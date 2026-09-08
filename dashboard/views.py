from django.shortcuts import redirect
from django.views.generic import TemplateView
from .nav import NAV


def dashboard_redirect(request):
    """
    Target of redirect("dashboard") in accounts/views.py's login_view.
    Sends the user to the right section based on the role stored in
    their session at login.
    """
    if not request.session.get("user_id"):
        return redirect("login")
    if request.session.get("role") == "admin":
        return redirect("dashboard:admin_overview")
    return redirect("dashboard:user_overview")


class DashboardView(TemplateView):
    role = None
    active_url_name = None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["role"] = self.role
        ctx["nav"] = NAV[self.role]
        ctx["active_url_name"] = f"dashboard:{self.active_url_name}"
        return ctx


class UserOverviewView(DashboardView):
    role = "user"
    active_url_name = "user_overview"
    template_name = "dashboard/user/overview.html"


class UserUploadView(DashboardView):
    role = "user"
    active_url_name = "user_upload"
    template_name = "dashboard/user/upload.html"


class UserAnalysisView(DashboardView):
    role = "user"
    active_url_name = "user_analysis"
    template_name = "dashboard/user/analysis.html"


class UserJDMatchView(DashboardView):
    role = "user"
    active_url_name = "user_jd_match"
    template_name = "dashboard/user/jd_match.html"


class UserBulletRewriterView(DashboardView):
    role = "user"
    active_url_name = "user_bullet_rewriter"
    template_name = "dashboard/user/bullet_rewriter.html"


class UserSkillGapView(DashboardView):
    role = "user"
    active_url_name = "user_skill_gap"
    template_name = "dashboard/user/skill_gap.html"


class UserVersionHistoryView(DashboardView):
    role = "user"
    active_url_name = "user_version_history"
    template_name = "dashboard/user/version_history.html"


class UserQuestionGeneratorView(DashboardView):
    role = "user"
    active_url_name = "user_question_generator"
    template_name = "dashboard/user/question_generator.html"


class UserTestExamView(DashboardView):
    role = "user"
    active_url_name = "user_test_exam"
    template_name = "dashboard/user/test_exam.html"


class UserWeakAreasView(DashboardView):
    role = "user"
    active_url_name = "user_weak_areas"
    template_name = "dashboard/user/weak_areas.html"


class UserExportView(DashboardView):
    role = "user"
    active_url_name = "user_export"
    template_name = "dashboard/user/export.html"


class UserFeedbackView(DashboardView):
    role = "user"
    active_url_name = "user_feedback"
    template_name = "dashboard/user/feedback.html"


class AdminOverviewView(DashboardView):
    role = "admin"
    active_url_name = "admin_overview"
    template_name = "dashboard/admin/overview.html"


class AdminUsersView(DashboardView):
    role = "admin"
    active_url_name = "admin_users"
    template_name = "dashboard/admin/users.html"


class AdminStaffRolesView(DashboardView):
    role = "admin"
    active_url_name = "admin_staff_roles"
    template_name = "dashboard/admin/staff_roles.html"


class AdminFeedbackView(DashboardView):
    role = "admin"
    active_url_name = "admin_feedback"
    template_name = "dashboard/admin/feedback.html"