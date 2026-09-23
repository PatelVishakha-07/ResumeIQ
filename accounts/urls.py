from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register_view, name="register"),
    path("register/send_otp/", views.register_send_otp, name="register_send_otp"),
    path("register/verify_otp/", views.register_verify_otp, name="register_verify_otp"),
    path("register/resend_otp/", views.register_resend_otp, name="register_resend_otp"),
    path("forgot_password/", views.forgot_password_view, name="forgot_password"),
    path("forgot_password/send_otp/", views.forgot_password_send_otp, name="forgot_password_send_otp"),
    path("forgot_password/verify_otp/", views.forgot_password_verify_otp, name="forgot_password_verify_otp"),
    path("forgot_password/resend_otp/", views.forgot_password_resend_otp, name="forgot_password_resend_otp"),
    path("forgot_password/reset/", views.forgot_password_reset, name="forgot_password_reset"),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name="logout"),    
    
    path('settings/', views.account_settings, name='account_settings'),
    path('settings/profile/', views.account_update_profile, name='account_update_profile'),
    path('settings/password/', views.account_change_password, name='account_change_password'),
]