import re
import string
from collections import Counter
from io import BytesIO

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import docx as docx_lib
except ImportError:
    docx_lib = None


# ---------------------------------------------------------------------------
# Image-detection thresholds
# ---------------------------------------------------------------------------
MIN_READABLE_WORDS = 40         # below this, the file is treated as unreadable by an ATS
SIGNIFICANT_IMAGE_RATIO = 0.05  # an image covering >=5% of a page is not just a logo/icon
IMAGE_HEAVY_RATIO = 0.25        # >=25% of the page covered by images
MOSTLY_IMAGE_RATIO = 0.50       # >=50% of the page covered by images
MIN_WORDS_PER_PAGE = 150        # text density expected from a real resume page

CAP_IMAGE_ONLY = 10             # max ATS score for image-only / no-text files
CAP_MOSTLY_IMAGE = 30           # max ATS score for mostly-image files

section_keywords = {
    'contact': [
        r'@',
        r'\bphone\b',
        r'\bmobile\b',
        r'\bemail\b',
        r'\blinkedin\b',
        r'\bgithub\b',
        r'\bportfolio\b',
        r'\+?\d[\d\s().-]{7,}\d'
    ],

    'summary': [
        r'\bsummary\b',
        r'\bprofessional summary\b',
        r'\bcareer summary\b',
        r'\bobjective\b',
        r'\bprofile\b',
        r'\babout me\b'
    ],

    'experience': [
        r'\bexperience\b',
        r'\bwork experience\b',
        r'\bprofessional experience\b',
        r'\bemployment\b',
        r'\bwork history\b'
    ],

    'education': [
        r'\beducation\b',
        r'\bacademic\b',
        r'\bdegree\b',
        r'\bqualification\b'
    ],

    'skills': [
        r'\bskills\b',
        r'\btechnical skills\b',
        r'\bcore skills\b',
        r'\bcompetencies\b',
        r'\btechnologies\b',
        r'\btechnical expertise\b'
    ],

    'projects': [
        r'\bprojects\b',
        r'\bpersonal projects\b',
        r'\bacademic projects\b',
        r'\bkey projects\b'
    ],

    'certifications': [
        r'\bcertifications?\b',
        r'\blicenses?\b',
        r'\bcertificates?\b'
    ],

    'achievements': [
        r'\bachievements?\b',
        r'\bawards?\b',
        r'\bhonors?\b'
    ],

    'additional': [
        r'\blanguages?\b',
        r'\binterests?\b',
        r'\bactivities\b',
        r'\bvolunteer\b'
    ]
}

technical_skills = [
    'python', 'java', 'c', 'c++', 'c#',
    'kotlin', 'dart', 'flutter', 'android', 'django',
    'flask', 'laravel', 'php', 'spring', 'spring boot',

    'mysql', 'postgresql', 'postgres', 'mongodb', 'oracle', 'sql',

    'html', 'css', 'javascript', 'typescript', 'react', 'reactjs', 'node', 'nodejs',

    'git', 'github', 'docker', 'postman',

    'machine learning', 'deep learning', 'artificial intelligence', 'data science', 'opencv', 'computer vision',

    'rest api', 'restful api', 'api',

    'data structures', 'algorithms', 'object oriented programming', 'oops', 'dbms', 'database', 'system design'
]
  
action_verbs = {
    'led', 'managed', 'built', 'developed', 'designed', 'implemented', 'improved', 'increased', 'reduced', 'created',
    'launched', 'optimized', 'optimised', 'automated', 'delivered', 'drove', 'owned', 'architected',
    'streamlined', 'mentored', 'negotiated', 'analyzed', 'analysed', 'coordinated', 'executed',
    'spearheaded', 'scaled', 'integrated', 'deployed', 'tested', 'debugged', 'configured', 'migrated',
    'refactored', 'engineered', 'programmed', 'maintained', 'implemented', 'validated', 'monitored'
}

generic_phrases = [
    'hardworking', 'hard working', 'quick learner', 'team player',
    'self motivated', 'self-motivated', 'punctual', 'honest', 'dedicated', 'passionate individual',
    'positive attitude', 'good communication skills', 'excellent communication skills',
    'seeking a challenging position', 'seeking challenging opportunities', 'looking for a challenging opportunity',
    'looking for a challenging position', 'work well under pressure', 'ability to work in a team',
]

keyword_aliases = {
    'postgres': 'postgresql',
    'postgresql': 'postgresql',

    'ml': 'machine learning',
    'machine-learning': 'machine learning',

    'ai': 'artificial intelligence',

    'js': 'javascript', 'javascript': 'javascript',

    'ts': 'typescript',

    'reactjs': 'react', 'react.js': 'react',

    'nodejs': 'node', 'node.js': 'node',

    'restful api': 'rest api', 'restful apis': 'rest api',

    'rest apis': 'rest api',

    'object-oriented programming': 'object oriented programming',
    'object oriented programming': 'object oriented programming',

    'data-structures': 'data structures', 'data structures': 'data structures',

    'c sharp': 'c#', 'c-sharp': 'c#'
}

stopwords = set("""
a about above after again against all am an and any are aren't as at be because been
before being below between both but by can't cannot could couldn't did didn't do does
doesn't doing don't down during each few for from further had hadn't has hasn't have
haven't having he he'd he'll he's her here here's hers herself him himself his how
how's i i'd i'll i'm i've if in into is isn't it it's its itself let's me more most
mustn't my myself no nor not of off on once only or other ought our ours ourselves out
over own same shan't she she'd she'll she's should shouldn't so some such than that
that's the their theirs them themselves then there there's these they they'd they'll
they're they've this those through to too under until up very was wasn't we we'd
we'll we're we've were weren't what what's when when's where where's which while who
who's whom why why's with won't would wouldn't you you'd you'll you're you've your
yours yourself yourselves using use used within years year strong looking seeking
job role team work company across ability including etc will able
""".split())



def _empty_meta():
    return {
        'page_count': 1,
        'image_count': 0,
        'significant_images': 0,
        'image_area_ratio': 0.0,
        'is_image_file': False,
    }


# extract text (+ image statistics) from pdf
def extract_text_from_pdf(file_obj):
    if not pdfplumber:
        raise RuntimeError("pdfplumber is not installed (pip install pdfplumber)")

    text_parts = []
    has_tables = False
    meta = _empty_meta()
    page_ratios = []

    with pdfplumber.open(file_obj) as pdf:
        meta['page_count'] = max(len(pdf.pages), 1)

        for page in pdf.pages:
            page_text = page.extract_text() or ''
            text_parts.append(page_text)
            if not has_tables and page.find_tables():
                has_tables = True

            page_w, page_h = float(page.width), float(page.height)
            page_area = (page_w * page_h) or 1.0
            covered = 0.0

            for img in page.images:
                x0, x1 = max(img['x0'], 0), min(img['x1'], page_w)
                top, bottom = max(img['top'], 0), min(img['bottom'], page_h)
                area = max(0.0, x1 - x0) * max(0.0, bottom - top)
                covered += area
                meta['image_count'] += 1
                if area / page_area >= SIGNIFICANT_IMAGE_RATIO:
                    meta['significant_images'] += 1

            page_ratios.append(min(1.0, covered / page_area))

    if page_ratios:
        meta['image_area_ratio'] = round(sum(page_ratios) / len(page_ratios), 3)

    return '\n'.join(text_parts), has_tables, meta


# extract text (+ image statistics) from word document
def extract_text_from_docx(file_obj):
    if not docx_lib:
        raise RuntimeError("python-docx is not installed (pip install python-docx)")

    document = docx_lib.Document(file_obj)
    paragraphs = [p.text for p in document.paragraphs]
    has_tables = len(document.tables) > 0
    meta = _empty_meta()

    try:
        section = document.sections[0]
        page_area = float((section.page_width or 7772400) * (section.page_height or 10058400))
        covered = 0.0
        # every inline or floating picture has a <wp:extent cx= cy=> (EMU)
        for ext in document.element.body.xpath('.//wp:extent'):
            area = float(ext.get('cx', 0)) * float(ext.get('cy', 0))
            covered += area
            meta['image_count'] += 1
            if area / page_area >= SIGNIFICANT_IMAGE_RATIO:
                meta['significant_images'] += 1
        meta['image_area_ratio'] = round(min(1.0, covered / page_area), 3)
    except Exception:
        pass  # image stats are best-effort; never block text extraction

    return '\n'.join(paragraphs), has_tables, meta


# an uploaded picture (jpg/png) has no machine-readable text at all
def extract_text_from_image(_file_obj):
    meta = _empty_meta()
    meta.update(image_count=1, significant_images=1, image_area_ratio=1.0, is_image_file=True)
    return '', False, meta


# extract from raw bytes of an uploaded file -> (text, has_tables, meta)
def extract_text(files_bytes, file_type):
    stream = BytesIO(files_bytes)

    if file_type == 'pdf':
        return extract_text_from_pdf(stream)
    if file_type == 'docx':
        return extract_text_from_docx(stream)
    if file_type == 'image':
        return extract_text_from_image(stream)

    raise ValueError(f"Unsupported file type: {file_type}")


# ---------------------------------------------------------------------------
# Image / parseability assessment
# ---------------------------------------------------------------------------
def assess_image_content(text, meta):
    """Decide how badly images hurt ATS readability.

    Returns dict:
      image_based    - True when the ATS can't really read the file
      score_cap      - hard ceiling for the final ATS score (100 = no cap)
      penalty        - points deducted from the formatting score
      warnings       - human-readable explanations
    """
    meta = meta or _empty_meta()
    words = text.split()
    word_count = len(words)
    pages = max(meta.get('page_count', 1), 1)
    words_per_page = word_count / pages
    ratio = meta.get('image_area_ratio', 0.0)
    significant = meta.get('significant_images', 0)

    result = {'image_based': False, 'score_cap': 100, 'penalty': 0, 'warnings': []}

    # 1) No usable text: scanned page, screenshot, or a jpg/png upload
    if meta.get('is_image_file') or word_count < MIN_READABLE_WORDS:
        result['image_based'] = True
        result['score_cap'] = CAP_IMAGE_ONLY
        result['warnings'].append(
            'No readable text found. This looks like a scanned or image-based resume. '
            'ATS software cannot read images, so it would see an empty resume. '
            'Export a text-based PDF or DOCX from your editor instead.'
        )
        return result

    # 2) Mostly image with a thin text layer (e.g. bad OCR layer over a scan)
    if ratio >= MOSTLY_IMAGE_RATIO and words_per_page < MIN_WORDS_PER_PAGE:
        result['image_based'] = True
        result['score_cap'] = CAP_MOSTLY_IMAGE
        result['warnings'].append(
            'Most of the page is covered by images and very little text is extractable. '
            'An ATS is likely to miss most of your content.'
        )
        return result

    # 3) Image-heavy but text is present: penalise, don't cap
    if ratio >= IMAGE_HEAVY_RATIO:
        result['penalty'] += 20
        result['warnings'].append(
            'A large part of the page is images. Content inside images is invisible to an ATS.'
        )
    if significant:
        result['penalty'] += min(20, 8 * significant)
        result['warnings'].append(
            f'{significant} large image(s) detected (photos, banners, or graphics). '
            'Remove them or make sure no important text is inside them.'
        )

    # 4) Garbled text layer (typical of poor OCR): few real words
    alpha_tokens = sum(1 for w in words if re.fullmatch(r"[A-Za-z][A-Za-z'.,;:()/&+#-]*", w))
    if word_count and alpha_tokens / word_count < 0.5:
        result['penalty'] += 15
        result['warnings'].append(
            'The extracted text looks garbled, which often means an OCR layer on a scanned document.'
        )

    result['penalty'] = min(result['penalty'], 40)
    return result

def detect_section(text):
    text_lower = text.lower()
    found, missing = [], []

    for section, patterns in section_keywords.items():
        if any(re.search(p, text_lower) for p in patterns):
            found.append(section)
        else:
            missing.append(section)

    return found, missing

def extract_section_text(text, section):
    #Try to extract the content belonging to a particular This is intentionally heuristic because PDF/DOCX text extraction does not always preserve the original layout.
    patterns = section_keywords.get(section, [])
    heading_pattern = (r'(?:' + '|'.join(patterns) + r')')

    other_sections = []
    for key, values in section_keywords.items():
        if key != section:
            other_sections.extend(values)
    next_heading = ( r'|'.join(other_sections) )

    pattern = re.compile( heading_pattern + r'(.*?)(?='
        + next_heading + r'|$)', re.IGNORECASE | re.DOTALL )

    match = pattern.search(text)
    if not match:
        return ""

    return match.group(1).strip()

"""
    Scores the quality and usefulness of resume sections,
    rather than only checking whether headings exist.
    """
def score_section_quality(text):
    text_lower = text.lower()
    scores = {}
    details = {}

    #contact section
    contact_score = 0
    contact_details = []

    if re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', text):
        contact_score += 25
        contact_details.append( 'Email address detected.' )
    else:
        contact_details.append( 'Email address not detected.' )

    if re.search(r'\+?\d[\d\s().-]{7,}\d', text):
        contact_score += 25
        contact_details.append( 'Phone number detected.')
    else:
        contact_details.append('Phone number not detected.' )

    if re.search(r'linkedin\.com', text_lower):
        contact_score += 20
        contact_details.append('LinkedIn profile detected.' )

    if re.search(r'github\.com', text_lower):
        contact_score += 15
        contact_details.append( 'LinkedIn profile detected.' )

    if re.search(r'portfolio|website', text_lower):
        contact_score += 15
        contact_details.append('GitHub profile detected.' )        

    scores['contact'] = min(contact_score, 100)
    details["contact"] = contact_details

    #summary
    summary_score = 0
    summary_details = []
    summary_match = re.search(
        r'(summary|objective|profile)(.*?)(experience|education|skills|projects|$)',
        text_lower,
        re.DOTALL
    )
    if summary_match:
        summary_text = summary_match.group(2).strip()
        words = summary_text.split()

        if 30 <= len(words) <= 100:
            summary_score += 40
            summary_details.append('Summary has an appropriate length.' )

        elif 15 <= len(words) <= 120:
            summary_score += 25
            summary_details.append('Summary exists but its length could be improved.' )
        else:
            summary_details.append('Summary is too short or too long.' )

        # Technical keywords indicate that the summary is describing actual professional skills.
        tech_hits = sum(1 for item in technical_skills if item in summary_text)
        summary_score += min(tech_hits * 10, 30)

        if tech_hits:
            summary_details.append(f'{tech_hits} technical skill(s) detected in summary.')
        else:
            summary_details.append('Summary contains little technical information.')

        # Avoid extremely generic summaries
        generic_terms = [ 'hardworking', 'punctual', 'honest', 'quick learner', 'seeking a challenging position' ]
        generic_hits = sum(1 for term in generic_terms if term in summary_text)
        if generic_hits:
            summary_score -= min(generic_hits * 10, 30)
            summary_details.append(f'{generic_hits} generic phrase(s) detected.')
    else:
        summary_details.append('No professional summary detected.')

    scores["summary"] = max(0, min(summary_score, 100))
    details["summary"] = summary_details

    #skills
    skills_score = 0
    skills_details = []
    skill_hits = []

    for skill in technical_skills:
        pattern = ( r'(?<!\w)' + re.escape(skill) + r'(?!\w)')
        if re.search(pattern,text_lower ):
            skill_hits.append(skill)
    skill_count = len(set(skill_hits))

    if skill_count >= 12:
        skills_score = 100
    elif skill_count >= 9:
        skills_score = 90
    elif skill_count >= 7:
        skills_score = 80
    elif skill_count >= 5:
        skills_score = 70
    elif skill_count >= 3:
        skills_score = 50
    elif skill_count >= 1:
        skills_score = 30
    else:
        skills_score = 0

    if skill_count:
        skills_details.append(f'{skill_count} technical skill(s) detected.')
    else:
        skills_details.append('No recognized technical skills detected.')
    scores["skills"] = skills_score
    details["skills"] = skills_details

    #projects
    project_score = 0
    project_details = []

    project_text = extract_section_text(text, 'projects' )

    if project_text:
        project_words = len(project_text.split())

        if project_words >= 150:
            project_score += 40
        elif project_words >= 100:
            project_score += 30
        elif project_words >= 50:
            project_score += 20
        elif project_words >= 20:
            project_score = 10        

        project_action_hits = sum(1 for verb in action_verbs if re.search(r'\b' + re.escape(verb) + r'\b', project_text))

        project_score += min(project_action_hits * 6, 30)

        #technology usage
        project_tech_hits = sum(1 for skill in technical_skills if re.search(r'\b' + re.escape(skill) + r'\b', project_text))
        project_score += min(project_tech_hits * 5, 30)

        if project_action_hits:
            project_details.append(f'{project_action_hits} action-oriented term(s) detected.')
        else:
            project_details.append('Projects do not contain many action-oriented descriptions.')

        if project_tech_hits:
            project_details.append(f'{project_tech_hits} technology/skill reference(s) detected.')
        else:
            project_details.append('Projects contain little technical information.')

    else:
        project_details.append('No projects section detected.')

    scores["projects"] = min(project_score, 100)
    details["projects"] = project_details

    #education
    education_score = 0
    education_details = []   

    education_text = extract_section_text(text,'education' )

    if education_text:
        degree_patterns = [
                r'\bbca\b',
                r'\bmca\b',
                r'\bb\.?tech\b',
                r'\bm\.?tech\b',
                r'\bbachelor\b',
                r'\bmaster\b',
                r'\bdiploma\b'
            ]
        degree_found = any(re.search(pattern,) for pattern in degree_patterns)

        if degree_found:
            education_score += 50
            education_details.append('Degree/qualification detected.')
        else:
            education_details.append('Degree/qualification not clearly detected.')

        if re.search(r'\b20\d{2}\b', text_lower):
            education_score += 25
            education_details.append('Education year detected.')

        if re.search(r'\b(gpa|cgpa|percentage|percent|%)\b', text_lower):
            education_score += 15
            education_details.append('Academic performance information detected.')

        if re.search(r'\buniversity\b|\bcollege\b|\binstitute\b', education_text.lower()):
            education_score += 10
            education_details.append('Institution information detected.')

    else:
        education_details.append('No education section detected.')

    scores["education"] = min(education_score, 100)
    details["education"] = education_details

    #experience
    experience_score = 0
    experience_details = []

    experience_text = extract_section_text(text,'experience')
    if experience_text:
        action_hits = sum(1 for verb in action_verbs if re.search(r'\b' + re.escape(verb) + r'\b', experience_text))
        experience_score += min(action_hits * 7, 40)
        number_hits = len(re.findall(r'\b\d+(?:\.\d+)?%?\b', experience_text))
        experience_score += min(number_hits * 5, 30)

        experience_words = len(experience_text.split())

        if experience_words >= 150:
            experience_score += 30
        elif experience_words >= 100:
            experience_score += 20
        elif experience_words >= 50:
            experience_score += 10

        if action_hits:
            experience_details.append(f'{action_hits} action verb(s) detected.')
        else:
            experience_details.append('Experience descriptions lack strong action verbs.')

        if number_hits:
            experience_details.append(f'{number_hits} numeric/quantified value(s) detected.')
        else:
            experience_details.append('No quantified achievements detected.')
    else:
        experience_details.append('No professional experience section detected.')

    scores["experience"] = min(experience_score, 100)
    details["experience"] = experience_details

    #optional sections
    certifications_text = extract_section_text(text, "certification")
    if certifications_text:
        scores["certification"] = 100
        details["certifications"] = 'Certification section detected.'
    else:
        scores["certification"] = 0
        details["certifications"] = 'No certification section detected.'

    achievement_text = extract_section_text(text, "achievements")
    if achievement_text:
        scores['achievements'] = 100
        details['achievements'] = ['Achievements section detected.']
    else:
        scores['achievements'] = 0
        details['achievements'] = ['No achievements section detected.']
    

    #overall section quality
    weights = {'contact': 0.10, 'summary': 0.10, 'skills': 0.20,
            'projects': 0.20, 'education': 0.15, 'experience': 0.25,}
    weighted_score = sum(scores.get(section,0) * weight for section, weight in weights.items())

    return (round(weighted_score, 2), scores, details)


bullet_re = re.compile(r'^[•\-*\u2022\u25CF]')

def score_formatting(text, has_tables, image_penalty=0):
    score = 100.0
    word_count = len(text.split())

    if word_count < 150:
        score -= 25
    elif word_count > 1500:
        score -= 15

    if has_tables:
        score -= 20

    lines = [str(l).strip() for l in text.splitlines() if l and str(l).strip()]

    if lines:
        bullet_lines = sum(1 for l in lines if bullet_re.match(l))
        if bullet_lines / len(lines) < 0.05:
            score -= 10

    printable = sum(1 for c in text if c in string.printable)
    ratio = printable / max(len(text), 1)

    if ratio < 0.9:
        score -= 20

    score -= image_penalty

    return max(0.0, min(100.0, round(score, 2)))

"""
    Evaluate whether resume bullets contain useful,
    action-oriented and technical information.
    """
def score_bullet_quality(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    bullets = [line for line in lines if bullet_re.match(line)]

    # No bullets. Do not give zero because some resumes use paragraphs, but still penalize the structure.
    if not bullets:
        return 30.0
    good_bullets = 0
    for bullet in bullets:
        clean = re.sub(r'^[•\-*\u2022\u25CF]\s*','',bullet)
        words = clean.split()
        if len(words) < 6:
            continue
        bullet_score = 0
        #action verb
        first_word = (words[0].lower().strip(string.punctuation))
        if first_word in action_verbs:
            bullet_score += 1

        #technology
        clean_lower = clean.lower()
        if any(skill in clean_lower for skill in technical_skills):
            bullet_score += 1

        #quantified result
        if re.search(r'\b\d+(?:\.\d+)?%?\b', clean):
            bullet_score += 1

        #reasonable length
        if 10 <= len(words) <= 35:
            bullet_score += 1

        #good bullet
        if bullet_score >= 2:
            good_bullets += 1
    return round(good_bullets/ len(bullets) * 100, 2)

def content_quality_score(text):
    """Evaluate overall resume content quality. This prevents a resume from getting a high score merely because it contains all the standard headings."""

    if not text.strip():
        return 0.0
    score = 100.0
    text_lower = text.lower()
    words = text.split()
    word_count = len(words)

    #resume length
    if word_count < 150:
        score -= 25
    elif word_count < 250:
        score -= 10
    elif word_count > 1500:
        score -= 15

    #generic filler
    generic_count = sum(1 for phrase in generic_phrases if phrase in text_lower)
    score -= min(generic_count * 5,20)

    #action verbs
    action_count = sum(1 for verb in action_verbs
        if re.search( r'\b' + re.escape(verb) + r'\b', text_lower))
    if action_count == 0:
        score -= 20
    elif action_count < 3:
        score -= 10
    elif action_count >= 8:
        score += 5

    #technical content
    technical_count = 0
    for skill in technical_skills:
        if re.search( r'(?<!\w)' + re.escape(skill) + r'(?!\w)', text_lower ):
            technical_count += 1

    if technical_count == 0:
        score -= 15
    elif technical_count < 3:
        score -= 5
    elif technical_count >= 8:
        score += 5

    #quantified achievements
    numbers = re.findall(r'\b\d+(?:\.\d+)?%?\b', text)
    if len(numbers) == 0:
        score -= 10
    elif len(numbers) >= 5:
        score += 5

    #first-person language
    first_person_count = len( re.findall( r'\b(i|me|my|myself)\b', text_lower))
    if first_person_count > 5:
        score -= 10

    #repeated words
    repeated_words = re.findall(r'\b(\w+)\s+\1\b', text_lower)
    if repeated_words:
        score -= 5
    return max(0.0,min( 100.0, round(score, 2)))

def normalize_keyword(keyword):
    #Normalize common technology aliases.
    keyword = keyword.lower().strip()
    keyword = re.sub(r'\s+', ' ', keyword)
    return keyword_aliases.get(keyword,keyword )

def extract_keywords(text, top_n=30):
    words = re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{1,}", text.lower())
    words = [w.strip() for w in words if len(w) > 2 and w not in stopwords]
    return [w for w, _ in Counter(words).most_common(top_n)]

#JD keyword matching
def keyword_exists(keyword, text):
    normalized_text = text.lower()
    keyword = normalize_keyword(keyword)

    if keyword in normalize_keyword:
        return True

    aliases = [alias for alias, canonical in keyword_aliases.items() if canonical == keyword]
    for alias in aliases:
        if alias in normalized_text:
            return True
    return False

def score_keyword_match(resume_text, jd_text):
    if not jd_text or jd_text.strip():
        return 0.0, []

    jd_lower = jd_text.lower()
    technical_jd_keywords = []

    for skill in technical_skills:
        if keyword_exists(skill, jd_lower):
            technical_jd_keywords.append(normalize_keyword(skill))

    #extract general JD keywords
    general_keywords = extract_keywords(jd_text, top_n=30)

    # Remove very generic terms
    generic_jd_terms = {
        'experience', 'work', 'team', 'company', 'role', 'candidate', 'ability', 'skills',
        'job', 'using', 'including', 'knowledge', 'strong', 'good', 'working', 'years' }

    general_keywords = [keyword for keyword in general_keywords if keyword not in generic_jd_terms]

    all_keywords = []
    for keyword in technical_jd_keywords:
        if keyword not in all_keywords:
            all_keywords.append(keyword)

    for keyword in general_keywords:
        if keyword not in all_keywords:
            all_keywords.append(keyword)

    all_keywords = all_keywords[:25]
    if not all_keywords:
        return 0.0, []

    matched = []
    missing = []
    for keyword in all_keywords:
        if keyword_exists(keyword, resume_text):
            matched.append(keyword)
        else:
            missing.append(keyword)
    match_pct = round(len(matched) / len(all_keywords) * 100, 2)

    return (match_pct, missing[:15])

def baselinekeyword_score(text):
    # no text => no evidence of anything; don't hand out the 40-point baseline
    if not text.strip():
        return 0.0

    text_lower = text.lower()
    score = 0.0
    skill_hits = 0

    #technical skills
    for skill in technical_skills:
        if re.search( r'(?<!\w)' + re.escape(skill) + r'(?!\w)', text_lower ):
            skill_hits += 1

    score += min( skill_hits * 5, 35 )

    #action verb
    action_hits = sum( 1 for verb in action_verbs
        if re.search(r'\b' + re.escape(verb) + r'\b', text_lower ))
    score += min(action_hits * 4, 25)

    #quantified results
    number_hits = len(re.findall(r'\b\d+(?:\.\d+)?%?\b', text))
    score += min(number_hits * 3,20)

    #projects or experience
    found_sections, _ = detect_section(text )
    if 'projects' in found_sections:
        score += 10
    if 'experience' in found_sections:
        score += 10
    return round(min(score, 100),2)

#grammar and passive voice check
passive_re = re.compile(r'\b(is|are|was|were|be|been|being)\s+\w+ed\b', re.IGNORECASE)

def detect_passive_voice(text):
    sentences = re.split(r'(?<=[.!?])\s+', text)
    flags = [s.strip() for s in sentences if passive_re.search(s)]

    return flags[:10]

def detect_grammar_issues(text):
    issues = []
    if re.search(r'\b(\w+)\s+\1\b', text, re.IGNORECASE):
        issues.append('Possible repeated word detected.')

    long_sentences = [s for s in re.split(r'(?<=[.!?])\s+', text) if len(s.split()) > 40]

    if long_sentences:
        issues.append(f'{len(long_sentences)} sentence(s) longer than 40 words — consider shortening.')

    # two or more consecutive spaces (the old pattern ' +' matched every single space)
    if re.search(r' {2,}', text):
        issues.append('Inconsistent spacing detected (double spaces).')

    return issues

#Generate human-readable ATS recommendations.
def generate_recommendations( section_details,section_scores, content_score, bullet_score, formatting_score,
    keyword_score, missing_sections, missing_keywords, grammar_issues, passive_voice_flags, jd_provided ):

    recommendations = []
    for section in ["summary", "skills", "projects", "experience", "education"]:
        score = section_scores.get(section, 0)
        if score < 400:
            recommendations.append(f'Improve the {section} section. '
                'It exists but does not contain enough useful or '
                'relevant information.')
            
    important_sections = ["summary", "skills", "projects", "education"]
    for section in important_sections:
        if section in missing_sections:
            recommendations.append(f'Consider adding a {section} section '
                'if it is relevant to your background.')
            
    if content_score < 50:
        recommendations.append(
            'Overall resume content is weak. Add specific technical '
            'details, accomplishments, project contributions and '
            'measurable results instead of generic statements.'
        )

    if formatting_score < 60:
        recommendations.append(
            'Improve ATS-friendly formatting. Avoid excessive tables, '
            'graphics and formatting that can interfere with text extraction.'
        )

    if jd_provided:
        if keyword_score < 50:
            recommendations.append(
                'Your resume has a relatively low keyword match with '
                'the supplied job description. Add relevant skills and '
                'technologies only when you genuinely have them.'
            )
        if missing_keywords:
            recommendations.append(
                'Review the missing job-description keywords and add '
                'the ones that accurately represent your experience.'
            )

    if grammar_issues:
        recommendations.append(
            'Review grammar and formatting issues detected in the resume.'
        )

    if passive_voice_flags:
        recommendations.append(
            'Some statements use passive voice. Rewrite them with '
            'stronger active verbs where appropriate.'
        )
    return recommendations[:10]


def compute_ats_score(resume_text, jd_text=None, has_tables=False, content_meta=None):

    """
    Main ATS scoring function.

    With JD:
        Formatting       15%
        Section quality  15%
        Content quality  20%
        JD keywords      35%
        Bullet quality   15%

    Without JD:
        Formatting       20%
        Section quality  20%
        Content quality  25%
        General relevance15%
        Bullet quality   20%
    """

    image_check = assess_image_content(resume_text, content_meta)

    found_sections, missing_sections = detect_section(resume_text)
    (section_score, section_details_score, section_details) = score_section_quality(resume_text)
    formatting_score = score_formatting(resume_text, has_tables, image_check['penalty'])

    content_score = content_quality_score(resume_text)
    bullet_score = score_bullet_quality(resume_text)


    if jd_text and jd_text.strip():
        keyword_score, missing_keywords = score_keyword_match(resume_text, jd_text)
        ats_score = round((formatting_score * 0.15) + (section_score * 0.15) + (content_score * 0.20) + 
                          (keyword_score * 0.35) + bullet_score * 0.15)
        
        jd_provided = True
    else:
        keyword_score = baselinekeyword_score(resume_text)
        missing_keywords = []
        ats_score = round( formatting_score * 0.20 + section_score * 0.20 + content_score * 0.25 +
            keyword_score * 0.15 + bullet_score * 0.20
        )

        jd_provided = False
    
    ats_score = min(ats_score, image_check['score_cap'])   # image-based files can never score well

    grammar_issues = detect_grammar_issues(resume_text)
    passive_voice_flags = detect_passive_voice(resume_text)

    recommendations = generate_recommendations(
        section_details, section_details_score, content_score, bullet_score, formatting_score,
        keyword_score, missing_sections, missing_keywords, grammar_issues, passive_voice_flags, jd_provided
    )




    return {
        'ats_score': ats_score,
        'formatting_score': formatting_score,
        'section_score': section_score,
        'content_score': content_score,
        'bullet_score': bullet_score,
        'keyword_match': keyword_score,

        'found_sections': found_sections,
        'missing_sections': missing_sections,

        'section_details': section_details_score,
        'section_quality_details': section_details,

        'missing_keywords': missing_keywords,

        'grammar_issues': grammar_issues,
        'passive_voice_flags': passive_voice_flags,
        'image_based': image_check['image_based'],
        'image_warnings': image_check['warnings'],

        "recommendations": recommendations
    }