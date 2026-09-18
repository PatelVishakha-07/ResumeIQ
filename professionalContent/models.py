"""
Export model — add this to resume/models.py (same app as Resume,
ResumeVersion, ResumeAnalysis, JDMatchResult, which the export views
already import from `resume.models`).

Matches table 11 ("exports") in your data dictionary:
  export_id, user_id, resume_id, export_type, file_path, created_at

field_path is a FileField (not CharField) so that
`export.file_path.save(filename, ContentFile(...), save=True)` in
save_export_document works directly — Django's FileField stores the
relative path as a string under the hood, same idea as file_path in
your data dictionary, but it also handles the actual file write/read
for you.
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
    resume = models.ForeignKey(
        Resume, on_delete=models.CASCADE, related_name="exports", db_column="resume_id"
    )
    export_type = models.CharField(max_length=20, choices=EXPORT_TYPE_CHOICES)
    file_path = models.FileField(upload_to=export_file_upload_path)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "exports"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_export_type_display()} for {self.user.name} (#{self.export_id})"