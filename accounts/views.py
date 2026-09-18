from django.shortcuts import render, redirect
from django.contrib import messages
from accounts.models import User
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.hashers import make_password, check_password
from django.http import JsonResponse
from django.conf import settings
import requests, json, os
from django.urls import reverse
from django.core.mail import send_mail


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
            role="user"
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


#logout view
def logout_view(request):
    request.session.flush()
    messages.success(request, "You have logged out.")
    return redirect("home")


#google login/signup — one endpoint handles both, since "sign in with Google"
#and "sign up with Google" are the same action: verify the token, then
#create the account if it doesn't exist yet.
def login_with_google_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    try:
        body = json.loads(request.body or "{}")
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid request."}, status=400)

    access_token = body.get("access_token")

    if not access_token:
        return JsonResponse({"error": "Missing Google access token."}, status=400)

    # Never trust the browser's claim about who signed in — ask Google
    # directly, using the token the browser just obtained.
    try:
        google_response = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=5,
        )
    except requests.RequestException:
        return JsonResponse({"error": "Could not reach Google. Try again."}, status=502)

    if google_response.status_code != 200:
        return JsonResponse({"error": "Could not verify Google account."}, status=401)

    profile = google_response.json()
    email = profile.get("email")
    email_verified = profile.get("email_verified") in (True, "true")
    name = profile.get("name") or email

    if not email or not email_verified:
        return JsonResponse({"error": "That Google account has no verified email."}, status=401)

    user, created = User.objects.get_or_create(
        email = email,
        defaults={"name": name, "password": None, "role": "user"},
    )

    if not user.status:
        return JsonResponse({"error": "Your account is inactive. Please contact support."}, status=403)

    request.session["user_id"] = user.user_id
    request.session["name"] = user.name
    request.session["role"] = user.role

    messages.success(request, "Login Successfull")
    return JsonResponse({"redirect": reverse("dashboard")})

def send_otp_for_verification(email, otp, subject = "Your ResumeIQ - Email Verification Code"):
    send_mail(
        subject = subject,
        message = (
            f"Hello, \n\n"
            f"Your Verification code is: {otp}\n\n"
            f"This code expires in 10 minutes. Do not share it with anyone.\n\n"
            f"– ResumeIQ"
        ),
        from_email = os.getenv("EMAIL_HOST_USER"),
        recipient_list = [email],
        fail_silently = False
    )