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


section_keywords = {
    'contact': [r'@', r'\bphone\b', r'\bemail\b', r'\blinkedin\b', r'\+?\d[\d\s().-]{7,}\d'],
    'summary': [r'\bsummary\b', r'\bobjective\b', r'\bprofile\b'],
    'experience': [r'\bexperience\b', r'\bemployment\b', r'\bwork history\b'],
    'education': [r'\beducation\b', r'\bacademic\b', r'\bdegree\b'],
    'skills': [r'\bskills\b', r'\bcompetencies\b', r'\btechnologies\b'],
}

def detect_section(text):
    text_lower = text.lower()
    found, missing = [], []

    for section, patterns in section_keywords.items():
        if any(re.search(p, text_lower) for p in patterns):
            found.append(section)
        else:
            missing.append(section)

    return found, missing

def score_sections(found_section):
    total = len(section_keywords)
    return round(len(found_section) / total * 100, 2)

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

action_verbs = {
    'led', 'managed', 'built', 'developed', 'designed', 'implemented', 'improved',
    'increased', 'reduced', 'created', 'launched', 'optimized', 'automated',
    'delivered', 'drove', 'owned', 'architected', 'streamlined', 'mentored',
    'negotiated', 'analyzed', 'coordinated', 'executed', 'spearheaded', 'scaled',
}

def extract_keywords(text, top_n=30):
    words = re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{1,}", text.lower())
    words = [w.strip() for w in words if len(w) > 2 and w not in stopwords]
    return [w for w, _ in Counter(words).most_common(top_n)]

def score_keyword_match(resume_text, jd_text):
    jd_keywords = extract_keywords(jd_text, top_n=25)
    resume_lower = resume_text.lower()

    if not jd_keywords:
        return 0.0, []

    matched = [kw for kw in jd_keywords if kw in resume_lower]
    missing = [kw for kw in jd_keywords if kw not in resume_lower]
    match_pct = round(len(matched) / len(jd_keywords) * 100, 2)

    return match_pct, missing[:15]

def baselinekeyword_score(text):
    # no text => no evidence of anything; don't hand out the 40-point baseline
    if not text.strip():
        return 0.0

    words = set(re.findall(r"[a-z]+", text.lower()))
    hits = len(words & action_verbs)

    return round(min(100.0, 40 + hits * 6), 2)

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

def compute_ats_score(resume_text, jd_text=None, has_tables=False, content_meta=None):
    image_check = assess_image_content(resume_text, content_meta)

    found_sections, missing_sections = detect_section(resume_text)
    section_score = score_sections(found_sections)
    formatting_score = score_formatting(resume_text, has_tables, image_check['penalty'])

    if jd_text:
        keyword_score, missing_keywords = score_keyword_match(resume_text, jd_text)
        w_format, w_section, w_keyword = 0.25, 0.25, 0.50
    else:
        keyword_score = baselinekeyword_score(resume_text)
        missing_keywords = []
        w_format, w_section, w_keyword = 0.35, 0.35, 0.30

    ats_score = round(formatting_score * w_format + section_score * w_section + keyword_score * w_keyword)
    ats_score = min(ats_score, image_check['score_cap'])   # image-based files can never score well

    return {
        'ats_score': ats_score,
        'formatting_score': formatting_score,
        'section_score': section_score,
        'keyword_match': keyword_score,
        'missing_keywords': missing_keywords,
        'missing_sections': missing_sections,
        'grammar_issues': detect_grammar_issues(resume_text),
        'passive_voice_flags': detect_passive_voice(resume_text),
        'image_based': image_check['image_based'],
        'image_warnings': image_check['warnings'],
    }