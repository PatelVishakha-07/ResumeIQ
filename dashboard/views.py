from django.shortcuts import redirect, render,get_object_or_404
from accounts.models import User
from django.shortcuts import redirect, render
from accounts.models import User 
from resume.models import Resume, ResumeAnalysis, ResumeVersion


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
    return render(request,"dashboard_view/admin/overview.html",
                  {
                      'nav':{
                          'role':'admin'
                      }
                  })
def manageUsers(request):
    users = User.objects.filter(role = 'user').order_by('-created_at')
    return render(request,"dashboard_view/admin/manageUser.html",
        {
            'users':users,
            'nav': {
                'role': 'admin'
            }
        })

def toggleUserStatus(request, user_id):
    user = get_object_or_404(User, user_id=user_id)

    user.status = not user.status
    user.save()

    return redirect('manageUser')


def manageStaffRole(request):
    return render(request,"dashboard_view/admin/staff_roles.html",
        {
            'nav': {
                'role': 'admin'
            }
        })
def feedback(request):
    return render(request,"dashboard_view/admin/feedback.html",
        {
            'nav': {
                'role': 'admin'
            }
        })


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

#Admin Views