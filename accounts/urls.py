from django.urls import path
from . import views


urlpatterns = [
    path('register/', views.register_view, name="register"),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name="logout"),


    path('admin_panel/settings/', views.adminSettings, name='admin_settings'),
    path('admin_panel/settings/profile/', views.adminUpdateProfile, name='admin_update_profile'),
    path('admin_panel/settings/password/', views.adminChangePassword, name='admin_change_password'),
    path("auth/google/", views.login_with_google_view, name="google_login"),
]
