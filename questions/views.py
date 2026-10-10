import json
import os

from django.contrib import messages
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required

from .models import Questions, WeakArea
from accounts.models import User

from resume.models import Resume
from resume.views import extract_text, min_text_length

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

from django.http import HttpResponse
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib import colors
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics


# ============================================================
# GEMINI SETUP
# ============================================================

try:
    from google import genai
except ImportError:
    genai = None


gemini_client = None

if genai is not None:
    api_key = os.getenv("GEMINI_API_KEY")

    if api_key:
        gemini_client = genai.Client(api_key=api_key)


# ============================================================
# CONSTANTS
# ============================================================

ALLOWED_TYPES = {
    "mcq",
    "technical",
    "behavioral",
}

ALLOWED_LEVELS = {
    "easy",
    "intermediate",
    "advanced",
    "expert",
}

ALLOWED_MODES = {
    "mock",
    "practice",
}

MAX_QUESTIONS = 30
WEAK_AREA_THRESHOLD = 70


# ============================================================
# INTERVIEW PREPARATION PAGE
# ============================================================


def interview_prep_view(request):
    user_id = request.session.get("user_id")

    if not user_id:
        messages.error(request, "Please sign in to continue.")
        return redirect("login")

    user_resumes = Resume.objects.filter(
        user_id=user_id
    ).order_by("-updated_at")

    return render(
        request,
        "dashboard_view/user/interview_prep.html",
        {
            "user_resumes": user_resumes,
        }
    )


# ============================================================
# VALIDATE GEMINI QUESTIONS
# ============================================================

def validate_generated_questions(data, expected_count, allowed_types):
    """
    Validate Gemini response before saving questions.
    """

    if not isinstance(data, dict):
        return False

    questions = data.get("questions")

    if not isinstance(questions, list):
        return False

    if len(questions) == 0:
        return False

    if len(questions) < expected_count:
        return False

    for q in questions[:expected_count]:

        if not isinstance(q, dict):
            return False

        question_type = q.get("type")

        if question_type not in allowed_types:
            return False

        question_text = q.get("question_text")

        if not isinstance(question_text, str):
            return False

        if not question_text.strip():
            return False

        # MCQ validation
        if question_type == "mcq":

            options = q.get("options")

            if not isinstance(options, list):
                return False

            if len(options) != 4:
                return False

            correct_answer = q.get("correct_answer")

            if correct_answer not in options:
                return False

        # Technical / Behavioral
        else:

            if q.get("options") is not None:
                return False

            if not isinstance(q.get("correct_answer"), str):
                return False

            if not q.get("correct_answer").strip():
                return False

    return True


# ============================================================
# FALLBACK QUESTIONS
# ============================================================

def fallback_questions(count, allowed_types):
    """
    Fallback questions if Gemini is unavailable.
    """

    bank = [

        {
            "type": "mcq",
            "level": "intermediate",
            "question_text":
                "What is the time complexity of binary search on a sorted array?",
            "options": [
                "O(n)",
                "O(log n)",
                "O(n log n)",
                "O(1)"
            ],
            "correct_answer": "O(log n)"
        },

        {
            "type": "mcq",
            "level": "intermediate",
            "question_text":
                "Which HTTP method is normally used to update an existing resource?",
            "options": [
                "GET",
                "POST",
                "PUT",
                "TRACE"
            ],
            "correct_answer": "PUT"
        },

        {
            "type": "mcq",
            "level": "easy",
            "question_text":
                "Which status code represents a successful HTTP request?",
            "options": [
                "200",
                "404",
                "500",
                "301"
            ],
            "correct_answer": "200"
        },

        {
            "type": "behavioral",
            "level": "intermediate",
            "question_text":
                "Tell me about a time you faced a difficult problem in a project and how you solved it.",
            "options": None,
            "correct_answer":
                "Explain the situation, task, action and result using the STAR method."
        },

        {
            "type": "behavioral",
            "level": "intermediate",
            "question_text":
                "Describe a situation where you had to learn a new technology quickly.",
            "options": None,
            "correct_answer":
                "Explain the situation, what you learned, how you learned it and the result."
        },

        {
            "type": "technical",
            "level": "advanced",
            "question_text":
                "How would you design a rate limiter for a public REST API?",
            "options": None,
            "correct_answer":
                "Discuss approaches such as token bucket or leaky bucket, storage, distributed synchronization and request limits."
        },

        {
            "type": "technical",
            "level": "intermediate",
            "question_text":
                "Explain the difference between authentication and authorization.",
            "options": None,
            "correct_answer":
                "Authentication verifies who the user is, while authorization determines what the authenticated user is allowed to access."
        },
    ]

    filtered = [
        q for q in bank
        if q["type"] in allowed_types
    ]

    if not filtered:
        filtered = bank

    result = []

    index = 0

    while len(result) < count:
        result.append(filtered[index % len(filtered)].copy())
        index += 1

    return result[:count]


# ============================================================
# OLD INTERVIEW PREP GENERATOR
# ============================================================


def generate_questions(request):
    """
    Handle interview preparation by topic or resume.

    Topic mode:
        Uses the existing topic-based generator.

    Resume mode:
        Forwards to quiz_generated_result_view(prep_mode=True), which
        generates the questions and then redirects to the exam page.
    """

    if request.method != "POST":
        return redirect("interview_prep")

    # 1. Check login
    user_id = request.session.get("user_id")

    if not user_id:
        messages.error(request, "Please sign in to continue.")
        return redirect("login")

    # 2. Detect preparation source BEFORE validating question_type
    source = (
        request.POST.get("source", "topic") or "topic"
    ).strip().lower()

    # 3. Resume mode does not submit question_type because
    #    your HTML disables those radio buttons.
    if source == "resume":
        return quiz_generated_result_view(request, prep_mode=True)

    # 4. Continue with topic mode
    topic_text = (
        request.POST.get("topic") or ""
    ).strip()

    questions_count = request.POST.get("questions_count", 10)

    question_type = (
        request.POST.get("question_type") or ""
    ).strip().lower()

    level = (
        request.POST.get("level", "intermediate") or "intermediate"
    ).strip().lower()

    mode = (
        request.POST.get("mode", "practice") or "practice"
    ).strip().lower()

    # 5. Validate question count
    try:
        questions_count = int(questions_count)
    except (ValueError, TypeError):
        questions_count = 10

    questions_count = max(1, min(questions_count, MAX_QUESTIONS))

    # 6. Validate question type
    if question_type not in ALLOWED_TYPES:
        messages.error(
            request,
            "Please select a valid question type."
        )
        return redirect("interview_prep")

    # 7. Validate topic
    if len(topic_text) < 2:
        messages.error(
            request,
            "Please describe what this session is for first."
        )
        return redirect("interview_prep")

    # 8. Validate difficulty and mode
    if level not in ALLOWED_LEVELS:
        level = "intermediate"

    if mode not in ALLOWED_MODES:
        mode = "practice"

    # 9. Generate topic questions
    generated = None

    if gemini_client is not None:
        try:
            system_prompt = """
You are an interview-question generator.

Generate questions specifically about the supplied topic.
Return ONLY valid JSON with a "questions" list.

Each question must contain:
- type: mcq, technical, or behavioral
- level: easy, intermediate, advanced, or expert
- question_text: the question
- options: four options for MCQ, otherwise null
- correct_answer: the correct answer or model answer

Rules:
1. Generate exactly the requested number of questions.
2. Use only the requested question type.
3. Use only the requested difficulty.
4. Keep all questions relevant to the topic.
5. MCQ answers must exactly match one of the four options.
6. Technical and behavioral questions must have options set to null.
7. Technical and behavioral questions must include useful model answers.
"""

            user_prompt = f"""
Topic: {topic_text}
Question type: {question_type}
Difficulty: {level}
Number of questions: {questions_count}

Generate the questions now.
"""

            response = gemini_client.models.generate_content(
                model="gemini-3.8-flash",
                contents=[system_prompt, user_prompt],
                config={
                    "temperature": 0.5,
                    "response_mime_type": "application/json",
                },
            )

            data = json.loads(response.text or "")

            if validate_generated_questions(
                data,
                questions_count,
                {question_type},
            ):
                generated = data["questions"][:questions_count]

        except Exception as exc:
            print("Gemini interview generation error:", repr(exc))
            generated = None

    # 10. Fallback if Gemini is unavailable or returns invalid data
    if generated is None:
        generated = fallback_questions(
            questions_count,
            {question_type},
        )

        for item in generated:
            item["level"] = level

    # 11. Save generated questions
    created_ids = []

    for item in generated:
        question = Questions.objects.create(
            user_id=user_id,
            resume=None,
            question_text=item["question_text"],
            question_type=item["type"],
            options=item.get("options"),
            correct_answer=item.get("correct_answer"),
            level=item.get("level", level),
        )

        created_ids.append(question.question_id)

    # 12. Store session data
    request.session["last_generated_question_ids"] = created_ids
    request.session["exam_mode"] = mode
    request.session["exam_topic"] = topic_text
    request.session["exam_level"] = level
    request.session["exam_question_type"] = question_type
    request.session["exam_source"] = "topic"

    # 13. Open the existing exam page
    return redirect("take_exam")
# ============================================================
# TAKE EXAM
# ============================================================

def take_exam_view(request):

    user_id = request.session.get(
        "user_id"
    )

    if not user_id:

        messages.error(
            request,
            "Please sign in to continue."
        )

        return redirect("login")

    question_ids = request.session.get(
        "last_generated_question_ids",
        []
    )

    questions = list(
        Questions.objects.filter(
            question_id__in=question_ids,
            user_id=user_id
        )
    )

    questions.sort(
        key=lambda q:
        question_ids.index(q.question_id)
    )

    if not questions:

        messages.error(
            request,
            "No generated questions found — try generating a new session."
        )

        return redirect("interview_prep")

    session_data = []

    for q in questions:

        entry = {

            "id": q.question_id,

            "type": q.question_type,

            "level": q.level,

            "q": q.question_text
        }

        if q.question_type == "mcq":

            options = q.options or []

            entry["options"] = options

            if q.correct_answer in options:

                entry["correct"] = options.index(
                    q.correct_answer
                )

            else:

                entry["correct"] = -1

        else:

            entry["options"] = []

            entry["correct"] = None

        session_data.append(entry)

    return render(

        request,

        "dashboard_view/user/take_exam.html",

        {
            "questions_for_js":
                session_data,

            "mode":
                request.session.get(
                    "exam_mode",
                    "practice"
                ),

            "topic":
                request.session.get(
                    "exam_topic",
                    "your generated session"
                )
        }
    )


# ============================================================
# SUBMIT EXAM
# ============================================================

def submit_exam_view(request):

    if request.method != "POST":

        return JsonResponse(
            {"error": "POST required."},
            status=405
        )

    user_id = request.session.get(
        "user_id"
    )

    if not user_id:

        return JsonResponse(
            {
                "error":
                    "Please sign in to continue."
            },
            status=401
        )

    try:

        data = json.loads(
            request.body or "{}"
        )

    except (ValueError, TypeError):

        return JsonResponse(
            {
                "error":
                    "Invalid submission."
            },
            status=400
        )

    overall = data.get("overall")

    if not isinstance(
        overall,
        (int, float)
    ):

        return JsonResponse(
            {
                "error":
                    "Missing or invalid overall score."
            },
            status=400
        )

    overall = max(
        0,
        min(100, overall)
    )

    topic_text = (
        request.session.get(
            "exam_topic"
        )
        or ""
    ).strip()

    if not topic_text:

        topic_text = "General practice"

    if overall < WEAK_AREA_THRESHOLD:

        WeakArea.objects.update_or_create(

            user_id=user_id,

            topic=topic_text,

            defaults={
                "performance_score":
                    overall
            }
        )

        weak_area_recorded = True

    else:

        WeakArea.objects.filter(

            user_id=user_id,

            topic=topic_text

        ).delete()

        weak_area_recorded = False

    return JsonResponse(
        {
            "saved": True,
            "weak_area_recorded":
                weak_area_recorded
        }
    )


# ============================================================
# GENERATE QUESTIONS PAGE
# ============================================================

def generate_quiz_view(request):

    user_id = request.session.get(
        "user_id"
    )

    if not user_id:

        messages.error(
            request,
            "Please sign in to continue."
        )

        return redirect("login")

    user_resumes = Resume.objects.filter(
        user_id=user_id
    ).order_by("-updated_at")

    return render(
        request,
        "dashboard_view/user/generate_questions.html",
        {
            "user_resumes":
                user_resumes
        }
    )


# ============================================================
# MAIN RESUME / TOPIC QUESTION GENERATOR
# ============================================================

def quiz_generated_result_view(request, prep_mode=False):
    """
    prep_mode=False -> "Generate Questions" page: shows questions + answers.
    prep_mode=True  -> Interview Prep page: saves questions, then redirects
                       to take_exam so the user ANSWERS them.
    """

    error_template = (
        "dashboard_view/user/interview_prep.html"
        if prep_mode
        else "dashboard_view/user/generate_questions.html"
    )

    if request.method != "POST":

        return redirect("quiz_questions")

    user_id = request.session.get(
        "user_id"
    )

    if not user_id:

        return redirect("login")

    try:

        user = User.objects.get(
            user_id=user_id
        )

    except User.DoesNotExist:

        return redirect("login")

    # ========================================================
    # SOURCE
    # ========================================================

    source = (
        request.POST.get(
            "source",
            "resume"
        )
        .strip()
        .lower()
    )

    # ========================================================
    # NUMBER OF QUESTIONS
    # ========================================================

    try:

        num_questions = int(
            request.POST.get(
                "questions_count",
                10
            )
        )

    except (ValueError, TypeError):

        num_questions = 10

    num_questions = max(
        1,
        min(30, num_questions)
    )

    # ========================================================
    # DIFFICULTY
    # ========================================================

    level = (
        request.POST.get(
            "level",
            "intermediate"
        )
        .strip()
        .lower()
    )

    if level not in ALLOWED_LEVELS:

        level = "intermediate"

    # ========================================================
    # VARIABLES
    # ========================================================

    resume = None
    resume_text = ""
    topic = ""

    # ========================================================
    # RESUME MODE
    # ========================================================

    if source == "resume":

        # ----------------------------------------------------
        # IMPORTANT:
        # Resume mode ALWAYS uses technical + behavioral.
        # MCQ is NOT allowed for resume mode.
        # ----------------------------------------------------

        if prep_mode:
            questions_type = [
                t for t in request.POST.getlist("resume_question_types")
                if t in ("technical", "behavioral")
            ]

            if not questions_type:
                return render(
                    request,
                    error_template,
                    {
                        "user_resumes": Resume.objects.filter(
                            user_id=user_id
                        ).order_by("-updated_at"),
                        "error": "Please select Technical, Behavioral (STAR), or both.",
                    }
                )
        else:
            questions_type = [
                "technical",
                "behavioral"
            ]

        # ----------------------------------------------------
        # Existing resume
        # ----------------------------------------------------

        existing_resume_id = request.POST.get(
            "existing_resume_id"
        )

        if existing_resume_id:

            try:

                resume = Resume.objects.get(

                    resume_id=existing_resume_id,

                    user_id=user_id
                )

            except Resume.DoesNotExist:

                return render(

                    request,

                    error_template,

                    {
                        "user_resumes":
                            Resume.objects.filter(
                                user_id=user_id
                            ).order_by("-updated_at"),

                        "error":
                            "Selected resume was not found."
                    }
                )

            resume_text = (
                resume.parsed_text
                or ""
            )

        # ----------------------------------------------------
        # New uploaded resume
        # ----------------------------------------------------

        elif request.FILES.get(
            "resume_file"
        ):

            resume_file = request.FILES.get(
                "resume_file"
            )

            file_name = resume_file.name

            if "." not in file_name:

                return render(

                    request,

                    error_template,

                    {
                        "user_resumes":
                            Resume.objects.filter(
                                user_id=user_id
                            ).order_by("-updated_at"),

                        "error":
                            "Please upload a PDF or DOCX resume."
                    }
                )

            extension = (
                file_name
                .rsplit(".", 1)[-1]
                .lower()
            )

            if extension == "pdf":

                file_type = "pdf"

            elif extension in [
                "docx",
                "doc"
            ]:

                file_type = "docx"

            else:

                return render(

                    request,

                    error_template,

                    {
                        "user_resumes":
                            Resume.objects.filter(
                                user_id=user_id
                            ).order_by("-updated_at"),

                        "error":
                            "Only PDF or DOCX resumes are supported."
                    }
                )

            # ------------------------------------------------
            # Read file
            # ------------------------------------------------

            raw_bytes = resume_file.read()

            try:

                resume_text, has_tables, content_meta = extract_text(

                    raw_bytes,

                    file_type
                )

            except Exception as e:

                import traceback

                traceback.print_exc()

                return render(

                    request,

                    error_template,

                    {
                        "user_resumes":
                            Resume.objects.filter(
                                user_id=user_id
                            ).order_by("-updated_at"),

                        "error":
                            "Resume extraction failed."
                    }
                )

            resume_text = resume_text or ""

            if len(
                resume_text.strip()
            ) < min_text_length:

                return render(

                    request,

                    error_template,

                    {
                        "user_resumes":
                            Resume.objects.filter(
                                user_id=user_id
                            ).order_by("-updated_at"),

                        "error":
                            "We couldn't find enough readable text in that resume."
                    }
                )

            # ------------------------------------------------
            # Save resume
            # ------------------------------------------------

            stored_path = default_storage.save(

                f"resumes/{user.user_id}/{file_name}",

                ContentFile(raw_bytes)
            )

            resume = Resume.objects.create(

                user=user,

                file_path=stored_path,

                file_type=file_type,

                parsed_text=resume_text
            )

        else:

            return render(

                request,

                error_template,

                {
                    "user_resumes":
                        Resume.objects.filter(
                            user_id=user_id
                        ).order_by("-updated_at"),

                    "error":
                        "Please choose a resume or upload a new one."
                }
            )

        if not resume_text:

            return render(

                request,

                error_template,

                {
                    "user_resumes":
                        Resume.objects.filter(
                            user_id=user_id
                        ).order_by("-updated_at"),

                    "error":
                        "Unable to extract text from the selected resume."
                }
            )

        topic = (
            "Resume interview practice"
            if prep_mode
            else "Questions based on my resume"
        )

    # ========================================================
    # TOPIC MODE
    # ========================================================

    elif source == "topic":

        topic = (
            request.POST.get(
                "topic"
            )
            or ""
        ).strip()

        if len(topic) < 2:

            return render(

                request,

                error_template,

                {
                    "user_resumes":
                        Resume.objects.filter(
                            user_id=user_id
                        ).order_by("-updated_at"),

                    "error":
                        "Please enter a topic or job description."
                }
            )

        # ----------------------------------------------------
        # IMPORTANT:
        # Topic mode allows all three types.
        # ----------------------------------------------------

        questions_type = request.POST.getlist(
            "questions_types"
        )

        questions_type = [
            q
            for q in questions_type
            if q in ALLOWED_TYPES
        ]

        if not questions_type:

            return render(

                request,

                error_template,

                {
                    "user_resumes":
                        Resume.objects.filter(
                            user_id=user_id
                        ).order_by("-updated_at"),

                    "error":
                        "Please select at least one question type."
                }
            )

    else:

        return redirect(
            "interview_prep" if prep_mode else "quiz_questions"
        )

    # ========================================================
    # GEMINI PROMPT
    # ========================================================

    if source == "resume":

        allowed_resume_types = [
            "technical",
            "behavioral"
        ]

        prompt = f"""
You are an expert technical and HR interviewer.

Generate exactly {num_questions} personalized interview questions
based ONLY on the candidate's resume.

RESUME CONTENT
==================================================

{resume_text}

==================================================

QUESTION TYPES

Generate only these types: {", ".join(questions_type)}

DIFFICULTY:

{level}

STRICT RULES:

1. Generate exactly {num_questions} questions.

2. Every question MUST be based on information actually present
   in the resume.

3. Use the candidate's:
   - skills
   - programming languages
   - frameworks
   - tools
   - projects
   - education
   - experience
   - certifications
   - technologies

4. NEVER invent a technology, project, company, experience,
   certification or skill that does not appear in the resume.

5. If more than one type is listed above, generate a balanced
   mixture of them. If only one is listed, use only that type.

6. Technical questions must ask about technologies, projects,
   implementation, architecture, programming concepts or
   technical decisions mentioned in the resume.

7. Behavioral questions should be connected to projects,
   education, work experience or other experiences mentioned
   in the resume.

8. Behavioral questions should be answerable using the STAR method.

9. Do NOT generate MCQ questions.

10. Technical questions must have:
    "options": null

11. Behavioral questions must have:
    "options": null

12. Every question must have a useful model answer in
    "correct_answer".

13. Do not repeat questions.

RETURN ONLY VALID JSON.

FORMAT:

{{
    "questions": [
        {{
            "type": "technical",
            "level": "{level}",
            "question_text": "Question here",
            "options": null,
            "correct_answer": "Model answer here"
        }},
        {{
            "type": "behavioral",
            "level": "{level}",
            "question_text": "Question here",
            "options": null,
            "correct_answer": "Model answer here"
        }}
    ]
}}
"""

    else:

        types_text = ", ".join(
            questions_type
        )

        prompt = f"""
You are an expert interview and assessment question generator.

Generate exactly {num_questions} questions based on the topic below.

TOPIC / JOB DESCRIPTION
==================================================

{topic}

==================================================

SELECTED QUESTION TYPES:

{types_text}

DIFFICULTY:

{level}

STRICT RULES:

1. Generate exactly {num_questions} questions.

2. Every question must be strongly relevant to the topic.

3. Use ONLY these question types:
   {types_text}

4. Do not generate any type that was not selected.

5. Questions must match the requested difficulty.

6. Do not repeat questions.

7. If the type is "mcq":

   - options must contain exactly four options.
   - exactly one option must be correct.
   - correct_answer must exactly match one option.

8. If the type is "technical":

   - options must be null.
   - correct_answer must contain a useful model answer.

9. If the type is "behavioral":

   - options must be null.
   - correct_answer must contain a useful model answer.
   - question should be suitable for a STAR-style answer.

10. Return ONLY valid JSON.

FORMAT:

{{
    "questions": [
        {{
            "type": "mcq",
            "level": "{level}",
            "question_text": "Question here",
            "options": [
                "Option A",
                "Option B",
                "Option C",
                "Option D"
            ],
            "correct_answer": "Option A"
        }},
        {{
            "type": "technical",
            "level": "{level}",
            "question_text": "Question here",
            "options": null,
            "correct_answer": "Model answer here"
        }},
        {{
            "type": "behavioral",
            "level": "{level}",
            "question_text": "Question here",
            "options": null,
            "correct_answer": "Model answer here"
        }}
    ]
}}
"""

    # ========================================================
    # GEMINI CHECK
    # ========================================================

    if gemini_client is None:

        return render(

            request,

            error_template,

            {
                "user_resumes":
                    Resume.objects.filter(
                        user_id=user_id
                    ).order_by("-updated_at"),

                "error":
                    "Gemini API is not configured. Please try again later."
            }
        )

    # ========================================================
    # CALL GEMINI
    # ========================================================

    try:

        response = gemini_client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,

            config={
                "temperature": 0.5,
                "response_mime_type":
                    "application/json"
            }
        )

        response_text = (
            response.text
            or ""
        ).strip()

    except Exception as e:

        print(
            "========== GEMINI ERROR =========="
        )

        print(
            repr(e)
        )

        print(
            "=================================="
        )

        return render(

            request,

            error_template,

            {
                "user_resumes":
                    Resume.objects.filter(
                        user_id=user_id
                    ).order_by("-updated_at"),

                "error":
                    f"Unable to generate questions. {str(e)}"
            }
        )

    # ========================================================
    # PARSE JSON
    # ========================================================

    try:

        data = json.loads(
            response_text
        )

    except (
        json.JSONDecodeError,
        KeyError,
        TypeError
    ):

        return render(

            request,

            error_template,

            {
                "user_resumes":
                    Resume.objects.filter(
                        user_id=user_id
                    ).order_by("-updated_at"),

                "error":
                    "Gemini returned an invalid question format. Please try again."
            }
        )

    generated_questions = data.get(
        "questions"
    )

    if not isinstance(
        generated_questions,
        list
    ):

        return render(

            request,

            error_template,

            {
                "user_resumes":
                    Resume.objects.filter(
                        user_id=user_id
                    ).order_by("-updated_at"),

                "error":
                    "No questions were generated. Please try again."
            }
        )

    # ========================================================
    # VALIDATE TYPES
    # ========================================================

    permitted_types = set(
        questions_type
    )

    valid_questions = []

    for item in generated_questions:

        if not isinstance(
            item,
            dict
        ):
            continue

        item_type = item.get(
            "type"
        )

        question_text = item.get(
            "question_text"
        )

        correct_answer = item.get(
            "correct_answer"
        )

        if item_type not in permitted_types:
            continue

        if not isinstance(
            question_text,
            str
        ):
            continue

        if not question_text.strip():
            continue

        if not isinstance(
            correct_answer,
            str
        ):
            continue

        if not correct_answer.strip():
            continue

        # ----------------------------------------------------
        # MCQ validation
        # ----------------------------------------------------

        if item_type == "mcq":

            options = item.get(
                "options"
            )

            if not isinstance(
                options,
                list
            ):
                continue

            if len(options) != 4:
                continue

            if correct_answer not in options:
                continue

        else:

            options = None

        valid_questions.append({

            "type":
                item_type,

            "level":
                item.get(
                    "level",
                    level
                ),

            "question_text":
                question_text.strip(),

            "options":
                options,

            "correct_answer":
                correct_answer.strip()
        })

    # ========================================================
    # CHECK GENERATED COUNT
    # ========================================================

    if not valid_questions:

        return render(

            request,

            error_template,

            {
                "user_resumes":
                    Resume.objects.filter(
                        user_id=user_id
                    ).order_by("-updated_at"),

                "error":
                    "Gemini could not generate valid questions. Please try again."
            }
        )

    # Only save requested number
    valid_questions = valid_questions[
        :num_questions
    ]

    # ========================================================
    # SAVE QUESTIONS
    # ========================================================

    saved_questions = []
    for item in valid_questions:
        question = Questions.objects.create(
            user=user,
            # VERY IMPORTANT:
            # Store the selected resume with the question.
            resume=resume if source == "resume" else None,
            question_text=item["question_text"],

            # VERY IMPORTANT:
            # Save each question's own type.
            question_type=item["type"],
            options=item["options"],
            correct_answer=item["correct_answer"],
            level=item["level"]
        )

        saved_questions.append(question)

    # ========================================================
    # STORE SESSION INFORMATION
    # ========================================================

    request.session["last_generated_question_ids"] = [q.question_id for q in saved_questions]

    mode = (request.POST.get("mode") or "practice").strip().lower()

    if mode not in ALLOWED_MODES:
        mode = "practice"

    request.session["exam_mode"] = mode if prep_mode else "practice"
    request.session["exam_topic"] = topic
    request.session["exam_level"] = level
    request.session["exam_source"] = source
    request.session["exam_question_types"] = questions_type

    # Interview Prep flow: let the user answer the questions.
    if prep_mode:
        return redirect("take_exam")

    # ========================================================
    # RESULT PAGE
    # ========================================================

    return render(request,"dashboard_view/user/question_result.html",
        {
            "questions": saved_questions,
            "topic": topic,
            "level": level,
            "question_type": questions_type,
            "source": source
        }
    )

def download_generated_questions_pdf(request):
    # Get generated question IDs from session
    question_ids = request.session.get("last_generated_question_ids", [])

    if not question_ids:
        return HttpResponse("No generated questions found.", status=404)

    # Get questions
    questions = Questions.objects.filter(question_id__in=question_ids)

    # Keep the same order as generated
    questions_dict = {q.question_id: q for q in questions}
    questions = [ questions_dict[qid] for qid in question_ids if qid in questions_dict]

    # Create PDF response
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        'attachment; filename="ResumeIQ_Generated_Questions.pdf"'
    )

    # PDF document
    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Title"],
        fontSize=20,
        leading=24,
        spaceAfter=10,
        textColor=colors.HexColor("#14171A"),
    )

    subtitle_style = ParagraphStyle(
        "SubtitleStyle",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        spaceAfter=20,
        textColor=colors.HexColor("#666666"),
    )

    question_style = ParagraphStyle(
        "QuestionStyle",
        parent=styles["Heading2"],
        fontSize=12,
        leading=17,
        spaceBefore=12,
        spaceAfter=8,
        textColor=colors.HexColor("#14171A"),
    )

    option_style = ParagraphStyle(
        "OptionStyle",
        parent=styles["Normal"],
        fontSize=10.5,
        leading=15,
        leftIndent=15,
        spaceAfter=5,
    )

    answer_label_style = ParagraphStyle(
        "AnswerLabelStyle",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        spaceBefore=8,
        spaceAfter=4,
        textColor=colors.HexColor("#3852E3"),
    )

    answer_style = ParagraphStyle( "AnswerStyle", parent=styles["Normal"], fontSize=10.5, leading=16, spaceAfter=10,)

    story = []

    # Title
    story.append(Paragraph("ResumeIQ – Generated Interview Questions",title_style))
    story.append(Paragraph("AI-generated interview questions for interview preparation.",subtitle_style))

    # Questions
    for index, question in enumerate(questions, start=1):
        question_text = question.question_text or ""

        story.append(Paragraph( f"<b>Question {index}</b><br/>{question_text}", question_style ) )

        # MCQ options
        if question.options:
            for option_index, option in enumerate(question.options, start=1 ):
                story.append(Paragraph(f"<b>{option_index}.</b> {option}",option_style))

        # Answer
        answer_label = ( "Correct Answer" if question.options else "Suggested Answer")

        story.append(Paragraph(answer_label,answer_label_style))
        answer = question.correct_answer or "No answer available."
        story.append(Paragraph(answer,answer_style))
        story.append(Spacer(1, 8))

    # Build PDF
    doc.build(story)

    return response