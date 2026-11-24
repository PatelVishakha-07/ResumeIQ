import json
import logging

from django.conf import settings
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

_client = None


class BulletRewriteError(Exception):
    """Raised when the AI call fails or returns unusable output."""


def _get_client():
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            raise BulletRewriteError("GEMINI_API_KEY is not configured.")
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


SYSTEM_PROMPT = """You are an expert resume writer and career coach.
Rewrite each resume bullet point so it is stronger and results-focused.

Rules:
- Start with a strong action verb (Led, Built, Reduced, Delivered, etc.).
- Keep the original meaning. NEVER invent numbers, tools, titles or achievements
  that are not in the original. If the original has no metric, do not add one.
- One line, at most 25 words. No first person, no trailing period.
- Do not use filler like "responsible for", "worked on", "helped with".

Return ONLY a JSON array of strings, the same length and order as the input."""


def rewrite_bullets(bullets):
    """Rewrite a list of bullets in ONE Gemini call. Returns a list of the same length."""
    if not bullets:
        return []

    prompt = "Input bullets (JSON array):\n" + json.dumps(bullets, ensure_ascii=False)

    try:
        response = _get_client().models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.4,
                response_mime_type="application/json",
            ),
        )
        rewritten = json.loads(response.text)
    except BulletRewriteError:
        raise
    except Exception as exc:
        logger.exception("Gemini bullet rewrite failed")
        raise BulletRewriteError("The AI service is unavailable. Please try again.") from exc

    if (
        not isinstance(rewritten, list)
        or len(rewritten) != len(bullets)
        or not all(isinstance(r, str) and r.strip() for r in rewritten)
    ):
        raise BulletRewriteError("The AI returned an unexpected response. Please try again.")

    return [r.strip() for r in rewritten]

import re

_BULLET_CHARS = "•●▪■◦○-–—*·"

def extract_bullets(text, limit=10):
    """Pull likely bullet points out of a resume's plain text."""
    if not text:
        return []

    bullets, seen = [], set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        has_marker = line[0] in _BULLET_CHARS
        line = line.lstrip(_BULLET_CHARS + " \t").strip()
        words = len(line.split())

        # Marked lines: accept 4+ words. Unmarked lines: need to look like a sentence.
        if has_marker:
            ok = words >= 4
        else:
            ok = 6 <= words <= 35 and not line.isupper() and "@" not in line and "|" not in line

        if ok and line.lower() not in seen:
            seen.add(line.lower())
            bullets.append(line)

    return bullets[:limit]

