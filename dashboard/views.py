from django.shortcuts import redirect, render,get_object_or_404
from accounts.models import User
from django.shortcuts import redirect, render
from accounts.models import User 
from resume.models import Resume, ResumeAnalysis, ResumeVersion
import os
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.contrib.auth.hashers import check_password, make_password
from django.contrib import messages


def dashboard_redirect(request):
    """
    Sends the user to the right section based on the role stored in
    their session at login.
    """
    user_id = request.session.get("user_id")

    if not user_id:
        return redirect("login")

    user = User.objects.get(user_id = user_id)

    role = request.session.get("role")
    nav = {
        'role': role,
        'avatar_initial': user.name[0].upper() if user.name else "",
        'avatar_name': user.name
    }

    if role == "admin":        
        return render(request, "dashboard_view/admin/overview.html", {'nav':nav})
        
    return render(request, "dashboard_view/user/overview.html", {'nav':nav})




# Admin URL
def adminOverview(request):
    admin_id = request.session.get("user_id")
    admin_user = User.objects.get(user_id=admin_id)
    return render(request,"dashboard_view/admin/overview.html",
                  {
                      'nav':{
                          'role':'admin',
                          "avatar_initial": admin_user.name[0].upper(),
                          "avatar_name": admin_user.name,
                      }
                  })
def manageUsers(request):
    admin_id = request.session.get("user_id")
    admin_user = User.objects.get(user_id=admin_id)
    users = User.objects.filter(role = 'user').order_by('-created_at')
    return render(request,"dashboard_view/admin/manageUser.html",
        {
            'users':users,
            'nav': {
                'role': 'admin',
                "avatar_initial": admin_user.name[0].upper(),
                "avatar_name": admin_user.name,
            }
        })

def toggleUserStatus(request, user_id):
    user = get_object_or_404(User, user_id=user_id)

    user.status = not user.status
    user.save()

    return redirect('manageUser')

def userDetail(request, user_id):
    admin_id = request.session.get("user_id")
    admin_user = User.objects.get(user_id=admin_id)

    detail_user = get_object_or_404(User, user_id=user_id)
    
    resumes = Resume.objects.filter(user=detail_user).order_by('-updated_at')

    resume_summaries = []
    for resume in resumes:
        latest_version = resume.resumeversion_set.order_by('-version_number').first()

        latest_analysis = None
        if latest_version:
            latest_analysis = latest_version.resumeanalysis_set.order_by('-analyzed_at').first()

        resume_summaries.append({
            "resume": resume,
            "filename":os.path.basename(resume.file_path),
            "latest_version": latest_version,
            "latest_analysis": latest_analysis,
        })

    # Static value
    weak_areas = [
        {"topic": "System Design", "performance_score": 45.00, "last_updated": "2025-01-22"},
        {"topic": "Data Structures", "performance_score": 58.00, "last_updated": "2025-01-20"},
        {"topic": "SQL Queries", "performance_score": 62.00, "last_updated": "2025-01-18"},
    ]

    context = {
        "nav":{
            "role":"admin",
            "avatar_initial": admin_user.name[0].upper(),
            "avatar_name": admin_user.name,
        },
        "detail_user": detail_user,
        "resume_summaries": resume_summaries,
        "weak_areas": weak_areas,
    }
    return render(request, "dashboard_view/admin/user_detail.html", context)

def manageStaffRole(request):
    admin_id = request.session.get("user_id")
    admin_user = User.objects.get(user_id=admin_id)
    return render(request,"dashboard_view/admin/staff_roles.html",
        {
            'nav': {
                'role': 'admin',
                "avatar_initial": admin_user.name[0].upper(),
                "avatar_name": admin_user.name,
                
            }
        })
def feedback(request):
    admin_id = request.session.get("user_id")
    admin_user = User.objects.get(user_id=admin_id)
    return render(request,"dashboard_view/admin/feedback.html",
        {
            'nav': {
                'role': 'admin',
                "avatar_initial": admin_user.name[0].upper(),
                "avatar_name": admin_user.name,
            }
        })

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

    if request.method == "POST":
        name = request.POST.get("name", "").strip()

        if not name:
            messages.error(request, "Name cannot be empty.")
            return redirect("admin_update_profile")

        admin_user.name = name
        admin_user.save()

        request.session["name"] = admin_user.name
        messages.success(request, "Profile updated successfully.")
        return redirect("admin_settings")

    context = {
        "nav": {
            "role": "admin",
            "avatar_initial": admin_user.name[0].upper(),
            "avatar_name": admin_user.name,
        },
        "admin_user": admin_user,
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



#User Views

def ats_score_generator_view(request):
    return render(request, "dashboard_view/user/ats_score_generator.html")

def score_band(score):
    if score is None:
        return "good"
    if score >= 75:
        return "good"
    if score >= 50:
        return "warn"
    return "bad"

def resume_history_view(request):

    user_id = request.session.get("user_id")
    if not user_id:
        return redirect("login")
    
    try:
        user = User.objects.get(user_id=user_id)        
    except User.DoesNotExist:
        return redirect("login")

    resume_id = Resume.objects.filter(user_id = user_id)

    versions_list = (ResumeVersion.objects.filter(versions__in = resume_id).order_by("created_at"))

    resume_list = []
    previous_score = None
    best_score = None
    best_score_version = None

    for v in versions_list:
        analysis = (ResumeAnalysis.objects.filter(analyses = v).order_by("-analyzed_at").first())
        score = analysis.ats_score if analysis else None

        is_first = previous_score is None
        delta = None if is_first or score is None else score - previous_score

        resume_list.append({
            "version_number": v.version_number,
            "file_name": v.versions.file_path.split("/")[-1],
            "file_type": v.versions.file_type,
            "uploaded_at": v.created_at,
            "ats_score": score if score is not None else "—",
            "score_band": score_band(score),
            "delta": delta,
            "is_first": is_first,
            "version_id": v.version_id
        })

        if score is not None:
            previous_score = score
            if best_score is None or score > best_score:
                best_score = score
                best_score_version = v.version_number

    resume_list.reverse()
    latest = resume_list[0] if resume_list else None

    context = {
        "resumes": resume_list,
        "latest_score": latest["ats_score"] if latest else None,
        "latest_score_band": latest["score_band"] if latest else "good",
        "latest_delta": latest["delta"] if latest else None,
        "best_score": best_score,
        "best_score_version": best_score_version,
        "first_upload_date": (
            versions_list.first().created_at.strftime("%b %d, %Y")
            if versions_list.exists() else None
        ),
    }

    return render(request, "dashboard_view/user/resume_history.html", context)

