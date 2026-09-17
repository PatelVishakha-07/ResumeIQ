from django.urls import path
from . import views

urlpatterns = [
    path("user/interview_prep/", views.interview_prep_view, name="interview_prep"),        
    path("user/generate_question/", views.generate_questions, name="generate_question"),
    path("user/question_result/", views.questions_result_view, name="question_result"),
    path("user/take_exam/", views.take_exam_view, name="take_exam"),
    path("user/submit_exam", views.submit_exam_view, name="submit_exam"),
    path("user/quiz_questions", views.generate_quiz_view, name="quiz_questions"),
    path("user/quiz_result", views.quiz_generated_result_view, name="quiz_result"),
]
