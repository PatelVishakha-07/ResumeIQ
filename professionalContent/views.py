import html as html_module
import json
import logging
import time
from functools import wraps
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
from resume.models import ResumeVersion

from .models import Export

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

logger = logging.getLogger(__name__)

GEMINI_MODEL = getattr(settings, "GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_FALLBACK_MODELS = getattr(settings, "GEMINI_FALLBACK_MODELS", [])
RETRYABLE_CODES = (500, 502, 503, 504)

MAX_QUESTIONS = 5

DOC_LABELS = {"cover_letter": "cover letter", "linkedin": "LinkedIn summary"}
VALID_EXPORT_TYPES = ("cover_letter", "linkedin")

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
        {"question": "Years of experience?", "field_type": "text"},
        {"question": "Top skills you want to highlight (comma-separated)?", "field_type": "text"},
        {"question": "One achievement you're proud of?", "field_type": "textarea"},
        {"question": "What are you looking for next? (optional)", "field_type": "textarea"},
    ],
}

# --- Cover letter: still resume-grounded --------------------------------

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

# --- LinkedIn summary: pure Q&A, NO resume involved ------------------------

LINKEDIN_NEXT_QUESTION_SYSTEM_PROMPT = """You are conducting a short, adaptive interview with a job seeker
who wants a LinkedIn "About" summary written for them. There is NO resume
involved — everything the summary says must come only from what they tell
you in this conversation.

Decide the SINGLE most useful next question to ask, based on the Q&A
history so far (e.g. current/target job title, years of experience, top
skills, a notable achievement, what they're looking for next, preferred
tone). Never re-ask something already covered.

Ask at most {max_q} questions total, but stop earlier and respond
done=true as soon as you have enough to write a specific, non-generic
summary — this can be as few as 2-3 questions if the person's answers are
already detailed, or the full {max_q} if their answers are short.

Respond with ONLY valid JSON, no prose, no markdown fences, in exactly one
of these two shapes:

{{"done": false, "question": "...", "hint": "...", "field_type": "text|textarea|select", "options": ["..."]}}

or

{{"done": true}}

"field_type" must be "select" only when you also provide 2-5 short "options".
Omit "options" entirely for "text"/"textarea". "hint" may be an empty string."""

LINKEDIN_SUMMARY_SYSTEM_PROMPT = """You write concise, first-person LinkedIn "About" section summaries
for job seekers, based ONLY on the intake Q&A provided below — there is
no resume. Never invent a job title, employer, years of experience, skill,
or achievement beyond what the person actually said in their answers.

150-220 words, first person, no buzzword soup. End with a short line
inviting relevant connections/opportunities.

Respond with ONLY the summary text. No markdown, no commentary."""


# =============================================================================
# Shared helpers
# =============================================================================

def _get_logged_in_user(request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    try:
        return User.objects.get(user_id=user_id)
    except User.DoesNotExist:
        return None


def _page_login_required(view):
    """
    For normal pages: if not signed in, flash a message and redirect to
    login. Otherwise the user is available as `request.app_user`.
    """
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = _get_logged_in_user(request)
        if not user:
            messages.error(request, "Please sign in to continue.")
            return redirect("login")
        request.app_user = user
        return view(request, *args, **kwargs)
    return wrapper


def _api_login_required(view):
    """
    For fetch/AJAX endpoints: if not signed in, return 401 JSON instead of
    redirecting. Otherwise the user is available as `request.app_user`.
    """
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = _get_logged_in_user(request)
        if not user:
            return JsonResponse({"error": "Please sign in to continue."}, status=401)
        request.app_user = user
        return view(request, *args, **kwargs)
    return wrapper


def _gemini_client():
    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if genai is None or not api_key:
        return None
    return genai.Client(api_key=api_key)


def _parse_qa_history(raw):
    """
    Safely parse the qa_history JSON sent by the browser.

    Always returns a list of {"question": str, "answer": str} dicts, capped
    in length and size. Anything malformed (invalid JSON, not a list,
    non-dict items) is dropped instead of raising.
    """
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [
        {
            "question": str(qa.get("question", ""))[:500],
            "answer": str(qa.get("answer", ""))[:5000],
        }
        for qa in data
        if isinstance(qa, dict)
    ][:MAX_QUESTIONS]


def _format_qa(qa_history, empty_text):
    """Turn the Q&A list into the 'Q: ... A: ...' text sent to the AI."""
    return "\n".join(
        f"Q: {qa.get('question', '')}\nA: {qa.get('answer', '')}" for qa in qa_history
    ) or empty_text


def _get_user_version(user, version_id):
    """A resume version, only if it belongs to this user (else 404)."""
    return get_object_or_404(ResumeVersion, version_id=version_id, versions__user=user)


def _get_user_versions(user):
    return (
        ResumeVersion.objects.filter(versions__user=user)
        .select_related("versions")
        .order_by("-created_at")
    )


def _render_pdf_bytes(title, text, user):
    """
    Turn plain text into PDF bytes (or None on failure).

    xhtml2pdf doesn't reliably wrap `white-space: pre-wrap` text, so we
    split on blank lines and render real <p> tags. Text is escaped first so
    stray < or & in the AI output can't break the PDF's HTML.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    content_html = "".join(f"<p>{html_module.escape(p)}</p>" for p in paragraphs)
    html = render_to_string(
        "dashboard_view/user/export_document_pdf.html",
        {"title": title, "content_html": content_html, "user": user},
    )
    buf = BytesIO()
    status = pisa.CreatePDF(html, dest=buf)
    return None if status.err else buf.getvalue()


# =============================================================================
# Pages
# =============================================================================

def professionalContent(request):
    return render(request, "dashboard_view/user/professional_content.html")


@_page_login_required
def export_documents_choice(request):
    """Chooser page with links to the cover letter and LinkedIn wizards."""
    return render(request, "dashboard_view/user/professional_content.html")


@_page_login_required
def cover_letter_wizard_view(request):
    """Own page, own template. Resume-based — picks a version first."""
    return render(
        request,
        "dashboard_view/user/cover_letter_wizard.html",
        {"versions": _get_user_versions(request.app_user)},
    )


@_page_login_required
def linkedin_wizard_view(request):
    """
    Own page. No resume selection — the page goes straight into the AI Q&A
    on load, and the summary is built purely from those answers.
    """
    return render(request, "dashboard_view/user/linkedin_summary_wizard.html")


# =============================================================================
# LinkedIn autosave
# =============================================================================

def _save_linkedin_export(user, text, export_id=None):
    """Create the LinkedIn export row, or update it if export_id is given."""
    pdf_bytes = _render_pdf_bytes("LinkedIn Summary", text, user)
    if pdf_bytes is None:
        return None

    export = None
    if export_id:
        export = Export.objects.filter(
            export_id=export_id, user=user, export_type="linkedin"
        ).first()

    if export is None:
        export = Export(user=user, resume=None, export_type="linkedin")
    elif export.file_path:
        export.file_path.delete(save=False)  # remove the old PDF from storage

    export.content = text
    filename = f"{user.name.replace(' ', '_')}_linkedin.pdf"
    export.file_path.save(filename, ContentFile(pdf_bytes), save=False)
    export.save()
    return export


@require_http_methods(["POST"])
@_api_login_required
def autosave_linkedin(request):
    text = (request.POST.get("content") or "").strip()
    if not text:
        return JsonResponse({"error": "Nothing to save."}, status=400)

    try:
        export_id = int(request.POST.get("export_id") or 0) or None
    except ValueError:
        export_id = None

    export = _save_linkedin_export(request.app_user, text, export_id)
    if export is None:
        return JsonResponse({"error": "Couldn't generate the PDF."}, status=500)

    return JsonResponse({"saved": True, "export_id": export.export_id})


# =============================================================================
# AI: adaptive next question
# =============================================================================

def _generate_with_retry(client, contents, config, attempts=3):
    models_to_try = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]
    last_err = None
    for model in models_to_try:
        for attempt in range(attempts):
            try:
                return client.models.generate_content(model=model, contents=contents, config=config)
            except Exception as e:
                last_err = e
                code = getattr(e, "code", None)
                logger.warning("Gemini call failed (%s, attempt %d): %r", model, attempt + 1, e)
                if code in RETRYABLE_CODES and attempt < attempts - 1:
                    time.sleep(2 ** attempt)
                    continue
                break  # 429, 400, 404, etc.: try the next model
    raise last_err


def _ai_next_question(export_type, resume_text, qa_history):
    """
    resume_text is only meaningful for export_type == 'cover_letter'.
    For 'linkedin', resume_text is always None and the prompt never
    mentions a resume at all.
    """
    if len(qa_history) >= MAX_QUESTIONS:
        return {"done": True}

    client = _gemini_client()
    if client is not None:
        history_text = _format_qa(qa_history, "(no questions asked yet)")

        if export_type == "linkedin":
            system_prompt = LINKEDIN_NEXT_QUESTION_SYSTEM_PROMPT.format(max_q=MAX_QUESTIONS)
            user_content = f"Q&A SO FAR:\n{history_text}"
        else:
            system_prompt = NEXT_QUESTION_SYSTEM_PROMPT_TEMPLATE.format(
                doc_label=DOC_LABELS[export_type], max_q=MAX_QUESTIONS
            )
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
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            data = json.loads(response.text)

            if data.get("done") is True:
                return {"done": True}

            if isinstance(data.get("question"), str) and data["question"].strip():
                field_type = data.get("field_type")
                return {
                    "done": False,
                    "question": data["question"].strip(),
                    "hint": data.get("hint", "") or "",
                    "field_type": field_type if field_type in ("text", "textarea", "select") else "text",
                    "options": data.get("options") if isinstance(data.get("options"), list) else [],
                    "source": "ai",
                }
        except Exception:
            logger.exception("Gemini error while generating the next question")

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
@_api_login_required
def generate_next_question(request):
    export_type = request.POST.get("export_type")
    if export_type not in VALID_EXPORT_TYPES:
        return JsonResponse({"error": "Invalid document type."}, status=400)

    qa_history = _parse_qa_history(request.POST.get("qa_history"))

    resume_text = None
    if export_type == "cover_letter":
        # Cover letter requires a resume version; LinkedIn never uses one.
        version = _get_user_version(request.app_user, request.POST.get("version_id"))
        resume_text = version.content_snapshot

    return JsonResponse(_ai_next_question(export_type, resume_text, qa_history))


# =============================================================================
# AI: final document
# =============================================================================

def _ai_generate_final_document(export_type, resume_text, qa_history):
    qa_text = _format_qa(qa_history, "(no additional intake answers)")

    if export_type == "linkedin":
        system_prompt = LINKEDIN_SUMMARY_SYSTEM_PROMPT
        user_content = f"INTAKE ANSWERS:\n{qa_text}"
    else:
        system_prompt = COVER_LETTER_SYSTEM_PROMPT
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
                    max_output_tokens=2048,
                    # Writing a short summary/letter doesn't need multi-step
                    # reasoning. Without this, "thinking" tokens can eat
                    # most of max_output_tokens before any visible text is
                    # written, cutting the answer off mid-sentence.
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            text = (response.text or "").strip()
            if text:
                return text, "ai"
        except Exception:
            logger.exception("Gemini error while generating the final document")

    return (
        "We couldn't reach the AI writer just now. You can still write this "
        "draft yourself below, or go back and try Generate again in a moment."
    ), "fallback"


@require_http_methods(["POST"])
@_api_login_required
def generate_final_document(request):
    export_type = request.POST.get("export_type")
    if export_type not in VALID_EXPORT_TYPES:
        return JsonResponse({"error": "Invalid document type."}, status=400)

    qa_history = _parse_qa_history(request.POST.get("qa_history"))

    resume_text = None
    if export_type == "cover_letter":
        version = _get_user_version(request.app_user, request.POST.get("version_id"))
        resume_text = version.content_snapshot

    content, source = _ai_generate_final_document(export_type, resume_text, qa_history)
    return JsonResponse({"content": content, "source": source})


# =============================================================================
# Cover letter: save + PDF download
# =============================================================================

@require_http_methods(["POST"])
@_page_login_required
def save_export_document(request, export_type, version_id=None):
    """
    Cover letters only. URL: export/save/<version_id>/<export_type>/

    LinkedIn summaries are saved automatically through `autosave_linkedin`,
    so they never come through this view.
    """
    user = request.app_user

    if export_type != "cover_letter" or version_id is None:
        messages.error(request, "Invalid document type.")
        return redirect("export_documents")

    final_text = (request.POST.get("content") or "").strip()
    if not final_text:
        messages.error(request, "There's nothing to save yet.")
        return redirect("export_documents")

    version = _get_user_version(user, version_id)

    pdf_bytes = _render_pdf_bytes("Cover Letter", final_text, user)
    if pdf_bytes is None:
        messages.error(request, "We couldn't generate the PDF for this document.")
        return redirect("export_documents")

    filename = f"{user.name.replace(' ', '_')}_cover_letter_v{version.version_number}.pdf"
    export = Export(
        user=user,
        resume=version.versions,
        export_type="cover_letter",
        content=final_text,
    )
    export.file_path.save(filename, ContentFile(pdf_bytes), save=True)

    messages.success(request, "Cover Letter saved to your exports.")

    # Cover letters download as a PDF, since they're commonly attached to an
    # application or printed.
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

