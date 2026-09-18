from django.shortcuts import render, redirect
from django.contrib import messages
from accounts.models import User,Profile
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
