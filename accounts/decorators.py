# accounts/decorators.py
from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect
from accounts.models import User

def admin_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        uid = request.session.get("user_id")
        user = User.objects.filter(pk=uid, status=True).first() if uid else None
        if not user:
            messages.error(request, "Please sign in to continue.")
            return redirect("login")
        if user.role != "admin":
            return redirect("dashboard")
        request.app_user = user
        return view(request, *args, **kwargs)
    return wrapper