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


#extract text from pdf
def extract_text_from_pdf(file_obj):
    if not pdfplumber:
        raise RuntimeError("pdfplumber is not installed (pip install pdfplumber)")

    text_parts = []
    has_tables = False

    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ''
            text_parts.append(page_text)
            if not has_tables and page.find_tables():
                has_tables = True

    return '\n'.join(text_parts), has_tables

#extract text from word document
def extract_text_from_docx(file_obj):
    if not docx_lib:
            raise RuntimeError("python-docx is not installed (pip install python-docx)")

    document = docx_lib.Document(file_obj)
    paragraphs = [p.text for p in document.paragraphs]
    has_tables = len(document.tables) > 0
    return '\n'.join(paragraphs), has_tables

#extract raw bytes from uploaded file
def extract_text(files_bytes, file_type):
    stream = BytesIO(files_bytes)

    if file_type == 'pdf':
        return extract_text_from_pdf(stream)
    if file_type == 'docx':
        return extract_text_from_docx(stream)

    raise ValueError(f"Unsupported file type: {file_type}")


section_keywords = {
    'contact':[r'@', r'\bphone\b', r'\bemail\b', r'\blinkedin\b', r'\+?\d[\d\s().-]{7,}\d'],
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
    return round(len(found_section) / total*100, 2)

bullet_re = re.compile(r'^[•\-*\u2022\u25CF]')

def score_formatting(text, has_tables):
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

    if re.search(r' +',text):
        issues.append('Inconsistent spacing detected (double spaces).')

    return issues

def compute_ats_score(resume_text, jd_text=None, has_tables = False):
    found_sections, missing_sections = detect_section(resume_text)
    section_score = score_sections(found_sections)
    formatting_score = score_formatting(resume_text, has_tables)

    if jd_text:
        keyword_score, missing_keywords = score_keyword_match(resume_text, jd_text)
        w_format, w_section, w_keyword = 0.25, 0.25, 0.50

    else:
        keyword_score = baselinekeyword_score(resume_text)
        missing_keywords = []
        w_format, w_section, w_keyword = 0.35, 0.35, 0.30

    ats_score = round(formatting_score * w_format + section_score * w_section + keyword_score * w_keyword)

    return {
        'ats_score': ats_score,
        'formatting_score': formatting_score,
        'section_score': section_score,
        'keyword_match': keyword_score,
        'missing_keywords': missing_keywords,
        'missing_sections': missing_sections,
        'grammar_issues': detect_grammar_issues(resume_text),
        'passive_voice_flags': detect_passive_voice(resume_text)
    }