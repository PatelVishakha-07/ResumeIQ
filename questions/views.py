import json
from django.contrib import messages
from django.shortcuts import render, redirect
from .models import Questions

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


system_prompt = """You are an interview-question generator for a career-readiness platform.
 
Given a topic, technology, role, or pasted job description, generate interview
practice questions tailored specifically to that input — never generic filler.
 
Respond with ONLY valid JSON, no prose, no markdown fences, in exactly this shape:
{
  "questions": [
    {
      "type": "mcq" | "behavioral" | "technical",
      "difficulty": "easy" | "medium" | "hard",
      "level": "easy" | "intermediate" | "advanced" | "expert",
      "question_text": "the question itself",
      "options": ["four options"],                     // ONLY present when type is "mcq"
      "correct_answer": "the correct option, verbatim"  // ONLY present when type is "mcq", must exactly match one entry in options
    }
  ]
}
 
Behavioral questions should be answerable with the STAR method. Technical
questions should be specific to the tools/technologies implied by the input."""

allowed_types = {"mcq", "behavioral", "technical"}
allowed_difficulties = {"easy", "medium", "hard"}
allowed_levels = {"easy", "intermediate", "advanced", "expert"}
max_questions = 30

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
        if q.get("difficulty") not in allowed_difficulties:
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
            "type": "mcq", "difficulty": "medium", "level": "intermediate",
            "question_text": "What is the time complexity of binary search on a sorted array?",
            "options": ["O(n)", "O(log n)", "O(n log n)", "O(1)"], "correct_answer": "O(log n)"
        },
        {
            "type": "mcq", "difficulty": "medium", "level": "intermediate",
            "question_text": "In REST APIs, which HTTP method is idempotent?",
            "options": ["POST", "PATCH", "PUT", "CONNECT"], "correct_answer": "PUT"
        },
        {
            "type": "mcq", "difficulty": "easy", "level": "easy",
            "question_text": "Which of these is NOT a valid HTTP status code range?",
            "options": ["2xx Success", "3xx Redirection", "6xx Client Error", "5xx Server Error"],
            "correct_answer": "6xx Client Error"
        },
        {
            "type": "behavioral", "difficulty": "medium", "level": "intermediate",
            "question_text": "Tell me about a time you had to push back on a decision made by a teammate or manager."
        },
        {
            "type": "behavioral", "difficulty": "medium", "level": "intermediate",
            "question_text": "Describe a project where the requirements changed midway through. How did you handle it?"
        },
        {   
            "type": "technical", "difficulty": "hard", "level": "advanced",
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
    question_type = request.POST.getlist("questions_types")
    level = request.POST.get("level", "intermediate")
    difficulty = request.POST.get("difficulty", "medium")

    try:
        questions_count = int(questions_count)
        if questions_count < 1:
            questions_count = 10
    except (ValueError, TypeError):
        questions_count = 10

    question_type = [q_type for q_type in question_type if q_type in allowed_types]
 
    if not question_type:
        messages.error(request, "Please select at least one question type.")
        return redirect("interview_prep")
 
    if len(topic_text) < 2:
        messages.error(request, "Please describe what this session is for first.")
        return redirect("interview_prep")

    if level not in allowed_levels:
        level = "intermediate"
    if difficulty not in allowed_difficulties:
        difficulty = "medium"

    generated = None

    if OpenAI is not None:
        try:
            client = OpenAI()
            user_prompt = (
                f"Topic / job description:\n{topic_text}\n\n"
                f"Generate exactly {questions_count} questions.\n"
                f"Only use these question types: {', '.join(question_type)}.\n"
                f"Target difficulty: {difficulty}. Target level: {level}."
            )
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.5,
                max_tokens=2200,
            )

            raw = response.choices[0].message.content
            data = json.loads(raw)
            if validate_questions(data):
                generated = data["questions"][:questions_count]
        except Exception:
            generated = None

    if generated is None:
        generated = fallback_questions(questions_count, question_type)

    created_ids = []
    for q in generated:
        question = Questions.objects.create(
            user_id = user_id,
            resume=None,
            question_text=q["question_text"],
            question_type=q["type"],
            difficulty=q["difficulty"],
            options=q.get("options"),
            correct_answer=q.get("correct_answer"),
            level=q["level"],
        )
        created_ids.append(question.question_id)

    request.session["last_generated_question_ids"] = created_ids
 
    return redirect("question_results")

def question_results_view(request):
    if not request.session.get("user_id"):
        messages.error(request, "Please sign in to continue.")
        return redirect("login")
 
    question_ids = request.session.get("last_generated_question_ids", [])
    questions = list(Questions.objects.filter(question_id__in=question_ids))
    questions.sort(key=lambda q: question_ids.index(q.question_id))  # preserve generation order
 
    if not questions:
        messages.error(request, "No generated questions found — try generating a new session.")
        return redirect("interview_prep")
 
    return render(
        request, "dashboard_view/user/question_results.html", {"questions": questions}
    )
 