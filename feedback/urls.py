from django.urls import path
from . import views


urlpatterns = [
    path("user/feedback/", views.user_feedback_view, name="user_feedback"),
    path("panel/feedback/", views.admin_feedback_list, name="feedback"),
    path("panel/feedback/<int:feedback_id>/", views.admin_feedback_detail, name="feedback_detail"),
]