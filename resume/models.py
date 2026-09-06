from django.db import models
from accounts.models import User

#Resume table
class Resume(models.Model):
    file_type_choices = [
        ('pdf', 'PDF'),
        ('docx', 'DOCX')
    ]

    resume_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column='user_id', related_name='resumes')

    file_path = models.CharField(max_length=255)
    file_type = models.CharField(max_length=10, choices=file_type_choices)
    parsed_text = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "resume"

    def __str__(self):
        return f"Resume #{self.resume_id} ({self.user.email})"

#resume_version — every revision of a resume, for score trends over time
class ResumeVersion(models.Model):
    version_id = models.AutoField(primary_key=True)
    resume = models.ForeignKey(Resume, on_delete=models.CASCADE, db_column='resume_id', name='versions')

    version_number = models.IntegerField()
    content_snapshot = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "resume_version"
        ordering = ['version_number']

    def __str__(self):
        return f"Resume #{self.resume_id} - v {self.version_number}"


#Resume Analysis table: AI analysis output for one resume version
class ResumeAnalysis(models.Model):
    analysis_id = models.AutoField(primary_key=True)
    version = models.ForeignKey(ResumeVersion, on_delete=models.CASCADE, db_column='version_id', name='analyses')

    ats_score = models.DecimalField(max_digits=5, decimal_places=2)
    grammar_issues = models.JSONField(null=True, blank=True)
    passive_voice_flags = models.JSONField(null=True, blank=True)
    missing_section = models.JSONField(null=True, blank=True)
    analyzed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'resume_analysis'
        constraints = [
            models.CheckConstraint(
                check = models.Q(ats_score__gte=0) & models.Q(ats_score__lte = 100),
                name = 'resume_analysis_ats_score_range'
            )
        ]

    def __str__(self):
        return f'Analysis #{self.analysis_id} - score {self.ats_score}'

#Job description table: JD a user pastes in, for matching or question generation.
class JobDescription(models.Model):
    jd_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column='user_id', name='job_descriptions')

    jd_text = models.TextField()
    target_role = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'job_descriptions'

    def __str__(self):
        return f"JD #{self.jd_id} ({self.target_role or 'untitled'})"


#jd_match_results — match results for both with-resume and without-resume flows
class JDMatchResult(models.Model):
    match_id = models.AutoField(primary_key=True)

    search_type_choices = [
        ('with_resume', 'With Resume'),
        ('without_resume', 'Without Resume')
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column='user_id', related_name='jd_matches')
    version = models.ForeignKey(ResumeVersion, on_delete=models.CASCADE, db_column='version_id', related_name='jd_matches', null=True, blank=True)
    jd = models.ForeignKey(JobDescription, on_delete=models.CASCADE, db_column='jd_id', related_name='jd_matches')

    match_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    missing_keywords = models.JSONField(null=True, blank=True)
    search_type = models.CharField(max_length=20, choices=search_type_choices)
    required_skills = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'jd_matches'
        constraints = [
            models.CheckConstraint(
                check = models.Q(match_percentage__isnull = True) |( models.Q(match_percentage__gte=0) & models.Q(match_percentage__lte=100)),
                name = 'jd_match_results_percentage_range'
            )
        ]

    def __str__(self):
        return f"Match #{self.match_id} ({self.search_type})"