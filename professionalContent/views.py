import json
import time
from io import BytesIO
 
from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods
from xhtml2pdf import pisa
 
from accounts.models import User
from resume.models import Resume, ResumeVersion
 
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

GEMINI_MODEL = getattr(settings, "GEMINI_MODEL", "gemini-3.6-flash")
 
 
MAX_QUESTIONS = 5
 
DOC_LABELS = {"cover_letter": "cover letter", "linkedin": "LinkedIn summary"}

# --- Fallback question banks (used only if AI is unavailable) ----------------
FALLBACK_QUESTIONS = {
    "cover_letter": [
        {"question": "Which company is this for?", "field_type": "text"},
        {"question": "What role are you applying for?", "field_type": "text"},
        {"question": "Paste the job description, or its key requirements.", "field_type": "textarea"},
        {"question": "In a sentence or two, why this role?", "field_type": "textarea"},
        {"question": "What tone should the letter have?", "field_type": "select",
         "options": ["Formal", "Conversational", "Confident"]},
    ],
    "linkedin": [
        {"question": "Current or target job title?", "field_type": "text"},
        {"question": "Top skills you want to highlight (comma-separated)?", "field_type": "text"},
        {"question": "One achievement you're proud of?", "field_type": "textarea"},
        {"question": "What are you looking for next? (optional)", "field_type": "textarea"},
        {"question": "What tone should the summary have?", "field_type": "select",
         "options": ["Professional", "Friendly", "Bold"]},
    ],
}

NEXT_QUESTION_SYSTEM_PROMPT_TEMPLATE = """You are conducting a short, adaptive intake interview with a
job seeker before writing their {doc_label}. You've been given their resume
text and the question/answer pairs already collected in this conversation.
 
Decide the SINGLE most useful next question to ask — one that fills a real
gap the resume doesn't already answer (e.g. target company, role, tone,
an achievement to foreground, what they want next). Never re-ask something
already covered in the Q&A history or already obvious from the resume text.
 
Ask at most {max_q} questions total. Once you have enough to write a strong,
specific {doc_label} (often after 3-4 questions), stop and respond with
done=true instead of asking another question.
 
Respond with ONLY valid JSON, no prose, no markdown fences, in exactly one
of these two shapes:
 
{{"done": false, "question": "...", "hint": "...", "field_type": "text|textarea|select", "options": ["..."]}}
 
or
 
{{"done": true}}
 
"field_type" must be "select" only when you also provide 2-5 short "options".
Omit "options" entirely for "text"/"textarea". "hint" may be an empty string."""
 
COVER_LETTER_SYSTEM_PROMPT = """You write tailored, professional cover letters for job seekers, based
on their resume text and an intake Q&A about the target role/company/tone.
 
First person, 3-4 short paragraphs, no bracket placeholders unless truly
unknown. Ground every claim in the resume text provided — never invent
experience, employers, or metrics that aren't there.
 
Respond with ONLY the cover letter body text. No markdown, no commentary."""
 
LINKEDIN_SUMMARY_SYSTEM_PROMPT = """You write concise, first-person LinkedIn "About" section summaries
for job seekers, based on their resume text and an intake Q&A.
 
150-220 words, first person, no buzzword soup, grounded only in the resume
text and answers provided. End with a short line inviting relevant
connections/opportunities.
 
Respond with ONLY the summary text. No markdown, no commentary."""


def _get_logged_in_user(request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    try:
        return User.objects.get(user_id = user_id)
    except User.DoesNotExist:
        return None

    
def _gemini_client():
    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if genai is None or not api_key:
        return None
    return genai.Client(api_key=api_key)


 #-----pages------------------------

def professionalContent(request):
    return render(
        request,
        "dashboard_view/user/professional_content.html"
    )

def export_documents_choice(request):
    # """Chooser page: two cards, each a real link to its own wizard page."""
    user = _get_logged_in_user(request)
    if not user:
        messages.error(request, "Please sign in to continue.")
        return redirect("login")
    return render(request, "dashboard_view/user/export_documents_choice.html")

def _get_user_versions(user):
    return(ResumeVersion.objects.filter(versions__user = user).select_related("versions").order_by("-created_at"))



def cover_letter_wizard_view(request):
    """Own page, own template (cover_letter_wizard.html), own CSS file."""
    user = _get_logged_in_user(request)
    if not user:
        messages.error(request, "Please sign in to continue.")
        return redirect("login")
 
    return render(
        request,
        "dashboard_view/user/cover_letter_wizard.html",
        {"versions": _get_user_versions(user)},
    )
 
 
def linkedin_wizard_view(request):
    """Own page, own template (linkedin_summary_wizard.html), own CSS file."""
    user = _get_logged_in_user(request)
    if not user:
        messages.error(request, "Please sign in to continue.")
        return redirect("login")
 
    return render(
        request,
        "dashboard_view/user/linkedin_summary_wizard.html",
        {"versions": _get_user_versions(user)},
    )


#-----AI adaptive next questiions-----------------


GEMINI_FALLBACK_MODELS = getattr(settings, "GEMINI_FALLBACK_MODELS", [])

RETRYABLE_CODES = (500, 502, 503, 504)

def _generate_with_retry(client, contents, config, attempts=3):
    models = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]
    last_err = None
    for model in models:
        for attempt in range(attempts):
            try:
                return client.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except Exception as e:
                last_err = e
                code = getattr(e, "code", None)
                print(f"GEMINI RETRY ({model}, attempt {attempt + 1}):", repr(e))
                if code in RETRYABLE_CODES and attempt < attempts - 1:
                    time.sleep(2 ** attempt)
                    continue
                break  # 429, 400, 404, etc.: try the next model
    raise last_err

def _ai_next_question(export_type, resume_text, qa_history):
    client = _gemini_client()
    doc_label = DOC_LABELS[export_type]

    if len(qa_history) >= MAX_QUESTIONS :
        return {"done": True}

    if client is not None:
        system_prompt = NEXT_QUESTION_SYSTEM_PROMPT_TEMPLATE.format(
            doc_label=doc_label, max_q=MAX_QUESTIONS
        )
        history_text = "\n".join(
            f"Q: {qa.get('question','')}\nA: {qa.get('answer','')}" for qa in qa_history
        ) or "(no questions asked yet)"
        user_content = f"RESUME TEXT:\n{resume_text}\n\nQ&A SO FAR:\n{history_text}"
 
        try:
            response = _generate_with_retry(
                client,
                user_content,
                types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.4,
                    max_output_tokens=1000,
                    response_mime_type="application/json",
                ),
            )
            data = json.loads(response.text)
 
            if data.get("done") is True:
                return {"done": True}
 
            if isinstance(data.get("question"), str) and data["question"].strip():
                return {
                    "done": False,
                    "question": data["question"].strip(),
                    "hint": data.get("hint", "") or "",
                    "field_type": data.get("field_type") if data.get("field_type") in ("text", "textarea", "select") else "text",
                    "options": data.get("options") if isinstance(data.get("options"), list) else [],
                    "source": "ai",
                }
        except Exception as e:
            print("GEMINI ERROR (next_question):", repr(e))
 
    # --- Fallback: fixed list, walked by index -----------------------------
    bank = FALLBACK_QUESTIONS[export_type]
    index = len(qa_history)
    if index >= len(bank):
        return {"done": True}
 
    q = bank[index]
    return {
        "done": False,
        "question": q["question"],
        "hint": "",
        "field_type": q["field_type"],
        "options": q.get("options", []),
        "source": "fallback",
    }
 
 
@require_http_methods(["POST"])
def generate_next_question(request):
    user = _get_logged_in_user(request)
    if not user:
        return JsonResponse({"error": "Please sign in to continue."}, status=401)
 
    version_id = request.POST.get("version_id")
    export_type = request.POST.get("export_type")
    if export_type not in ("cover_letter", "linkedin"):
        return JsonResponse({"error": "Invalid document type."}, status=400)
 
    try:
        qa_history = json.loads(request.POST.get("qa_history") or "[]")
    except (TypeError, ValueError):
        qa_history = []
 
    version = get_object_or_404(ResumeVersion, version_id=version_id, versions__user=user)
    result = _ai_next_question(export_type, version.content_snapshot, qa_history)
    return JsonResponse(result)
 
 
# --- AI: final document ----------------------------------------------------
 
def _ai_generate_final_document(export_type, resume_text, qa_history):
    system_prompt = (
        COVER_LETTER_SYSTEM_PROMPT if export_type == "cover_letter" else LINKEDIN_SUMMARY_SYSTEM_PROMPT
    )
    qa_text = "\n".join(
        f"Q: {qa.get('question','')}\nA: {qa.get('answer','')}" for qa in qa_history
    ) or "(no additional intake answers)"
    user_content = f"RESUME TEXT:\n{resume_text}\n\nINTAKE ANSWERS:\n{qa_text}"
 
    client = _gemini_client()
    if client is not None:
        try:
            response = _generate_with_retry(
            client,
            user_content,
            types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.5,
                    max_output_tokens=1500,
                ),
            )
            text = (response.text or "").strip()
            if text:
                return text, "ai"
        except Exception as e:
            print("GEMINI ERROR (final_document):", repr(e))
 
    return (
        "We couldn't reach the AI writer just now. You can still write this "
        "draft yourself below, or go back and try Generate again in a moment."
    ), "fallback"
 
 
@require_http_methods(["POST"])
def generate_final_document(request):
    user = _get_logged_in_user(request)
    if not user:
        return JsonResponse({"error": "Please sign in to continue."}, status=401)
 
    version_id = request.POST.get("version_id")
    export_type = request.POST.get("export_type")
    if export_type not in ("cover_letter", "linkedin"):
        return JsonResponse({"error": "Invalid document type."}, status=400)
 
    try:
        qa_history = json.loads(request.POST.get("qa_history") or "[]")
    except (TypeError, ValueError):
        qa_history = []
 
    version = get_object_or_404(ResumeVersion, version_id=version_id, versions__user=user)
    content, source = _ai_generate_final_document(export_type, version.content_snapshot, qa_history)
    return JsonResponse({"content": content, "source": source})
 
 
# --- Save + PDF download ----------------------------------------------------
 
@require_http_methods(["POST"])
def save_export_document(request, version_id, export_type):
    user = _get_logged_in_user(request)
    if not user:
        messages.error(request, "Please sign in to continue.")
        return redirect("login")
 
    if export_type not in ("cover_letter", "linkedin"):
        messages.error(request, "Invalid document type.")
        return redirect("export_documents")
 
    version = get_object_or_404(ResumeVersion, version_id=version_id, versions__user=user)
    resume = version.versions
 
    final_text = (request.POST.get("content") or "").strip()
    if not final_text:
        messages.error(request, "There's nothing to save yet.")
        return redirect("export_documents")
 
    title = "Cover Letter" if export_type == "cover_letter" else "LinkedIn Summary"
    html = render_to_string(
        "dashboard_view/user/export_document_pdf.html",
        {"title": title, "content": final_text, "user": user},
    )
 
    pdf_buffer = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=pdf_buffer)
    if pisa_status.err:
        messages.error(request, "We couldn't generate the PDF for this document.")
        return redirect("export_documents")
 
    from resume.models import Export  # adjust import path to your project layout
 
    filename_base = f"{user.name.replace(' ', '_')}_{export_type}_v{version.version_number}.pdf"
    export = Export(user=user, resume=resume, export_type=export_type)
    export.file_path.save(filename_base, ContentFile(pdf_buffer.getvalue()), save=True)
 
    messages.success(request, f"{title} saved to your exports.")
 
    response = HttpResponse(pdf_buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f"attachment; filename={filename_base}"
    return response