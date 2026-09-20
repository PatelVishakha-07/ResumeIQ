"""
Export model — resume/models.py import stays the same, but the `resume`
field is now nullable.

Why: LinkedIn summary exports no longer go through a resume at all (pure
Q&A flow), so there's nothing to attach as `resume_id` for those rows.
Cover letter exports still always have one. null=True/blank=True lets
both cases live in the same table, matching table 11 ("exports") in your
data dictionary but relaxing the NOT NULL on resume_id specifically for
this reason.
"""

import uuid

from accounts.models import User
from django.db import models

from resume.models import Resume


def export_file_upload_path(instance, filename):
    """/exports/<user_id>_<export_type>_<uuid>.<ext> — avoids filename collisions."""
    ext = filename.rsplit(".", 1)[-1].lower()
    return f"exports/{instance.user_id}_{instance.export_type}_{uuid.uuid4().hex[:8]}.{ext}"


class Export(models.Model):
    EXPORT_TYPE_CHOICES = [
        ("resume", "Improved Resume"),
        ("linkedin", "LinkedIn Summary"),
        ("cover_letter", "Cover Letter"),
    ]

    export_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="exports", db_column="user_id"
    )
    # CHANGED: null=True, blank=True — LinkedIn exports have no resume.
    resume = models.ForeignKey(
        Resume,
        on_delete=models.CASCADE,
        related_name="exports",
        db_column="resume_id",
        null=True,
        blank=True,
    )
    export_type = models.CharField(max_length=20, choices=EXPORT_TYPE_CHOICES)
    # The raw generated text — kept alongside the PDF so it can be shown,
    # re-edited, or reused without having to parse it back out of the PDF.
    content = models.TextField()
    file_path = models.FileField(upload_to=export_file_upload_path)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "exports"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_export_type_display()} for {self.user.name} (#{self.export_id})"