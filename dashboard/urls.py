from django.urls import path
from . import views

urlpatterns = [
    path('admin_panel/', views.dashboard_redirect, name="dashboard"),
    path('admin_panel/overview',views.adminOverview, name="adminOverview"),
    path('admin_panel/manage_user', views.manageUsers, name="manageUser"),
    path('admin_panel/manage_user/<int:user_id>/toggle/',views.toggleUserStatus,name='toggle_user_status'),
    path('admin_panel/manage_staffRole', views.manageStaffRole, name="manageStaffRole"),
    path('admin_panel/feedback', views.feedback, name="feedback"),
]
