from django.urls import path
from . import views

urlpatterns = [


    path('dashboard/', views.dashboard_redirect, name="dashboard"),
    path('ats_score_generator/', views.ats_score_generator_view, name="ats_score_generator"),
    path("resume_history/", views.resume_history_view, name="resume_history"),

    

    path('dashboard/', views.dashboard_redirect, name="dashboard"),
    path('ats_score_generator/', views.ats_score_generator_view, name="ats_score_generator"),
    path("resume_history/", views.resume_history_view, name="resume_history"),
    path('user/view_resume_report/<int:version_id>/', views.resume_report_view, name="view_resume_report"),
    path("user/resume_report/<int:version_id>/download/", views.download_report_resume_view, name="resume_report_download"),
    path("user/roadmap_generator_view/", views.roadmap_generator_view, name="roadmap_generator"),
    path("user/generate_roadmap/", views.generate_roadmap, name="generate_roadmap"),


    path('admin_panel/overview',views.adminOverview, name="adminOverview"),
    path('admin_panel/manage_user', views.manageUsers, name="manageUser"),
    path('admin_panel/manage_user/<int:user_id>/toggle/',views.toggleUserStatus,name='toggle_user_status'),
    path('admin_panel/manage_user/<int:user_id>/', views.userDetail, name='user_detail'),
    path('admin_panel/manage_staffRole', views.manageStaffRole, name="manageStaffRole"),
    path('admin_panel/reports', views.reports, name="reports"),
    path('admin_panel/feedback', views.feedback, name="feedback"),


]
