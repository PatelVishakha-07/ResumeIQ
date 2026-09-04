from django.shortcuts import render, redirect
from django.contrib import messages
from accounts.models import User
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.hashers import make_password, check_password

#register view
def register_view(request):
    if request.method == "POST":
        name = request.POST.get("name")
        email = request.POST.get("email")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        if password != confirm_password:
            messages.error(request, "Password and Confirm Password do not match.")
            return redirect("register")

        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Please enter a valid email address.")
            return redirect("register")

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email-Id already exists.")
            return redirect("register")

        user = User(
            name = name,
            email = email,
            password = make_password(password),
            role = "user",
        )
        user.save()

        messages.success(request, "Registration successfull!")
        return redirect("login")
    
    return render(request, "authentication/register.html")

#login view
def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        #validate email
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Enter valid email address.")
            return redirect("login")

        #check if email exists or not
        try:
            user = User.objects.get(email = email)
        except User.DoesNotExist:
            messages.error(request, "Email id does not exists.")
            return redirect("login")

        #check if user has login through google
        if not user.password:
            messages.error(request, "This account has no password set. Please use social login.")
            return redirect("login")

        #check if email and password match
        if not check_password(password, user.password):
            messages.error(request, "Invalid password.")
            return redirect("login")

        #check if user is active
        if not user.status:
            messages.error(request, "Your account is inactive. Please contact support.")
            return redirect("login")

        request.session["user_id"] = user.user_id
        request.session["name"] = user.name
        request.session["role"] = user.role

        messages.success(request, "Login Successfull")
        return redirect("dashboard")


    return render(request, "authentication/login.html")