from django.shortcuts import redirect, render,get_object_or_404
from accounts.models import User,Profile
import os
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.contrib.auth.hashers import check_password, make_password
from django.contrib import messages
from resume.models import Resume,ResumeAnalysis
from django.utils.timesince import timesince
from django.utils import timezone
from resume.models import Resume, ResumeAnalysis, ResumeVersion, JDMatchResult
from django.template.loader import render_to_string
from django.http import HttpResponse, JsonResponse
from io import BytesIO
from xhtml2pdf import pisa
from resume.ats_scoring import compute_ats_score
from django.conf import settings
from django.views.decorators.http import require_http_methods
import json
from django.contrib.auth.decorators import login_required

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
        return adminOverview(request)   
        user = User.objects.get(user_id = user_id)    
        nav = {
            'role' : role,
            'avatar_initial' : user.name[0].upper() if user.name else " ",
            'avatar_name' : user.name

        }
        return render(request, "dashboard_view/admin/overview.html", {'nav':nav})
        
    return render(request, "dashboard_view/user/overview.html", {'nav':nav})




# Admin URL
def adminOverview(request):
    admin_id = request.session.get("user_id")
    if not admin_id:
        messages.error(request, "Please sign in to continue.")
        return redirect("login")

    admin_user = User.objects.get(user_id=admin_id)

 
    active_users_count = User.objects.filter(role="user", status=True).count()


    resumes_analysed_count = Resume.objects.filter(
        resumeversion__resumeanalysis__isnull=False
    ).distinct().count()

    # --- Recent activity -
    activity_items = []

    # Recent resume uploads
    recent_resumes = Resume.objects.select_related('user').order_by('-updated_at')[:5]
    for resume in recent_resumes:
        activity_items.append({
            "icon": "↥",
            "text_bold": resume.user.name,
            "text_rest": "uploaded a new resume",
            "timestamp": resume.updated_at,
        })


    recent_analyses = ResumeAnalysis.objects.select_related('analyses__versions__user').order_by('-analyzed_at')[:5]
    for analysis in recent_analyses:
        activity_items.append({
            "icon": "✓",
            "text_bold": "Resume analysis",
            "text_rest": f"completed for {analysis.analyses.versions.user.name}",
            "timestamp": analysis.analyzed_at,
        })

    # Sort combined feed newest-first, keep top 5
    activity_items.sort(key=lambda item: item["timestamp"], reverse=True)
    activity_items = activity_items[:5]

   
    now = timezone.now()
    for item in activity_items:
        item["time_ago"] = timesince(item["timestamp"], now) + " ago"

    context = {
        "nav": {
            "role": "admin",
            "avatar_initial": admin_user.name[0].upper(),
            "avatar_name": admin_user.name,
        },
        "active_users_count": active_users_count,
        "resumes_analysed_count": resumes_analysed_count,
        "activity_items": activity_items,
    }
    return render(request, "dashboard_view/admin/overview.html", context)


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

    # Static placeholder
    weak_areas = [
        {"topic": "System Design", "performance_score": 45.00, "last_updated": "2025-01-22"},
        {"topic": "Data Structures", "performance_score": 58.00, "last_updated": "2025-01-20"},
        {"topic": "SQL Queries", "performance_score": 62.00, "last_updated": "2025-01-18"},
    ]

    context = {
    "nav": {
        "role": "admin",
        "avatar_initial": admin_user.name[0].upper(),
        "avatar_name": admin_user.name,
    },
    "admin_user": admin_user,
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

def reports(request):
    admin_id = request.session.get("user_id")
    admin_user = User.objects.get(user_id=admin_id)
    return render(request,"dashboard_view/admin/admin_reports.html",
            {
                'nav': {
                    'role': 'admin',
                    "avatar_initial": admin_user.name[0].upper(),
                    "avatar_name": admin_user.name,
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


#functions to view report of the resume of particular user
def resume_report_view(request, version_id):
    user = get_logged_in_user_view(request)

    if not user:
        return redirect("login")

    version = get_object_or_404(ResumeVersion, version_id = version_id, versions__user = user)

    context = build_report_context(version)
    return render(request, "dashboard_view/user/view_resume_report.html", context)

def build_report_context(version):
    analysis = (ResumeAnalysis.objects.filter(analyses = version).order_by("-analyzed_at").first())

    jd_match = (JDMatchResult.objects.filter(version=version, search_type='with_resume').order_by("-match_id").first())

    resume = version.versions
    ats_score = analysis.ats_score if analysis else None
    ring_circuference = 327
    dashoffset = ring_circuference if ats_score is None else round(ring_circuference * (1 - float(ats_score)/100), 1)
    missing_sections = (analysis.missing_section if analysis else []) or []
    missing_keywords = (jd_match.missing_keywords if jd_match else []) or []

    jd_text_used = jd_match.jd.jd_text if jd_match else None
    breakdown = compute_ats_score(version.content_snapshot, jd_text_used, has_tables=False)

    return {
        "version": version,
        "resume": resume,
        "file_name": resume.file_path.split("/")[-1],
        "analysis": analysis,
        "ats_score": ats_score,
        "ats_score_dashoffset": dashoffset,
        "score_band": score_band(ats_score),
        "formatting_score": breakdown["formatting_score"],
        "section_score": breakdown["section_score"],
        "keyword_match": breakdown["keyword_match"],
        "missing_sections": missing_sections,
        "grammar_issues": (analysis.grammar_issues if analysis else []) or [],
        "passive_voice_flags": (analysis.passive_voice_flags if analysis else []) or [],
        "jd_match": jd_match,
        "missing_keywords": missing_keywords,
        "analyzed_at": analysis.analyzed_at if analysis else None,
        "missing_sections_display": ", ".join(s.replace("_", " ").title() for s in missing_sections) or None,
        "missing_keywords_display": ", ".join(missing_keywords) or None,
    }

def download_report_resume_view(request, version_id):
    user = get_logged_in_user_view(request)
    if not user:
        return redirect("login")

    version = get_object_or_404(ResumeVersion, version_id = version_id, versions__user = user)
    context = build_report_context(version)

    html = render_to_string("dashboard_view/user/resume_report_pdf_view.html", context)

    pdf_buffer = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=pdf_buffer)

    if pisa_status.err:
        return HttpResponse("We couldn't generate the PDF for this report.", status = 500)

    respose = HttpResponse(pdf_buffer.getvalue(), content_type = "application/pdf")
    filename = f"ResumeIQ_Report_v{version.version_number}.pdf"
    respose["Content-Disposition"] = f"attachment; filename='{filename}'"
    return respose


#function to view roadmap generator page
def roadmap_generator_view(request):
    return render(request, "dashboard_view/user/roadmap_generator.html")


try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

system_prompt = """You are a learning-roadmap generator for a career-readiness platform.
 
Given a topic, technology, role, or pasted job description, produce a structured
learning roadmap of 4-6 stages that takes someone from beginner to job-ready for
that specific thing. Tailor every stage's title, description, and topics to the
actual input — never return generic placeholders.
 
Respond with ONLY valid JSON in exactly this shape, no prose, no markdown fences:
{
  "query_label": "short human-readable label for what this roadmap is for, 60 chars or fewer",
  "stages": [
    {
      "title": "stage name",
      "duration": "e.g. 1-2 weeks",
      "level": "Beginner | Beginner -> Intermediate | Intermediate | Advanced",
      "desc": "one sentence describing this stage",
      "topics": ["3 to 5 short topic or skill strings"]
    }
  ]
}"""

max_input_length = 6000

#Used when OPENAI_API_KEY is missing/invalid or the API call fails for any reason — the feature should degrade gracefully, never hard-fail.
def fallback_roadmap(query_text):
    label = query_text if len(query_text) <= 60 else query_text[:60] + "..."
    return {
        "query_label": label,
        "stages": [
            {
                "title":"Fundamentals", "duration":"1-2 weeks", "level":"Beginner", 
                "desc": "The baseline concepts everything else builds on.",
                "topics": ["Core syntax", "Tooling setup", "Version control basics"]
             },            
             {
                "title": "Core concepts", "duration": "2–3 weeks", "level": "Beginner \u2192 Intermediate",
                "desc": "The bulk of what you'll actually use day to day.",
                "topics": ["Key building blocks", "Common patterns", "Standard libraries"]
            },
            {
                "title": "Practical application", "duration": "1–2 weeks", "level": "Intermediate",
                "desc": "Where theory turns into something you can point to.",
                "topics": ["State/data handling", "Working with APIs", "Debugging & tooling"]
            },
            {
                "title": "Testing & best practices", "duration": "1 week", "level": "Intermediate",
                "desc": "The habits that separate hobby code from production code.",
                "topics": ["Testing fundamentals", "Code quality tools", "Documentation"]
            },
            {
                "title": "Advanced & project work", "duration": "2+ weeks", "level": "Advanced",
                "desc": "Depth, plus a project worth putting on your resume.",
                "topics": ["Performance & scale", "Real-world project", "Interview-ready talking points"]
            },
        ]
    }

#Guards against a malformed/truncated AI response reaching the frontend.
def validate_roadmap(data):
    if not isinstance(data, dict):
        return False

    if not isinstance(data.get("query_label"), str):
        return False

    stages = data.get("stages")

    if not isinstance(stages, list) or not (1 <= len(stages) <= 10):
        return False

    for stage in stages:
        if not isinstance(stage, dict):
            return False

        for key in ('title', 'duration', 'level', 'desc', 'topics'):
            if key not in stage:
                return False

        if not isinstance(stage["title"],str) or not stage["title"].strip():
            return False

        if not isinstance(stage["topics"], str) or not stage["topics"].strip():
            return False

    return True

@require_http_methods(["POST"])
def generate_roadmap(request):
    query_text = (request.POST.get("query") or "").strip()

    if len(query_text) < 2:
        return JsonResponse({"error": "Please enter a topic, role, or job description first."}, status=400)

    if len(query_text) > max_input_length:
        query_text = query_text[:max_input_length]

    api_key = getattr(settings, "OPENAI_API_KEY", None)

    if OpenAI is not None and api_key:
        try:
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role":"system", "content":system_prompt},
                    {"role":"user", "content":query_text},
                ],
                response_format={"type":"json_object"},
                temperature=0.4,
                max_tokens=1200,                
            )
            raw = response.choices[0].message.content
            data = json.loads(raw)

            if validate_roadmap(data):
                data["source"] = "ai"
                return JsonResponse(data)

        except Exception:
            pass

    fallback = fallback_roadmap(query_text)
    fallback["source"] = "fallback"

    return JsonResponse(fallback)


def resume_report_view(request, version_id):
    user = get_logged_in_user_view(request)

    if not user:
        return redirect("login")

    version = get_object_or_404(ResumeVersion, version_id = version_id, versions__user = user)

    context = build_report_context(version)
    return render(request, "dashboard_view/user/view_resume_report.html", context)

def build_report_context(version):
    analysis = (ResumeAnalysis.objects.filter(analyses = version).order_by("-analyzed_at").first())

    jd_match = (JDMatchResult.objects.filter(version=version, search_type='with_resume').order_by("-match_id").first())

    resume = version.versions
    ats_score = analysis.ats_score if analysis else None
    ring_circuference = 327
    dashoffset = ring_circuference if ats_score is None else round(ring_circuference * (1 - float(ats_score)/100), 1)
    missing_sections = (analysis.missing_section if analysis else []) or []
    missing_keywords = (jd_match.missing_keywords if jd_match else []) or []

    jd_text_used = jd_match.jd.jd_text if jd_match else None
    breakdown = compute_ats_score(version.content_snapshot, jd_text_used, has_tables=False)

    return {
        "version": version,
        "resume": resume,
        "file_name": resume.file_path.split("/")[-1],
        "analysis": analysis,
        "ats_score": ats_score,
        "ats_score_dashoffset": dashoffset,
        "score_band": score_band(ats_score),
        "formatting_score": breakdown["formatting_score"],
        "section_score": breakdown["section_score"],
        "keyword_match": breakdown["keyword_match"],
        "missing_sections": missing_sections,
        "grammar_issues": (analysis.grammar_issues if analysis else []) or [],
        "passive_voice_flags": (analysis.passive_voice_flags if analysis else []) or [],
        "jd_match": jd_match,
        "missing_keywords": missing_keywords,
        "analyzed_at": analysis.analyzed_at if analysis else None,
        "missing_sections_display": ", ".join(s.replace("_", " ").title() for s in missing_sections) or None,
        "missing_keywords_display": ", ".join(missing_keywords) or None,
    }

def download_report_resume_view(request, version_id):
    user = get_logged_in_user_view(request)
    if not user:
        return redirect("login")

    version = get_object_or_404(ResumeVersion, version_id = version_id, versions__user = user)
    context = build_report_context(version)

    html = render_to_string("dashboard_view/user/resume_report_pdf_view.html", context)

    pdf_buffer = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=pdf_buffer)

    if pisa_status.err:
        return HttpResponse("We couldn't generate the PDF for this report.", status = 500)

    respose = HttpResponse(pdf_buffer.getvalue(), content_type = "application/pdf")
    filename = f"ResumeIQ_Report_v{version.version_number}.pdf"
    respose["Content-Disposition"] = f"attachment; filename='{filename}'"
    return respose


#function to view roadmap generator page
def roadmap_generator_view(request):
    return render(request, "dashboard_view/user/roadmap_generator.html")


try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

system_prompt = """You are a learning-roadmap generator for a career-readiness platform.
 
Given a topic, technology, role, or pasted job description, produce a structured
learning roadmap of 4-6 stages that takes someone from beginner to job-ready for
that specific thing. Tailor every stage's title, description, and topics to the
actual input — never return generic placeholders.
 
Respond with ONLY valid JSON in exactly this shape, no prose, no markdown fences:
{
  "query_label": "short human-readable label for what this roadmap is for, 60 chars or fewer",
  "stages": [
    {
      "title": "stage name",
      "duration": "e.g. 1-2 weeks",
      "level": "Beginner | Beginner -> Intermediate | Intermediate | Advanced",
      "desc": "one sentence describing this stage",
      "topics": ["3 to 5 short topic or skill strings"]
    }
  ]
}"""

max_input_length = 6000

#Used when OPENAI_API_KEY is missing/invalid or the API call fails for any reason — the feature should degrade gracefully, never hard-fail.
def fallback_roadmap(query_text):
    label = query_text if len(query_text) <= 60 else query_text[:60] + "..."
    return {
        "query_label": label,
        "stages": [
            {
                "title":"Fundamentals", "duration":"1-2 weeks", "level":"Beginner", 
                "desc": "The baseline concepts everything else builds on.",
                "topics": ["Core syntax", "Tooling setup", "Version control basics"]
             },            
             {
                "title": "Core concepts", "duration": "2–3 weeks", "level": "Beginner \u2192 Intermediate",
                "desc": "The bulk of what you'll actually use day to day.",
                "topics": ["Key building blocks", "Common patterns", "Standard libraries"]
            },
            {
                "title": "Practical application", "duration": "1–2 weeks", "level": "Intermediate",
                "desc": "Where theory turns into something you can point to.",
                "topics": ["State/data handling", "Working with APIs", "Debugging & tooling"]
            },
            {
                "title": "Testing & best practices", "duration": "1 week", "level": "Intermediate",
                "desc": "The habits that separate hobby code from production code.",
                "topics": ["Testing fundamentals", "Code quality tools", "Documentation"]
            },
            {
                "title": "Advanced & project work", "duration": "2+ weeks", "level": "Advanced",
                "desc": "Depth, plus a project worth putting on your resume.",
                "topics": ["Performance & scale", "Real-world project", "Interview-ready talking points"]
            },
        ]
    }

#Guards against a malformed/truncated AI response reaching the frontend.
def validate_roadmap(data):
    if not isinstance(data, dict):
        return False

    if not isinstance(data.get("query_label"), str):
        return False

    stages = data.get("stages")

    if not isinstance(stages, list) or not (1 <= len(stages) <= 10):
        return False

    for stage in stages:
        if not isinstance(stage, dict):
            return False

        for key in ('title', 'duration', 'level', 'desc', 'topics'):
            if key not in stage:
                return False

        if not isinstance(stage["title"],str) or not stage["title"].strip():
            return False

        if not isinstance(stage["topics"], str) or not stage["topics"].strip():
            return False

    return True

@require_http_methods(["POST"])
def generate_roadmap(request):
    query_text = (request.POST.get("query") or "").strip()

    if len(query_text) < 2:
        return JsonResponse({"error": "Please enter a topic, role, or job description first."}, status=400)

    if len(query_text) > max_input_length:
        query_text = query_text[:max_input_length]

    api_key = getattr(settings, "OPENAI_API_KEY", None)

    if OpenAI is not None and api_key:
        try:
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role":"system", "content":system_prompt},
                    {"role":"user", "content":query_text},
                ],
                response_format={"type":"json_object"},
                temperature=0.4,
                max_tokens=1200,                
            )
            raw = response.choices[0].message.content
            data = json.loads(raw)

            if validate_roadmap(data):
                data["source"] = "ai"
                return JsonResponse(data)

        except Exception:
            pass

    fallback = fallback_roadmap(query_text)
    fallback["source"] = "fallback"

    return JsonResponse(fallback)