from django.db import models
from accounts.models import User

# Create your models here.
class Feedback(models.Model):
    Category_Choices = [
        ("general", "General"),
        ("resume", "Resume tools"),
        ("ats", "ATS score"),
        ("roadmap", "Roadmap"),
        ("interview", "Interview prep"),
        ("idea", "Feature idea"),
        ("bug", "Something is broken")
    ]

    Status_Choices = [
        ("new", "New"),
        ("reviewed", "Reviewed")
    ]

    feedback_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column="user_id")
    rating = models.PositiveSmallIntegerField()
    category = models.CharField(max_length=20, choices=Category_Choices)
    message = models.TextField()
    status = models.CharField(max_length=10, choices=Status_Choices, default="new")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "feedback"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(check=models.Q(rating__gte=1) & models.Q(rating__lte=5),
            name = "feedback_rating_range")
        ]

    @property
    def stars(self):
        return "\u2605" * self.rating + "\u2606" * (5 - self.rating)

    def __str__(self):
        return f"Feedback #{self.feedback_id} ({self.rating}/5) \u2014 user #{self.user_id}"

