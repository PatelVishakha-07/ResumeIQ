from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register_view, name="register"),
    path("register/send_otp", views.register_send_otp, name="register_send_otp"),
    path("register/verify_otp", views.register_verify_otp, name="register_verify_otp"),
    path("register/resend_otp", views.register_resend_otp, name="register_resend_otp"),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name="logout"),    
    
    path('admin_panel/settings/', views.adminSettings, name='admin_settings'),
    path('admin_panel/settings/profile/', views.adminUpdateProfile, name='admin_update_profile'),
    path('admin_panel/settings/password/', views.adminChangePassword, name='admin_change_password'),
    
]
