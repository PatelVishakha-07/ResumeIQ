from django.urls import path
from . import views

urlpatterns = [
    path('professional-content/', views.professionalContent, name='professional_content'),
    path("export/", views.export_documents_choice, name="export_documents"),

    path("export/cover-letter/", views.cover_letter_wizard_view, name="cover_letter_wizard"),
    path("export/linkedin/", views.linkedin_wizard_view, name="linkedin_wizard"),

    path("export/next-question/", views.generate_next_question, name="generate_next_question"),
    path("export/generate-final/", views.generate_final_document, name="generate_final_document"),

    # Cover letter: still tied to a resume version.
    path("export/save/<int:version_id>/<str:export_type>/",views.save_export_document,name="save_export_document"),
    # LinkedIn: no resume version at all.
    path("export/save/<str:export_type>/",views.save_export_document,name="save_export_document_no_version"),

    path("export/autosave/linkedin/", views.autosave_linkedin, name="autosave_linkedin"),
]