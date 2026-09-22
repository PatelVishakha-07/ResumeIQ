from django.urls import path
from . import views

urlpatterns = [
    path('analyze/', views.analyze_resume, name='analyze_resume'),
    path("download-optimized/", views.download_optimized_resume, name="download_optimized_resume"),
    path('recheck-optimized/', views.recheck_optimized_resume, name='recheck_optimized_resume'),
]
