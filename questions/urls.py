from django.urls import path
from . import views

urlpatterns = [
    path("user/interview_prep/", views.interview_prep_view, name="interview_prep"),
]
