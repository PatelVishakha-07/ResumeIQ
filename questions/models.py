from django.db import models
from accounts.models import User
from resume.models import Resume    

class Questions(models.Model):
    questions_type_list = [
        ("mcq", "MCQ"),
        ("behavioral", "Behavioral"),
        ("technical", "Technical")
    ]

    levels_list = [
        ("easy", "Easy"),
        ("intermediate", "Intermediate"),
        ("advanced", "Advanced"),
        ("expert", "Expert")
    ]

    question_id = models.AutoField(primary_key=True)
    resume = models.ForeignKey(Resume, on_delete=models.CASCADE, null=True, blank=True, db_column="resume_id")

    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column="user_id", blank=True, null=True)

    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=questions_type_list)
    options = models.JSONField(null=True, blank=True)

    correct_answer = models.TextField( null=True, blank=True)
    level = models.CharField(max_length=20, choices=levels_list)

    class Meta:
        db_table = "questions"

    def __str__(self):
        return f"Question #{self.question_id} ({self.question_type})"


class WeakArea(models.Model):
    weak_area_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column="user_id", blank=True, null=True)
    topic = models.CharField(max_length=100)
    performance_score = models.DecimalField(max_digits=5, decimal_places=2)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "weak_areas"
        constraints = [
            models.CheckConstraint(
                check=models.Q(performance_score__gte=0) & models.Q(performance_score__lte=100),
                name="weak_area_performance_score_range",
            ),
        ]

    def __str__(self):
        return f"{self.topic} ({self.performance_score}) \u2014 user #{self.user_id}"