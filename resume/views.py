from django.shortcuts import render
import json
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from accounts.models import User
from .ats_scoring import compute_ats_score, extract_text
from .models import JDMatchResult, JobDescription, Resume, ResumeAnalysis, ResumeVersion

allowed_extensions = {'pdf':'pdf', 'docx':'docx', 'doc':'docx'}
max_file_size = 5 * 1024 * 1024
min_text_length = 30


""" Anonymous visitors: resume is scored in-memory only, nothing is written
    to the database — matches the "No account needed to see your score" flow.
    Logged-in users (request.session['user_id']): the upload, its parsed
    text, and the analysis are persisted into resume / resume_version /
    resume_analysis (and job_descriptions / jd_match_results if a JD was
    pasted), per the data dictionary. """

@require_http_methods(['POST'])
def analyze_resume(request):
    upload = request.FILES.get('resume')
    jd_text = (request.POST.get('jd') or '' ).strip()

    if not upload:
        return JsonResponse({"error":"Please attach a resume file."}, status=400)

    ext = upload.name.rsplit('.', 1)[-1].lower() if '.' in upload.name else ""

    file_type = allowed_extensions.get(ext)

    if not file_type:
        return JsonResponse({"error": 'Only PDF or DOCX files are supported.'}, status=400)

    if upload.size > max_file_size:
        return JsonResponse({"error": 'File is larger than 5MB.'}, status=400)

    raw_bytes = upload.read()

    try:
        resume_text, has_tables = extract_text(raw_bytes, file_type)
    except Exception:
        return JsonResponse({"error": "We couldn't read that file. Try re-saving it and uploading again."}, status=422)

    if not resume_text or len(resume_text.strip()) < min_text_length:
        return JsonResponse({"error": "We couldn't find readable text in that file — it may be a scanned image."}, status=422)

    result = compute_ats_score(resume_text, jd_text or None, has_tables=has_tables)
    saved = False

    user_id = request.session.get('user_id')
    if user_id:
        try:
            user = User.objects.get(user_id = user_id)
        except User.DoesNotExist:
            user = None

        if user:
            stored_path = default_storage.save(f'resumes/{user.user_id}/{upload.name}', ContentFile(raw_bytes))

            resume = Resume.objects.create(
                user = user,
                file_type = file_type,
                file_path = stored_path,
                parsed_text = resume_text
            )

            next_version_number = (ResumeVersion.objects.filter(resume=resume).count()) + 1

            version = ResumeVersion.objects.create(
                resume = resume,
                version_number = next_version_number,
                content_snapshot = resume_text
            )

            ResumeAnalysis.objects.create(
                version = version,
                ats_score = result['ats_score'],
                grammar_issues = result['grammar_issues'],
                passive_voice_flags = result['passive_voice_flags'],
                missing_sections = result['missing_sections']
            )

            if jd_text:
                jd = JobDescription.objects.create(user=user, jd_text=jd_text)
                JDMatchResult.objects.create(
                    user=user,
                    version=version,
                    jd=jd,
                    match_percentage = result['keyword_match'],
                    missing_keywords = result['missing_keywords'],
                    search_type = 'with_resume'                    
                )

            saved = True

    return JsonResponse({
        'ats_score': result['ats_score'],
        'formatting_score': result['formatting_score'],
        'section_score': result['section_score'],
        'keyword_match': result['keyword_match'],
        'missing_sections': result['missing_sections'],
        'missing_keywords': result['missing_keywords'],
        'saved': saved
    })