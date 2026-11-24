# resume/templatetags/resume_extras.py
import os
from django import template

register = template.Library()


@register.filter
def file_name(path):
    """'resumes/5/My_CV.pdf' -> 'My_CV.pdf'"""
    return os.path.basename(path or "") or "Resume"