from django.shortcuts import render
import json, logging
import os, re
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from docx import Document
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from accounts.models import User
from .ats_scoring import build_structured_resume, compute_ats_score, extract_text
from .bullet_writer import rewrite_bullets, extract_bullets, BulletRewriteError
from accounts.ratelimit import ai_rate_limit

logger = logging.getLogger(__name__)

try:
    from google import genai
except ImportError:
    genai = None
from .models import JDMatchResult, JobDescription, Resume, ResumeAnalysis, ResumeVersion, BulletRewrite

allowed_extensions = {
    'pdf': 'pdf', 'docx': 'docx', 'doc': 'docx',
    # pictures are accepted only so we can tell the user they score very low
    'png': 'image', 'jpg': 'image', 'jpeg': 'image',
}
max_file_size = 5 * 1024 * 1024
min_text_length = 30


""" Anonymous visitors: resume is scored in-memory only, nothing is written
    to the database — matches the "No account needed to see your score" flow.
    Logged-in users (request.session['user_id']): the upload, its parsed
    text, and the analysis are persisted into resume / resume_version /
    resume_analysis (and job_descriptions / jd_match_results if a JD was
    pasted), per the data dictionary.
    Image-based resumes (scans, screenshots, jpg/png) get a very low score
    plus an explanation, and are not persisted. """


@require_http_methods(['POST'])
def download_optimized_resume(request):
    """Generate a professionally formatted DOCX from the edited resume JSON."""
    raw = request.POST.get('resume_json') or ''
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid resume editor data.'}, status=400)

    if not isinstance(data, dict):
        return JsonResponse({'error': 'Invalid resume structure.'}, status=400)

    if not optimized_data_to_plain_text(data).strip():
        return JsonResponse({'error': 'Resume content is empty.'}, status=400)

    try:
        document = build_professional_resume_docx(data)
    except Exception:
        logger.exception("Could not create the DOCX resume")
        return JsonResponse({'error': 'Could not create the DOCX resume.'}, status=500)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = 'attachment; filename="ATS_Optimized_Resume.docx"'
    document.save(response)
    return response

def _as_list(value):
    if isinstance(value, list):
        return value
    if value in (None, ''):
        return []
    return [value]


def _clean_string(value):
    return str(value or '').strip()


def _normalize_ai_resume(data):
    """Guarantee one stable structure for both AI output and the editor."""
    if not isinstance(data, dict):
        return None

    result = {
        'name': _clean_string(data.get('name')),
        'headline': _clean_string(data.get('headline')),
        'contact': [_clean_string(x) for x in _as_list(data.get('contact')) if _clean_string(x)],
        'summary': _clean_string(data.get('summary')),
        'skills': {},
        'experience': [],
        'projects': [],
        'education': [],
        'certifications': [],
        'achievements': [],
        'languages': [],
    }

    skills = data.get('skills') or {}
    if isinstance(skills, dict):
        for category, values in skills.items():
            category = _clean_string(category)
            if not category:
                continue
            cleaned = [_clean_string(x) for x in _as_list(values) if _clean_string(x)]
            if cleaned:
                result['skills'][category] = cleaned

    def normalize_entry(item, kind):
        if isinstance(item, str):
            return {'title': '', 'company': '', 'location': '', 'dates': '', 'technologies': [], 'details': [], 'bullets': [item.strip()]} if kind == 'experience' else (
                {'name': item.strip(), 'technologies': [], 'description': '', 'bullets': []} if kind == 'projects' else
                {'degree': item.strip(), 'institution': '', 'location': '', 'dates': '', 'details': []}
            )
        if not isinstance(item, dict):
            return None

        if kind == 'experience':
            return {
                'title': _clean_string(item.get('title') or item.get('role') or item.get('position')),
                'company': _clean_string(item.get('company') or item.get('organization')),
                'location': _clean_string(item.get('location')),
                'dates': _clean_string(item.get('dates') or item.get('date') or item.get('duration')),
                'bullets': [_clean_string(x) for x in _as_list(item.get('bullets') or item.get('responsibilities') or item.get('details')) if _clean_string(x)],
            }
        if kind == 'projects':
            return {
                'name': _clean_string(item.get('name') or item.get('title') or item.get('project')),
                'technologies': [_clean_string(x) for x in _as_list(item.get('technologies') or item.get('technology') or item.get('tech_stack')) if _clean_string(x)],
                'description': _clean_string(item.get('description')),
                'bullets': [_clean_string(x) for x in _as_list(item.get('bullets') or item.get('details')) if _clean_string(x)],
            }
        return {
            'degree': _clean_string(item.get('degree') or item.get('qualification') or item.get('title')),
            'institution': _clean_string(item.get('institution') or item.get('college') or item.get('university')),
            'location': _clean_string(item.get('location')),
            'dates': _clean_string(item.get('dates') or item.get('date') or item.get('duration')),
            'details': [_clean_string(x) for x in _as_list(item.get('details') or item.get('bullets')) if _clean_string(x)],
        }

    for kind in ('experience', 'projects', 'education'):
        for item in _as_list(data.get(kind)):
            normalized = normalize_entry(item, kind)
            if normalized and any(normalized.values()):
                result[kind].append(normalized)

    for key in ('certifications', 'achievements', 'languages'):
        for item in _as_list(data.get(key)):
            if isinstance(item, dict):
                value = item.get('name') or item.get('title') or item.get('text') or item.get('value')
            else:
                value = item
            value = _clean_string(value)
            if value:
                result[key].append(value)

    return result

def _clean_notes(raw):
    raw = raw if isinstance(raw, dict) else {}

    def pick(key):
        return [_clean_string(x) for x in _as_list(raw.get(key)) if _clean_string(x)][:8]

    return {
        "changes": pick("changes"),
        "matched_skills": pick("matched_skills"),
        "missing_skills": pick("missing_skills"),
        "suggestions": pick("suggestions"),
    }


def _rule_based_notes(ats_result, jd_text):
    notes = {"changes": [], "matched_skills": [], "missing_skills": [], "suggestions": []}
    if jd_text and jd_text.strip():
        notes["missing_skills"] = [g["keyword"] for g in (ats_result.get("jd_gaps") or [])][:8]
        if notes["missing_skills"]:
            notes["suggestions"].append(
                "Add the missing job-description terms only where you genuinely have the skill."
            )
    notes["suggestions"].extend((ats_result.get("recommendations") or [])[:3])
    return notes


def improve_resume_with_ai(resume_text, jd_text="", ats_result=None):
    """Returns (structured_resume, improvement_notes)."""
    ats_result = ats_result or {}
    notes = _rule_based_notes(ats_result, jd_text)
    fallback = _normalize_ai_resume(build_structured_resume(resume_text))

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or genai is None:
        notes["suggestions"].insert(0, "AI tailoring is unavailable, so your resume was only reformatted.")
        return fallback, notes

    has_jd = bool(jd_text and jd_text.strip())
    jd_block = jd_text.strip() if has_jd else "(none provided)"

    try:
        client = genai.Client(api_key=api_key)

        prompt = f"""
You are ResumeIQ's professional resume improvement engine.

Convert the source resume into a clean, professional, ATS-friendly editable
resume, tailored to the job description when one is provided.

GENERAL RULES

1. Restore missing spaces between words.
   VISHAKHAPARESHKUMARPATEL -> Vishakha Pareshkumar Patel
   AspiringSoftwareDeveloper -> Aspiring Software Developer
   Final-yearMCAstudent -> Final-year MCA student

2. NEVER mix contact information with the summary. Contact contains only
   location, phone, email, LinkedIn, GitHub, portfolio and other profile links.

3. PROFESSIONAL SUMMARY contains only the candidate's professional summary.

4. Preserve actual information from the source.

5. NEVER invent: company, job, degree, project, technology, certification,
   date, achievement, metric, URL or responsibility.

6. You may improve grammar, sentence structure, capitalization, readability,
   action verbs and bullet wording.

7. Keep all real projects, education, certifications, skills and achievements.

TAILORING TO THE JOB DESCRIPTION (only when one is provided)

a. Rewrite the headline and professional summary so they speak to the job
   description's role. Use only skills and experience the source resume truly
   shows. Emphasise transferable strengths that match the job description
   (for example object-oriented programming, SQL, REST APIs, backend
   frameworks, testing).
b. Reorder skill groups, projects and bullets so the ones most relevant to the
   job description come first. Use the job description's wording only when it
   is an accurate synonym of something already in the resume.
c. NEVER add a technology, tool or skill from the job description that the
   resume does not already show. If the resume has Python but the job asks for
   Java, do not claim Java anywhere. Do not use the job's title as the
   headline if the candidate lacks the role's core skill; write a truthful
   headline instead.
d. Everything the job description needs that the resume does not show goes
   into improvement_notes.missing_skills, never into the resume.

IMPROVEMENT NOTES

- changes: 3 to 6 short sentences saying what you changed and why.
- matched_skills: job-description requirements the resume genuinely satisfies.
- missing_skills: job-description requirements the resume does not show.
- suggestions: 2 to 4 honest, practical tips (for example build and list a real
  project with the missing technology, or earn a certification).
If no job description is provided, leave matched_skills and missing_skills
empty and describe general improvements in changes and suggestions.

Return ONLY valid JSON in this format:

{{
    "name": "",
    "headline": "",
    "contact": [],
    "summary": "",
    "skills": {{}},
    "experience": [
        {{"title": "", "company": "", "location": "", "dates": "", "bullets": []}}
    ],
    "projects": [
        {{"name": "", "technologies": [], "description": "", "bullets": []}}
    ],
    "education": [
        {{"degree": "", "institution": "", "location": "", "dates": "", "details": []}}
    ],
    "certifications": [],
    "achievements": [],
    "languages": [],
    "improvement_notes": {{
        "changes": [],
        "matched_skills": [],
        "missing_skills": [],
        "suggestions": []
    }}
}}

SOURCE RESUME:

{resume_text}

JOB DESCRIPTION:

{jd_block}
"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"temperature": 0.3, "response_mime_type": "application/json"},
        )

        result = json.loads(response.text)
        if not isinstance(result, dict):
            raise ValueError("AI returned a non-object response")

        ai_notes = _clean_notes(result.pop("improvement_notes", None))
        improved = _normalize_ai_resume(result)
        if not improved:
            raise ValueError("AI returned an invalid resume structure")

        merged = {key: ai_notes[key] or notes[key] for key in notes}
        return improved, merged

    except Exception:
        logger.exception("Resume AI improvement failed")


@require_http_methods(['POST'])
@ai_rate_limit('analyze', user_limit=30, anon_limit=10)
def analyze_resume(request):

    upload = request.FILES.get('resume')
    jd_text = (request.POST.get('jd') or '').strip()

    if not upload:
        return JsonResponse({"error": "Please attach a resume file."}, status=400)

    ext = upload.name.rsplit('.', 1)[-1].lower() if '.' in upload.name else ""

    file_type = allowed_extensions.get(ext)

    if not file_type:
        return JsonResponse({"error": 'Only PDF or DOCX files are supported.'}, status=400)

    if upload.size > max_file_size:
        return JsonResponse({"error": 'File is larger than 5MB.'}, status=400)

    raw_bytes = upload.read()

    """ try:
        resume_text, has_tables, content_meta = extract_text(raw_bytes, file_type)
    except Exception:
        return JsonResponse({"error": "We couldn't read that file. Try re-saving it and uploading again."}, status=422) """

    try:
        resume_text, has_tables, content_meta = extract_text(
            raw_bytes,
            file_type
        )

    except Exception:
        logger.exception("Resume extraction failed")
        return JsonResponse(
            {"error": "We couldn't read that file. Try re-saving it and uploading again."},
            status=422
        )
    
    resume_text = resume_text or ''

    # Empty text is no longer a hard error when the file contains images:
    # that is exactly the "image resume" case and it should be scored (very low).
    has_images = content_meta.get('image_count', 0) > 0 or content_meta.get('is_image_file')
    if len(resume_text.strip()) < min_text_length and not has_images:
        return JsonResponse({"error": "We couldn't find readable text in that file."}, status=422)

    result = compute_ats_score(resume_text, jd_text or None, has_tables=has_tables, content_meta=content_meta)
    saved = False

    user_id = request.session.get('user_id')
    if user_id and not result['image_based']:
        try:
            user = User.objects.get(user_id=user_id)
        except User.DoesNotExist:
            user = None

        if user:
            stored_path = default_storage.save(f'resumes/{user.user_id}/{upload.name}', ContentFile(raw_bytes))

            # Re-uploading a file with the same name adds a new version to the
            # existing resume (v2, v3, ...) instead of creating a separate resume.
            # Django may have stored it as "<name>_<7 random chars>.<ext>" if the
            # name was already taken, so match both spellings.
            stem, _, ext_name = upload.name.rpartition('.')
            prefix = f'resumes/{user.user_id}/{stem}'
            same_file = re.compile(rf'^{re.escape(prefix)}(_[A-Za-z0-9]{{7}})?\.{re.escape(ext_name)}$')
            candidates = Resume.objects.filter(user=user, file_path__startswith=prefix).order_by('-updated_at')
            resume = next((r for r in candidates if same_file.match(r.file_path)), None)

            if resume:
                resume.file_type = file_type
                resume.file_path = stored_path
                resume.parsed_text = resume_text
                resume.save()
            else:
                resume = Resume.objects.create(
                    user=user,
                    file_type=file_type,
                    file_path=stored_path,
                    parsed_text=resume_text
                )

            next_version_number = (ResumeVersion.objects.filter(versions=resume).count()) + 1

            version = ResumeVersion.objects.create(
                versions=resume,
                version_number=next_version_number,
                content_snapshot=resume_text
            )

            ResumeAnalysis.objects.create(
                analyses=version,
                ats_score=result['ats_score'],
                grammar_issues=result['grammar_issues'],
                passive_voice_flags=result['passive_voice_flags'],
                missing_section=result['missing_sections']
            )

            if jd_text:
                jd = JobDescription.objects.create(job_descriptions=user, jd_text=jd_text)
                JDMatchResult.objects.create(
                    user=user,
                    version=version,
                    jd=jd,
                    match_percentage=result['keyword_match'],
                    missing_keywords=result['missing_keywords'],
                    search_type='with_resume'
                )

            saved = True

    # The AI rewrite costs money, so it is only run for signed-in users.
    if result['image_based'] or not user_id:
        optimized_resume, improvement_notes = None, None
    else:
        optimized_resume, improvement_notes = improve_resume_with_ai(resume_text, jd_text, result)

    return JsonResponse({
        'ats_score': result['ats_score'],
        'formatting_score': result['formatting_score'],
        'section_score': result['section_score'],
        'keyword_match': result['keyword_match'],
        'missing_sections': result['missing_sections'],
        'missing_keywords': result['missing_keywords'],
        'jd_gaps': result.get('jd_gaps', []),
        'optimized_resume': optimized_resume,
        'image_based': result['image_based'],
        'image_warnings': result['image_warnings'],
        'saved': saved,
        'improvement_notes': improvement_notes,
    })

@require_http_methods(['POST'])
@ai_rate_limit('recheck', user_limit=60, anon_limit=20)
def recheck_optimized_resume(request):
    """
    Re-check the edited optimized resume against the job description.
    The frontend sends the edited structured resume as JSON.
    """

    raw = request.POST.get('resume_json') or ''
    jd_text = (request.POST.get('jd') or '').strip()

    # ---------------------------------------------------------
    # Convert JSON from the editor back into Python dictionary
    # ---------------------------------------------------------
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return JsonResponse(
            {
                'error': 'Invalid resume editor data.'
            },
            status=400
        )

    # ---------------------------------------------------------
    # Convert structured resume into plain ATS-readable text
    # ---------------------------------------------------------
    edited_text = optimized_data_to_plain_text(data)

    if len(edited_text.strip()) < min_text_length:
        return JsonResponse(
            {
                'error': 'Please enter more resume content before re-checking.'
            },
            status=400
        )

    # ---------------------------------------------------------
    # Run ATS scoring again
    # ---------------------------------------------------------
    try:
        result = compute_ats_score(
            edited_text,
            jd_text if jd_text else None,
            has_tables=False,
            content_meta={
                'page_count': 1,
                'image_count': 0,
                'significant_images': 0,
                'image_area_ratio': 0.0,
                'is_image_file': False,
            }
        )

    except Exception:
        logger.exception("Could not re-check the edited resume")
        return JsonResponse({'error': 'Could not re-check the edited resume.'}, status=500)
    
    # ---------------------------------------------------------
    # Build actionable JD gaps
    # ---------------------------------------------------------
    jd_gaps = result.get('jd_gaps')

    if jd_gaps is None:
        jd_gaps = build_jd_gaps_from_result(
            result,
            jd_text
        )

    # ---------------------------------------------------------
    # Return new score to JavaScript
    # ---------------------------------------------------------
    return JsonResponse(
        {
            'ats_score': result.get('ats_score', 0),

            'formatting_score':
                result.get('formatting_score', 0),

            'section_score':
                result.get('section_score', 0),

            'keyword_match':
                result.get('keyword_match', 0),

            'missing_sections':
                result.get('missing_sections', []),

            'missing_keywords':
                result.get('missing_keywords', []),

            'jd_gaps':
                jd_gaps,

            'image_based':
                result.get('image_based', False),

            'image_warnings':
                result.get('image_warnings', []),
        }
    )

def optimized_data_to_plain_text(data):
    """Convert the editor structure into ATS-readable text."""
    data = _normalize_ai_resume(data) or {}
    lines = []

    for key in ('name', 'headline'):
        if data.get(key):
            lines.append(data[key])
    if data.get('contact'):
        lines.append(' | '.join(data['contact']))

    if data.get('summary'):
        lines += ['', 'PROFESSIONAL SUMMARY', data['summary']]

    if data.get('skills'):
        lines += ['', 'SKILLS']
        for category, values in data['skills'].items():
            if values:
                lines.append(f"{category}: {', '.join(values)}")

    if data.get('experience'):
        lines += ['', 'EXPERIENCE']
        for item in data['experience']:
            header = ' — '.join(x for x in [item.get('title'), item.get('company')] if x)
            if header:
                lines.append(header)
            meta = ' | '.join(x for x in [item.get('location'), item.get('dates')] if x)
            if meta:
                lines.append(meta)
            for bullet in item.get('bullets', []):
                if bullet:
                    lines.append(f'• {bullet}')

    if data.get('projects'):
        lines += ['', 'PROJECTS']
        for item in data['projects']:
            if item.get('name'):
                lines.append(item['name'])
            if item.get('technologies'):
                lines.append('Technologies: ' + ', '.join(item['technologies']))
            if item.get('description'):
                lines.append(item['description'])
            for bullet in item.get('bullets', []):
                if bullet:
                    lines.append(f'• {bullet}')

    if data.get('education'):
        lines += ['', 'EDUCATION']
        for item in data['education']:
            if item.get('degree'):
                lines.append(item['degree'])
            meta = ' | '.join(x for x in [item.get('institution'), item.get('location'), item.get('dates')] if x)
            if meta:
                lines.append(meta)
            for detail in item.get('details', []):
                if detail:
                    lines.append(f'• {detail}')

    for key, heading in (
        ('certifications', 'CERTIFICATIONS'),
        ('achievements', 'ACHIEVEMENTS'),
        ('languages', 'LANGUAGES'),
    ):
        if data.get(key):
            lines += ['', heading]
            lines.extend(f'• {x}' for x in data[key] if x)

    return '\n'.join(lines).strip()

def _add_resume_heading(document, text):
    from docx.shared import Pt
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    p = document.add_paragraph()
    p.paragraph_format.space_before = Pt(9)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text.upper())
    run.bold = True
    run.font.size = Pt(10.5)
    run.font.name = 'Arial'
    pPr = p._p.get_or_add_pPr()
    pbdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '6')
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), '666666')
    pbdr.append(bottom)
    pPr.append(pbdr)
    return p


def _add_resume_body(document, text, bold=False, italic=False, size=9.5, space_after=2):
    from docx.shared import Pt
    p = document.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.0
    run = p.add_run(str(text or ''))
    run.font.name = 'Arial'
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    return p


def _add_resume_bullet(document, text):
    from docx.shared import Pt
    p = document.add_paragraph(style='List Bullet')
    p.paragraph_format.left_indent = Pt(13)
    p.paragraph_format.first_line_indent = Pt(-5)
    p.paragraph_format.space_after = Pt(1.5)
    p.paragraph_format.line_spacing = 1.0
    r = p.add_run(str(text or ''))
    r.font.name = 'Arial'
    r.font.size = Pt(9.2)
    return p


def build_professional_resume_docx(data):
    """Create a clean, one-column, ATS-readable resume DOCX."""
    from docx.shared import Inches, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    data = _normalize_ai_resume(data) or {}
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.55)
    section.bottom_margin = Inches(0.55)
    section.left_margin = Inches(0.65)
    section.right_margin = Inches(0.65)

    normal = document.styles['Normal']
    normal.font.name = 'Arial'
    normal.font.size = Pt(9.5)
    normal.paragraph_format.space_after = Pt(2)
    normal.paragraph_format.line_spacing = 1.0

    # Header
    if data.get('name'):
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(1)
        r = p.add_run(data['name'])
        r.bold = True
        r.font.name = 'Arial'
        r.font.size = Pt(18)

    if data.get('headline'):
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(data['headline'])
        r.font.name = 'Arial'
        r.font.size = Pt(10.5)
        r.bold = True

    if data.get('contact'):
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(5)
        r = p.add_run(' | '.join(data['contact']))
        r.font.name = 'Arial'
        r.font.size = Pt(8.8)

    if data.get('summary'):
        _add_resume_heading(document, 'Professional Summary')
        _add_resume_body(document, data['summary'])

    if data.get('skills'):
        _add_resume_heading(document, 'Skills')
        for category, values in data['skills'].items():
            if not values:
                continue
            p = document.add_paragraph()
            p.paragraph_format.space_after = Pt(1.5)
            r = p.add_run(f'{category}: ')
            r.bold = True
            r.font.name = 'Arial'
            r.font.size = Pt(9.2)
            r2 = p.add_run(', '.join(values))
            r2.font.name = 'Arial'
            r2.font.size = Pt(9.2)

    if data.get('experience'):
        _add_resume_heading(document, 'Experience')
        for item in data['experience']:
            p = document.add_paragraph()
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.keep_with_next = True
            if item.get('title'):
                r = p.add_run(item['title'])
                r.bold = True
            if item.get('company'):
                r = p.add_run((' | ' if item.get('title') else '') + item['company'])
                r.bold = True
            for run in p.runs:
                run.font.name = 'Arial'; run.font.size = Pt(9.5)
            meta = ' | '.join(x for x in [item.get('location'), item.get('dates')] if x)
            if meta:
                _add_resume_body(document, meta, italic=True, size=8.8, space_after=1)
            for bullet in item.get('bullets', []):
                _add_resume_bullet(document, bullet)

    if data.get('projects'):
        _add_resume_heading(document, 'Projects')
        for item in data['projects']:
            p = document.add_paragraph()
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.keep_with_next = True
            r = p.add_run(item.get('name') or 'Project')
            r.bold = True; r.font.name = 'Arial'; r.font.size = Pt(9.5)
            if item.get('technologies'):
                r2 = p.add_run(' | ' + ', '.join(item['technologies']))
                r2.font.name = 'Arial'; r2.font.size = Pt(8.8)
            if item.get('description'):
                _add_resume_body(document, item['description'], size=9.0, space_after=1)
            for bullet in item.get('bullets', []):
                _add_resume_bullet(document, bullet)

    if data.get('education'):
        _add_resume_heading(document, 'Education')
        for item in data['education']:
            p = document.add_paragraph()
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.keep_with_next = True
            r = p.add_run(item.get('degree') or 'Qualification')
            r.bold = True; r.font.name = 'Arial'; r.font.size = Pt(9.5)
            meta = ' | '.join(x for x in [item.get('institution'), item.get('location'), item.get('dates')] if x)
            if meta:
                r2 = p.add_run(' | ' + meta)
                r2.font.name = 'Arial'; r2.font.size = Pt(8.8)
            for detail in item.get('details', []):
                _add_resume_bullet(document, detail)

    for key, heading in [('certifications','Certifications'),('achievements','Achievements'),('languages','Languages')]:
        if data.get(key):
            _add_resume_heading(document, heading)
            for value in data[key]:
                _add_resume_bullet(document, value)

    return document

def build_jd_gaps_from_result(result, jd_text):

    if not jd_text:
        return []

    gaps = []

    missing_keywords = (
        result.get('missing_keywords') or []
    )

    for keyword in missing_keywords[:15]:

        keyword = str(keyword).strip()

        if not keyword:
            continue

        lower = keyword.lower()

        # Determine requirement type
        if any(word in lower for word in [
            'experience',
            'candidate',
            'ability',
            'team',
            'company',
            'working',
            'knowledge',
            'strong',
            'years',
            'role'
        ]):
            gap_type = 'Requirement'

        elif any(word in lower for word in [
            'python',
            'java',
            'javascript',
            'typescript',
            'flutter',
            'django',
            'flask',
            'laravel',
            'mysql',
            'postgresql',
            'postgres',
            'sql',
            'mongodb',
            'docker',
            'aws',
            'azure',
            'git',
            'opencv',
            'api',
            'database',
            'framework',
            'machine learning',
            'data'
        ]):
            gap_type = 'Technical skill'

        else:
            gap_type = 'Keyword / concept'

        gaps.append({
            'keyword': keyword,

            'type': gap_type,

            'action': (
                f'Review whether you genuinely have experience '
                f'with "{keyword}". If yes, add it to the most '
                f'relevant Skills, Project, or Experience section '
                f'and describe where you used it. Do not add it '
                f'if you do not.'
            )
        })

    return gaps

def _file_label(resume):
    """'resumes/5/My_CV.pdf' -> 'My_CV.pdf'"""
    return os.path.basename(resume.file_path or "") or f"Resume {resume.resume_id}"

def bullet_rewriter(request):
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "Please sign in to continue.")
        return redirect("login")
    versions = (ResumeVersion.objects
                .filter(versions__user_id=user_id)
                .select_related("versions")          # 'versions' is the Resume FK
                .order_by("-created_at"))

    version_options = []
    for v in versions:
        label = f"{_file_label(v.versions)} · {v.created_at:%d %b %Y}"
        if v.version_number > 1:
            label += f" (v{v.version_number})"
        version_options.append({"id": v.version_id, "label": label})

    results = []
    bullets_text = ""
    selected_id = request.POST.get("version_id") or request.GET.get("version_id") or ""

    # Preselect the latest resume on first visit
    if not selected_id and version_options:
        selected_id = str(version_options[0]["id"])

    if request.method == "GET" and selected_id:
        chosen = versions.filter(pk=selected_id).first()
        if chosen:
            bullets_text = "\n".join(extract_bullets(chosen.content_snapshot))
            if not bullets_text:
                messages.info(request, "We couldn't detect bullet points in this resume. You can type them below.")

    if request.method == "POST":
        bullets_text = request.POST.get("bullets", "")
        version = get_object_or_404(versions, pk=request.POST.get("version_id"))
        bullets = [b.strip(" -•\t") for b in bullets_text.splitlines() if b.strip()]

        if not bullets:
            messages.error(request, "Please enter at least one bullet point.")
        elif len(bullets) > 10:
            messages.error(request, "Maximum 10 bullet points at a time.")
        else:
            try:
                rewritten = rewrite_bullets(bullets)
            except BulletRewriteError as e:
                messages.error(request, str(e))
            else:
                results = BulletRewrite.objects.bulk_create([
                    BulletRewrite(version=version, original_text=o, rewritten_text=r)
                    for o, r in zip(bullets, rewritten)
                ])

    history_qs = (BulletRewrite.objects
                  .filter(version__versions__user_id=user_id)
                  .select_related("version__versions")[:])
    history = [{
        "original": h.original_text,
        "rewritten": h.rewritten_text,
        "file": _file_label(h.version.versions),
        "created_at": h.created_at,
    } for h in history_qs]

    return render(request, "dashboard_view/user/bullet_rewriter.html", {
        "version_options": version_options,
        "results": results,
        "history": history,
        "bullets_text": bullets_text,
        "selected_id": str(selected_id),
    })

