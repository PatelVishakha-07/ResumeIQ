import json
from django.contrib import messages
from django.shortcuts import render, redirect
from .models import Questions, WeakArea
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
import os
from accounts.models import User

try:
    # from openai import OpenAI
    from google import genai
except ImportError:
    # OpenAI = None
    genai = None

gemini_client = None

if genai is not None:
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        gemini_client = genai.Client(api_key=api_key)

system_prompt = """You are an interview-question generator for a career-readiness platform.

Given a topic, technology, role, or pasted job description, generate interview
practice questions tailored specifically to that input — never generic filler.

Respond with ONLY valid JSON, no prose, no markdown fences, in exactly this shape:
{
  "questions": [
    {
      "type": "mcq" | "behavioral" | "technical",
      "level": "easy" | "intermediate" | "advanced" | "expert",
      "question_text": "the question itself",
      "options": ["four options"],
      "correct_answer": "the correct option, verbatim"
    }
  ]
}

IMPORTANT:
- Generate exactly the requested number of questions.
- Use ONLY the requested question type.
- Use ONLY the requested difficulty level.
- Questions must be relevant to the given topic.
- MCQ questions must contain exactly four options.
- correct_answer must exactly match one of the options.

Behavioral questions should be answerable with the STAR method.
Technical questions should be specific to the tools/technologies implied by the input."""

allowed_types = {"mcq", "behavioral", "technical"}
allowed_levels = {"easy", "intermediate", "advanced", "expert"}
allowed_modes = {"mock", "practice"}
max_questions = 30
weak_area_threshold = 70

# function to show interview preparation page
def interview_prep_view(request):
    return render(request, "dashboard_view/user/interview_prep.html")

def validate_questions(data):
    if not isinstance(data, dict):
        return False

    qs = data.get("questions")
    if not isinstance(qs, list) or len(qs) == 0:
        return False

    for q in qs:
        if not isinstance(q, dict):
            return False
        if q.get("type") not in allowed_types:
            return False
        if q.get("level") not in allowed_levels:
            return False
        if not isinstance(q.get("question_text"), str) or not q["question_text"].strip():
            return False

        if q["type"] == "mcq":
            options = q.get("options")
            if not isinstance(options, list) or len(options) <= 2:
                return False

            if q.get("correct_answer") not in options:
                return False

    return True

#used when OpenAI isn't installed/configured, or the API call fails for any reason — the feature should degrade gracefully, never 500.
def fallback_questions(count, allowed_types):
    bank = [
        {
            "type": "mcq", "level": "intermediate",
            "question_text": "What is the time complexity of binary search on a sorted array?",
            "options": ["O(n)", "O(log n)", "O(n log n)", "O(1)"], "correct_answer": "O(log n)"
        },
        {
            "type": "mcq", "level": "intermediate",
            "question_text": "In REST APIs, which HTTP method is idempotent?",
            "options": ["POST", "PATCH", "PUT", "CONNECT"], "correct_answer": "PUT"
        },
        {
            "type": "mcq", "level": "easy",
            "question_text": "Which of these is NOT a valid HTTP status code range?",
            "options": ["2xx Success", "3xx Redirection", "6xx Client Error", "5xx Server Error"],
            "correct_answer": "6xx Client Error"
        },
        {
            "type": "behavioral", "level": "intermediate",
            "question_text": "Tell me about a time you had to push back on a decision made by a teammate or manager."
        },
        {
            "type": "behavioral", "level": "intermediate",
            "question_text": "Describe a project where the requirements changed midway through. How did you handle it?"
        },
        {   
            "type": "technical", "level": "advanced",
            "question_text": "Walk through how you would design a rate limiter for a public API."
        },
    ]

    filtered = [q for q in bank if q["type"] in allowed_types] or bank

    out = []

    i=0
    while len(out) < count:
        out.append(filtered[i % len(filtered)])
        i += 1
    return out[:count]

def generate_questions(request):
    if request.method != "POST":
        return redirect("interview_prep")

    user_id = request.session.get("user_id")
    if not user_id:
        messages.error(request, "Please sign in to continue.")
        return redirect("login")

    topic_text = (request.POST.get("topic") or "").strip()
    questions_count = request.POST.get("questions_count", 10)
    question_types = request.POST.get("question_type")
    level = request.POST.get("level", "intermediate")
    mode = request.POST.get("mode", "practice")

    try:
        questions_count = int(questions_count)
        if questions_count < 1:
            questions_count = 10

        if questions_count > max_questions:
            questions_count = max_questions
    except (ValueError, TypeError):
        questions_count = 10


    if question_types not in allowed_types:
        messages.error(request, "Please select a valid question type.")
        return redirect("interview_prep")
 
    if len(topic_text) < 2:
        messages.error(request, "Please describe what this session is for first.")
        return redirect("interview_prep")

    if level not in allowed_levels:
        level = "intermediate"

    if mode not in allowed_modes:
        mode = "practice"

    generated = None

    # if OpenAI is not None:
    if gemini_client is not None:
        try:
            # client = OpenAI()
            user_prompt = (
                f"Topic / job description:\n{topic_text}\n\n"
                f"Generate exactly {questions_count} questions.\n"
                f"Only use these question types: {', '.join(question_types)}.\n"
                f"Target level: {level}."
            )
            """ response = client.chat.completions.create(            
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.5,
                max_tokens=2200,
            ) """

            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    system_prompt,
                    user_prompt
                ],
                config={
                    "temperature": 0.5,
                    "response_mime_type": "application/json",
                }
            )

            # raw = response.choices[0].message.content
            raw = response.text
            data = json.loads(raw)
            if validate_questions(data):
                generated = data["questions"][:questions_count]
        except Exception as e:
            print("Gemini error:", e)
            generated = None

    if generated is None:
        # generated = fallback_questions(questions_count, {question_type})
        generated = fallback_questions(questions_count, {question_types})

    created_ids = []
    for q in generated:
        question = Questions.objects.create(
            user_id = user_id,
            resume=None,
            question_text=q["question_text"],
            question_type=q["type"],
            options=q.get("options"),
            correct_answer=q.get("correct_answer"),
            level=q["level"],
        )
        created_ids.append(question.question_id)

    request.session["last_generated_question_ids"] = created_ids

    request.session["exam_mode"] = mode
    request.session["exam_topic"] = topic_text
    request.session["exam_level"] = level
    request.session["exam_question_type"] = question_types
 
    return redirect("take_exam")


def take_exam_view(request):
    user_id = request.session.get("user_id")
    if not user_id:
        messages.error(request, "Please sign in to continue.")
        return redirect("login")

    question_ids = request.session.get("last_generated_question_ids", [])

    questions = list(Questions.objects.filter(question_id__in=question_ids, user_id=user_id))

    questions.sort(key=lambda q: question_ids.index(q.question_id))

    if not questions:
        messages.error(request, "No generated questions found — try generating a new session.")
        return redirect("interview_prep")

    session_data = []
    for q in questions:
        entry = {
            "type": q.question_type,
            "level": q.level,
            "q": q.question_text
        }
        if q.question_type == "mcq":
            options = q.options
            entry["options"] = options
            entry["correct"] = options.index(q.correct_answer) if q.correct_answer in options else -1
        session_data.append(entry)

    return render(request, "dashboard_view/user/take_exam.html", { "questions_for_js":session_data, "mode": request.session.get("exam_mode", "practice"), "topic": request.session.get("exam_topic", "your generated session")})

def submit_exam_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    user_id = request.session.get("user_id")

    if not user_id:
        return JsonResponse({"error": "Please sign in to continue."}, status=401)

    try:
        data = json.loads(request.body or '{}')            
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid submission."}, status=400)

    overall = data.get("overall")

    if not isinstance(overall, (int, float)):
        return JsonResponse({"error": "Missing or invalid overall score."}, status=400)

    overall = max(0, min(100, overall))

    topic_text =  (request.session.get("exam_topic") or "").strip() or "General practice"

    if overall < weak_area_threshold:
        WeakArea.objects.update_or_create(
            user_id = user_id,
            topic = topic_text,
            defaults = {"performance_score": overall}
        )
        weak_area_recorded = True

    else:
        WeakArea.objects.filter(user_id=user_id, topic = topic_text).delete()
        weak_area_recorded = False

    return JsonResponse({"saved": True, "weak_area_recorded": weak_area_recorded})

def generate_quiz_view(request):
    return render(request, "dashboard_view/user/generate_questions.html")

def quiz_generated_result_view(request):
    if request.method != "POST":
        return redirect("generate_quiz")

    topic = request.POST.get("topic", "").strip()
    level = request.POST.get("level")
    questions_type = request.POST.get("question_type")

    try:
        num_questions = int(request.POST.get("num_questions",10))
    except ValueError:
        num_questions = 10

    if not topic:
        return redirect("generate_quiz")
    
    if questions_type not in ["mcq", "behavioral", "technical"]:
        return redirect("generate_quiz")

    if level not in ["easy", "intermediate", "advanced", "expert"]:
        return redirect("generate_quiz")

    if num_questions < 1:
        num_questions = 1

    if num_questions > 50:
        num_questions = 50

    # client = OpenAI()  

    prompt = f"""
Generate {num_questions} high-quality interview/practice questions.

Topic:
{topic}

Question Type:
{questions_type}

Level:
{level}

Follow these rules strictly:

1. Generate exactly {num_questions} questions.
2. Questions must be relevant to the topic.
3. Questions must match the selected level.
4. Do not repeat questions.
5. Every question must have a correct answer.
6. If question type is "mcq":
   - Generate exactly 4 options.
   - Only one option must be correct.
   - Store the correct answer exactly as one of the options.
7. If question type is "behavioral":
   - Generate realistic interview behavioral questions.
   - Do not generate MCQ options.
8. If question type is "technical":
   - Generate technical interview questions.
   - Do not generate MCQ options.

Return ONLY valid JSON in this format:

{{
    "questions": [
        {{
            "question_text": "Question here",
            "options": ["Option A", "Option B", "Option C", "Option D"],
            "correct_answer": "Correct option"
        }}
    ]
}}

For behavioral and technical questions,
"options" must be null.

Do not add markdown.
Do not add explanations outside the JSON.
"""
    if gemini_client is None:
            return render(
                request,
                "dashboard_view/user/generate_questions.html",
                {
                    "error": "Gemini API is not configured. Please try again later."
                }
            )
    
    """ response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
            "role": "user",
            "content": prompt
        }
        ]
    ) """

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={
                "temperature": 0.5,
                "response_mime_type": "application/json",
            }
        )

        response_text = response.text

    except Exception as e:
        print("========== GEMINI ERROR ==========")
        print(repr(e))
        print("==================================")

        return render(request,
            "dashboard_view/user/generate_questions.html",
            {
                "error": f"Unable to generate questions. {str(e)}"
            }
        )

    """ response_text = response.choices[0].message.content

    if response_text.startswith("```json"):
        response_text = response_text[7:]

    if response_text.startswith("```"):
        response_text = response_text[3:]

    if response_text.endswith("```"):
        response_text = response_text[:-3]

    response_text = response_text.strip() """

    try:
        data = json.loads(response_text)
    except (json.JSONDecodeError, KeyError, TypeError):
        return render(
            request,
            "dashboard_view/user/generate_questions.html",
            {
                "error": "Unable to generate questions. Please try again."
            }
        )

    saved_questions = []

    user_id = request.session.get("user_id")

    if not user_id:
        return redirect("login")

    user = User.objects.get(user_id=user_id)

    for item in data["questions"]:
        question = Questions.objects.create(
            user = user,
            question_text = item["question_text"],
            question_type = questions_type,
            options = item.get("options"),
            correct_answer = item.get("correct_answer"),
            level = level
        )

        saved_questions.append(question)

    return render(
        request,
        "dashboard_view/user/question_result.html",
        {
            "questions": saved_questions,
            "topic": topic,
            "level": level,
            "question_type": questions_type,
        }
    )