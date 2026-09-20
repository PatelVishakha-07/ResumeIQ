from django.shortcuts import render, redirect
from django.contrib import messages
from accounts.models import User,Profile
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.hashers import make_password, check_password
from django.http import JsonResponse
import json, os, logging, math, secrets, time, hashlib
from django.urls import reverse
from django.core.mail import send_mail
from django.db import IntegrityError
from django.utils.crypto import constant_time_compare, salted_hmac
from django.core.cache import cache
from django.views.decorators.csrf import ensure_csrf_cookie

logger = logging.getLogger(__name__)

#Email Verification 
otp_expiration_time = 10 * 60 #otp code expiration time: 10 minutes
otp_resend_time = 30 #to resend otp code
otp_max_attempt = 5 #wrong input per code
pending_signup_key = "pending_signup"


#register view
def register_view(request):
    if request.method == "POST":
        return redirect("register")
    return render(request, "authentication/register.html")        

def send_otp_for_verification(email, otp, subject = "Your ResumeIQ - Email Verification Code"):
    send_mail(
        subject=subject,
        message=(
            f"Hello, \n\n"
            f"Your Verification code is: {otp}\n\n"
            f"This code expires in 10 minutes. Do not share it with anyone.\n\n"
            f"– ResumeIQ"
        ),
        from_email = os.getenv("EMAIL_HOST_USER"),
        recipient_list = [email],
        fail_silently = False
    )

def _json_body(request):
    try:
        body = json.loads(request.body or {})
    except (ValueError, TypeError):
        return None
    return body if isinstance(body, dict) else None

def _hash_otp(otp):
    return salted_hmac("accounts.register_otp", otp).hexdigest()

# Generate a fresh code, email it, and keep only its hash in the session.
# If sending fails this raises, so nothing is stored.
def _issue_otp(request, pending):
    otp = f"{secrets.randbelow(10**6):06d}"
    send_otp_for_verification(pending["email"], otp)

    now = time.time()
    pending.update(
        otp_hash = _hash_otp(otp),
        sent_at = now,
        expires_at = now + otp_expiration_time,
        attempts = 0        
    )

    request.session[pending_signup_key] = pending

def register_send_otp(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid request."}, status=400)

    name = str(body.get("name") or "").strip()
    email = str(body.get("email") or "").strip()
    password = str(body.get("password") or "").strip()
    confirm_password = str(body.get("confirm_password") or "").strip()

    if not name:
        return JsonResponse({"error": "Please enter your full name."}, status=400)

    if len(name) > 100:
        return JsonResponse({"error": "Name must be 100 characters or fewer."}, status=400)

    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"error": "Please enter a valid email address."}, status=400)

    if len(email) > 100:
        return JsonResponse({"error": "Email must be 100 characters or fewer."}, status=400)

    if len(password) < 8:
        return JsonResponse({"error": "Password must be at least 8 characters."}, status=400)

    if password != confirm_password:
        return JsonResponse({"error": "Password and Confirm Password do not match."}, status=400)

    if User.objects.filter(email__iexact = email).exists():
        return JsonResponse({"error": "Email-Id already exists."}, status=409)

    now = time.time()
    pending = request.session.get(pending_signup_key)

    if pending and now - pending["sent_at"] < otp_resend_time:
        wait = math.ceil(otp_resend_time - (now - pending["sent_at"]))

        if pending["email"] != email:
            return JsonResponse({"error": f"Please wait {wait}s before requesting another code.", "retry_after": wait}, status = 429)

        # Same email (user closed the box and pressed Create account again):
        # keep the code that was already sent, just refresh the submitted details.
        pending["name"] = name
        pending["password"] = make_password(password)
        request.session[pending_signup_key] = pending

        return JsonResponse({"ok": True, "email": email, "resend_in": wait})

    pending = {"name": name, "email": email, "password": make_password(password)}

    try:
        _issue_otp(request, pending)
    except Exception:
        logger.exception("Could not send registration code to %s", email)
        return JsonResponse({"error": "We couldn't send the verification email. Please try again."}, status=502)

    return JsonResponse({"ok": True, "email": email, "resend_in": otp_resend_time})

def register_verify_otp(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid request."}, status=400)

    code = str(body.get("code") or "").strip()

    pending = request.session.get(pending_signup_key)
    if not pending:
        return JsonResponse({"error": "Your verification session expired. Please fill in the form again.", "expired": True}, status=400)

    if time.time() > pending["expires_at"]:
        return JsonResponse({"error": "This code has expired. Select Resend code to get a new one."}, status=400,)

    if pending["attempts"] >= otp_max_attempt:
        return JsonResponse(
            {"error": "Too many incorrect attempts. Select Resend code to get a new one."}, status=429)

    if not (code.isascii() and code.isdigit() and len(code) == 6):
        return JsonResponse({"error": "Enter the 6-digit code."}, status=400)

    if not constant_time_compare(_hash_otp(code), pending["otp_hash"]):
        pending["attempts"] += 1
        request.session[pending_signup_key] = pending

        left = otp_max_attempt - pending["attempts"]
        if left <= 0:
            msg = "Too many incorrect attempts. Select Resend code to get a new one."
        else:
            msg = f"Incorrect code. {left} attempt{'s' if left != 1 else ''} left."
        return JsonResponse({"error": msg}, status=400)
    created = False
    if not User.objects.filter(email__iexact = pending["email"]).exists():
        try:
            User.objects.create(
                name = pending["name"],
                email = pending["email"],
                password = pending["password"],
                role = "user"
            )
            created = True
        except IntegrityError:
            pass

    request.session.pop(pending_signup_key, None)

    if not created:
        return JsonResponse({"error": "Email-Id already exists."}, status=409)

    messages.success(request, "Email verified and account created. Please sign in.")
    return JsonResponse({"redirect": reverse("login")})

def register_resend_otp(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    pending = request.session.get(pending_signup_key)
    if not pending:
        return JsonResponse({"error": "Your verification session expired. Please fill in the form again.", "expired": True}, status=400)

    elapsed = time.time() - pending["sent_at"]
    if elapsed < otp_resend_time:
        wait = math.ceil(otp_resend_time - elapsed)
        return JsonResponse({"error": f"Please wait {wait}s before requesting another code.", "retry_after": wait},status=429, )
    
    try:
        _issue_otp(request, pending)
    except Exception:
        logger.exception("Could not resend registration code to %s", pending.get("email"))
        return JsonResponse({"error": "We couldn't send the verification email. Please try again."}, status=502,)

    return JsonResponse({"ok": True, "resend_in": otp_resend_time})

#Forgot password (email OTP -> verify -> set new password)
reset_session_key = "pending_password_reset"
reset_email_hourly_limit = 5
reset_ip_hourly_limit = 20
reset_limit_window = 60*60
max_password_length = 128

def hash_reset_otp(otp):
    return salted_hmac("accounts.reset_otp", otp).hexdigest()

def send_password_reset_otp(email, otp):
    send_mail(
        subject="Your ResumeIQ - Password Reset Code",
        message=(
            f"Hello, \n\n"
            f"We received a request to reset your ResumeIQ password.\n\n"
            f"Your verification code is: {otp}\n\n"
            f"This code expires in 10 minutes. Do not share it with anyone.\n"
            f"If you didn't request this, you can ignore this email - your password will not change.\n\n"
            f"– ResumeIQ"
        ),
        from_email = os.getenv("EMAIL_HOST_USER"),
        recipient_list = [email],
        fail_silently = False
    )    

def send_password_changed_notice(email):
    send_mail(
        subject="Your ResumeIQ password was changed",
        message = (
            f"Hello, \n\n"
            f"The password for your ResumeIQ account was just changed.\n"
            f"If this was you, no action is needed. If it wasn't, please contact support immediately.\n\n"
            f"– ResumeIQ"
        ),
        from_email = os.getenv("EMAIL_HOST_USER"),
        recipient_list = [email],
        fail_silently = False
    )

#counts a request in the cache; returns True once `limit` is exceeded inside `window` seconds
def rate_limited(key, limit, window):
    if cache.add(key, 1, window):
        return False
    try:
        return cache.incr(key) > limit
    except ValueError:
        cache.set(key, 1, window)
        return False

def reset_rate_limited(request, email):
    ip = request.META.get("REMOTE_ADDR", "unknown")    
    email_key =hashlib.sha256(email.lower().encode("utf-8")).hexdigest()
    return (
        rate_limited(f"pwreset:email:{email_key}", reset_email_hourly_limit, reset_limit_window) or 
        rate_limited(f"pwreset:ip:{ip}", reset_ip_hourly_limit, reset_limit_window)
    )

# Generate a fresh code and keep only its hash in the session. The email is only sent for a real,
# active account (pending["eligible"]); for anything else the flow looks the same but no email goes out.
def issue_reset_otp(request, pending):
    otp = f"{secrets.randbelow(10**6):06d}"

    if pending["eligible"]:
        try:
            send_password_reset_otp(pending["email"], otp)
        except Exception:
            logger.exception("Could not send password reset code to %s", pending["email"])

    now = time.time()
    pending.update(
        otp_hash = hash_reset_otp(otp),
        sent_at = now,
        expires_at = now + otp_expiration_time,
        attempts = 0,
        verified = False,
        verified_until = 0
    )

    request.session[reset_session_key] = pending

def reset_expired_response():
    return JsonResponse({"error": "Your reset session expired. Please start again.", "expired": True}, status=400)

@ensure_csrf_cookie
def forgot_password_view(request):
    return render(request, "authentication/forgot_password.html")

def forgot_password_send_otp(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
 
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid request."}, status=400)

    email = str(body.get("email") or "").strip()

    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"error": "Please enter a valid email address."}, status=400)

    if len(email) > 100:
        return JsonResponse({"error": "Email must be 100 characters or fewer."}, status=400)

    now = time.time()
    pending = request.session.get(reset_session_key)

    if pending and now - pending["sent_at"] < otp_resend_time:
        wait = math.ceil(otp_resend_time - (now - pending["sent_at"]))

        if pending["email"].lower() != email.lower():
            return JsonResponse({"error": f"Please wait {wait}s before requesting another code.", "retry_after": wait}, status=429)

        #same email again (page refreshed / box closed): keep the code that was already sent
        return JsonResponse({"ok": True, "email": email, "resend_in": wait})

    if reset_rate_limited(request,email):
        return JsonResponse({"error": "Too many reset requests. Please try again in an hour."}, status=429)

    user = User.objects.filter(email__iexact = email).first()
    pending = {"email":email, "eligible": bool(user and user.status)}

    issue_reset_otp(request, pending)

    return JsonResponse({"ok": True, "email": email, "resend_in": otp_resend_time})

def forgot_password_verify_otp(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
 
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid request."}, status=400)

    code = str(body.get("code", "")).strip()
    pending = request.session.get(reset_session_key)

    if not pending:
        return reset_expired_response()

    if time.time() > pending["expires_at"]:
        return JsonResponse({"error": "This code has expired. Select Resend code to get a new one."}, status=400)

    if pending["attempts"] >= otp_max_attempt:
        return JsonResponse({"error": "Too many incorrect attempts. Select Resend code to get a new one."}, status=429)

    if not (code.isascii() and code.isdigit() and len(code) == 6):
        return JsonResponse({"error": "Enter the 6-digit code."}, status=400)

    #a non-eligible email can never pass, even if the random code were guessed
    if not (constant_time_compare(hash_reset_otp(code), pending["otp_hash"]) and pending["eligible"]):
        pending["attempts"] += 1
        request.session[reset_session_key] = pending

        left = otp_max_attempt - pending["attempts"]
        if left <= 0:
            msg = "Too many incorrect attempts. Select Resend code to get a new one."
        else:
            msg = f"Incorrect code. {left} attempt{'s' if left != 1 else ''} left."
        return JsonResponse({"error": msg}, status=400)

    pending["verified"] = True
    pending["verified_until"] = time.time() + otp_expiration_time
    request.session[reset_session_key] = pending
    return JsonResponse({"ok": True})

def forgot_password_resend_otp(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
 
    pending = request.session.get(reset_session_key)
    if not pending:
        return reset_expired_response()
 
    elapsed = time.time() - pending["sent_at"]
    if elapsed < otp_resend_time:
        wait = math.ceil(otp_resend_time - elapsed)
        return JsonResponse({"error": f"Please wait {wait}s before requesting another code.", "retry_after": wait}, status=429)
 
    if reset_rate_limited(request, pending["email"]):
        return JsonResponse({"error": "Too many reset requests. Please try again in an hour."}, status=429)
 
    issue_reset_otp(request, pending)
    return JsonResponse({"ok": True, "resend_in": otp_resend_time})

def forgot_password_reset(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
 
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid request."}, status=400)
 
    pending = request.session.get(reset_session_key)
    if not pending:
        return reset_expired_response()

    if not pending["verified"]:
        return JsonResponse({"error": "Please verify your email code first."}, status=400)

    if time.time() > pending.get("verified_until", 0):
        request.session.pop(reset_session_key, None)
        return reset_expired_response()

    password = str(body.get("password") or "")
    confirm_password = str(body.get("confirm_password") or "")

    if len(password) < 8:
        return JsonResponse({"error": "Password must be at least 8 characters."}, status=400)    

    if len(password) > max_password_length:
        return JsonResponse({"error": f"Password must be {max_password_length} characters or fewer."}, status=400)

    if password != confirm_password:
        return JsonResponse({"error": "Password and Confirm Password do not match."}, status=400)

    user = User.objects.filter(email__iexact = pending["email"]).first()
    if not user or not user.status:
        request.session.pop(reset_session_key, None)
        return reset_expired_response()

    if user.password and check_password(password, user.password):
        return JsonResponse({"error": "Choose a password different from your current one."}, status=400)

    user.password = make_password(password)
    user.save()

    request.session.pop(reset_session_key, None)
    try:
        send_password_changed_notice(user.email)
    except Exception:
        logger.exception("Could not send password-changed notice to %s", user.email)
    messages.success(request, "Password reset successfully. Please sign in.")
    return JsonResponse({"redirect": reverse("login")})

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


# ---------------
# admin Setting
# ---------------

def adminSettings(request):
    admin_id = request.session.get("user_id")
    if not admin_id:
        messages.error(request, "Please sign in to continue.")
        return redirect("login")

    admin_user = User.objects.get(user_id=admin_id)

    context = {
        "nav": {
            "role": "admin",
            "avatar_initial": admin_user.name[0].upper(),
            "avatar_name": admin_user.name,
        },
        "admin_user": admin_user,
    }
    return render(request, "dashboard_view/admin/admin_settings.html", context)

def adminUpdateProfile(request):
    admin_id = request.session.get("user_id")
    if not admin_id:
        messages.error(request, "Please sign in to continue.")
        return redirect("login")

    admin_user = User.objects.get(user_id=admin_id)
    profile, _ = Profile.objects.get_or_create(user=admin_user)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        bio = request.POST.get("bio", "").strip()

        if not name:
            messages.error(request, "Name cannot be empty.")
            return redirect("admin_update_profile")

        # Update name
        admin_user.name = name
        admin_user.save()

        # Update bio
        profile.bio = bio

        # Remove current photo
        if request.POST.get("remove_image") == "1" and profile.profile_image:
            profile.profile_image.delete(save=False)
            profile.profile_image = None

        # Handle new upload
        uploaded_image = request.FILES.get("profile_image")
        if uploaded_image:
            allowed_types = ["image/jpeg", "image/png", "image/webp"]

            if uploaded_image.content_type not in allowed_types:
                messages.error(request, "Only JPG, PNG, or WEBP images are allowed.")
                return redirect("admin_update_profile")

            if uploaded_image.size > 2 * 1024 * 1024:
                messages.error(request, "Image must be 2MB or smaller.")
                return redirect("admin_update_profile")

            # Delete old image
            if profile.profile_image:
                profile.profile_image.delete(save=False)

            # Save new image
            profile.profile_image = uploaded_image

        profile.save()

        request.session["name"] = admin_user.name
        messages.success(request, "Profile updated successfully.")
        return redirect("admin_settings")

    context = {
        "nav": {
            "role": "admin",
            "avatar_initial": admin_user.name[0].upper(),
            "avatar_name": admin_user.name,
            "avatar_image": profile.get_image_url() if profile.profile_image else None,
        },
        "admin_user": admin_user,
        "profile": profile,
    }
    return render(request, "dashboard_view/admin/admin_update_profile.html", context)


def adminChangePassword(request):
    admin_id = request.session.get("user_id")
    if not admin_id:
        messages.error(request, "Please sign in to continue.")
        return redirect("login")

    admin_user = User.objects.get(user_id=admin_id)

    if request.method == "POST":
        current_password = request.POST.get("current_password", "")
        new_password = request.POST.get("new_password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if not admin_user.password:
            messages.error(request, "This account has no password set. Please use social login.")
            return redirect("admin_change_password")

        #check current password matches
        if not check_password(current_password, admin_user.password):
            messages.error(request, "Current password is incorrect.")
            return redirect("admin_change_password")

        if len(new_password) < 8:
            messages.error(request, "New password must be at least 8 characters.")
            return redirect("admin_change_password")

        if new_password != confirm_password:
            messages.error(request, "New password and confirmation do not match.")
            return redirect("admin_change_password")

        admin_user.password = make_password(new_password)
        admin_user.save()

        messages.success(request, "Password changed successfully.")
        return redirect("admin_settings")

    context = {
        "nav": {
            "role": "admin",
            "avatar_initial": admin_user.name[0].upper(),
            "avatar_name": admin_user.name,
        },
    }
    return render(request, "dashboard_view/admin/admin_change_password.html", context)

