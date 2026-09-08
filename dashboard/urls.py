from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    # Job Seeker / User
    path("user/", views.UserOverviewView.as_view(), name="user_overview"),
    path("user/upload/", views.UserUploadView.as_view(), name="user_upload"),
    path("user/analysis/", views.UserAnalysisView.as_view(), name="user_analysis"),
    path("user/jd-match/", views.UserJDMatchView.as_view(), name="user_jd_match"),
    path("user/bullet-rewriter/", views.UserBulletRewriterView.as_view(), name="user_bullet_rewriter"),
    path("user/skill-gap/", views.UserSkillGapView.as_view(), name="user_skill_gap"),
    path("user/version-history/", views.UserVersionHistoryView.as_view(), name="user_version_history"),
    path("user/questions/", views.UserQuestionGeneratorView.as_view(), name="user_question_generator"),
    path("user/test/", views.UserTestExamView.as_view(), name="user_test_exam"),
    path("user/weak-areas/", views.UserWeakAreasView.as_view(), name="user_weak_areas"),
    path("user/export/", views.UserExportView.as_view(), name="user_export"),
    path("user/feedback/", views.UserFeedbackView.as_view(), name="user_feedback"),

    # Admin / T&P — routed under admin-panel/ so it never clashes with
    # Django's own built-in /admin/ site.
    path("admin-panel/", views.AdminOverviewView.as_view(), name="admin_overview"),
    path("admin-panel/users/", views.AdminUsersView.as_view(), name="admin_users"),
    path("admin-panel/staff-roles/", views.AdminStaffRolesView.as_view(), name="admin_staff_roles"),
    path("admin-panel/feedback/", views.AdminFeedbackView.as_view(), name="admin_feedback"),
]
