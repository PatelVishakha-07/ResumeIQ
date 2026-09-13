from django.urls import path
from . import views

urlpatterns = [

    path('dashboard/', views.dashboard_redirect, name="dashboard"),
    path('ats_score_generator/', views.ats_score_generator_view, name="ats_score_generator"),
    path("resume_history/", views.resume_history_view, name="resume_history"),

    
    path('admin_panel/overview',views.adminOverview, name="adminOverview"),
    path('admin_panel/manage_user', views.manageUsers, name="manageUser"),
    path('admin_panel/manage_user/<int:user_id>/toggle/',views.toggleUserStatus,name='toggle_user_status'),
    path('admin_panel/manage_user/<int:user_id>/', views.userDetail, name='user_detail'),
    path('admin_panel/manage_staffRole', views.manageStaffRole, name="manageStaffRole"),
    path('admin_panel/feedback', views.feedback, name="feedback"),
    path('admin_panel/settings/', views.adminSettings, name='admin_settings'),
    path('admin_panel/settings/profile/', views.adminUpdateProfile, name='admin_update_profile'),
    path('admin_panel/settings/password/', views.adminChangePassword, name='admin_change_password'),
]
