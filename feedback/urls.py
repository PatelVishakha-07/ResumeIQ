from django.urls import path
from . import views

urlpatterns = [
    path("user/feedback/", views.user_feedback_view, name="user_feedback"),
]