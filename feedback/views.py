from datetime import timedelta

from django.contrib import messages
from django.shortcuts import render, redirect
from django.utils import timezone

from .models import Feedback

FEEDBACK_MIN_LENGTH = 10
FEEDBACK_MAX_LENGTH = 1000
FEEDBACK_DAILY_LIMIT = 5


def user_feedback_view(request):
    user_id = request.session.get("user_id")

    if not user_id:
        messages.error(request, "Please sign in to continue.")
        return redirect("login")

    categories = Feedback.Category_Choices
    valid_categories = {value for value, _ in categories}
    form = {"rating": "", "category": "general", "message": ""}
    error = None

    if request.method == "POST":
        form["rating"] = (request.POST.get("rating") or "").strip()
        form["category"] = (request.POST.get("category") or "general").strip()
        form["message"] = (request.POST.get("message") or "").strip()

        try:
            rating = int(form["rating"])
        except (ValueError, TypeError):
            rating = 0

        sent_today = Feedback.objects.filter(
            user_id=user_id,
            created_at__gte=timezone.now() - timedelta(days=1),
        ).count()

        if not 1 <= rating <= 5:
            error = "Choose a star rating from 1 to 5."
        elif form["category"] not in valid_categories:
            error = "Choose what your feedback is about."
        elif len(form["message"]) < FEEDBACK_MIN_LENGTH:
            error = f"Write at least {FEEDBACK_MIN_LENGTH} characters so we can act on it."
        elif len(form["message"]) > FEEDBACK_MAX_LENGTH:
            error = f"Keep your feedback under {FEEDBACK_MAX_LENGTH} characters."
        elif sent_today >= FEEDBACK_DAILY_LIMIT:
            error = "You've reached today's limit of 5 submissions. Try again tomorrow."
        else:
            Feedback.objects.create(
                user_id=user_id,
                rating=rating,
                category=form["category"],
                message=form["message"],
            )
            messages.success(request, "Thanks. Your feedback was sent to the team.")
            return redirect("user_feedback")

    return render(
        request,
        "dashboard_view/user/feedback.html",
        {
            "categories": categories,
            "form": form,
            "error": error,
            "past_feedback": Feedback.objects.filter(user_id=user_id)[:5],
            "max_length": FEEDBACK_MAX_LENGTH,
        },
    )