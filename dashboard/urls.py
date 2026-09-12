from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard_redirect, name="dashboard"),
    path('ats_score_generator/', views.ats_score_generator_view, name="ats_score_generator"),
    path("resume_history/", views.resume_history_view, name="resume_history"),
]
