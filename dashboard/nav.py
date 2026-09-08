# Single source of truth for the sidebar in each section.
# base.html + partials/sidebar.html render this, so the layout
# markup itself only has to exist once.

NAV = {
    "user": {
        "brand_sub": "Job Seeker Dashboard",
        "avatar_initial": "A",
        "avatar_name": "Aisha Rahman",
        "groups": [
            {
                "label": "Resume",
                "items": [
                    {"url_name": "dashboard:user_overview", "label": "Overview"},
                    {"url_name": "dashboard:user_upload", "label": "Upload & Parse"},
                    {"url_name": "dashboard:user_analysis", "label": "Resume Analysis"},
                    {"url_name": "dashboard:user_jd_match", "label": "JD Match & Roadmap"},
                    {"url_name": "dashboard:user_bullet_rewriter", "label": "Bullet Rewriter"},
                    {"url_name": "dashboard:user_skill_gap", "label": "Skill Gap Analysis"},
                    {"url_name": "dashboard:user_version_history", "label": "Version History"},
                ],
            },
            {
                "label": "Interview Prep",
                "items": [
                    {"url_name": "dashboard:user_question_generator", "label": "Question Generator"},
                    {"url_name": "dashboard:user_test_exam", "label": "Test / Exam"},
                    {"url_name": "dashboard:user_weak_areas", "label": "Weak Areas"},
                ],
            },
            {
                "label": "Output",
                "items": [
                    {"url_name": "dashboard:user_export", "label": "Export Documents"},
                    {"url_name": "dashboard:user_feedback", "label": "Feedback"},
                ],
            },
        ],
    },
    "admin": {
        "brand_sub": "Admin / T&P Dashboard",
        "avatar_initial": "T",
        "avatar_name": "T&P Cell Admin",
        "groups": [
            {
                "label": "Platform",
                "items": [
                    {"url_name": "dashboard:admin_overview", "label": "Dashboard & Analytics"},
                ],
            },
            {
                "label": "People",
                "items": [
                    {"url_name": "dashboard:admin_users", "label": "Manage Users"},
                    {"url_name": "dashboard:admin_staff_roles", "label": "Admin / Staff Roles"},
                    {"url_name": "dashboard:admin_feedback", "label": "User Feedback"},
                ],
            },
        ],
    },
}
