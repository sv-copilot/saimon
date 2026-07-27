"""job_hunt_config.py — Job Hunt domain bootstrap definitions.

Domain tool for job hunting: resume, cover letter, job matching,
interview preparation, and salary benchmarking.

This module follows the same pattern as seed_data.py but is kept separate
so domain tools don't pollute the platform core.  SeedLoader loads these
definitions at runtime alongside the canonical seed data.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Domain identity
# ---------------------------------------------------------------------------

DOMAIN_ID = "job_hunt"

# ---------------------------------------------------------------------------
# Content type definitions
# ---------------------------------------------------------------------------

DOMAIN_CONTENT_TYPES: list[dict[str, Any]] = [
    {
        "name": "resume",
        "description": "Professional resume or CV tailored to a specific "
                       "role, highlighting relevant skills and experience.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The target role and candidate background."},
        ],
        "optional_params": [
            {"name": "format", "type": "str",
             "description": "Resume format: chronological, functional, "
                            "hybrid."},
            {"name": "seniority", "type": "str",
             "description": "Seniority level: junior, mid, senior, lead."},
            {"name": "industry", "type": "str",
             "description": "Target industry."},
            {"name": "max_length", "type": "int",
             "description": "Maximum page count (default: 2)."},
        ],
        "voice_profile": "candidate-confident",
    },
    {
        "name": "cover_letter",
        "description": "Tailored cover letter that connects candidate "
                       "experience to the specific role and company.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The job description and candidate context."},
        ],
        "optional_params": [
            {"name": "company", "type": "str",
             "description": "Target company name."},
            {"name": "role", "type": "str",
             "description": "Target role title."},
            {"name": "tone", "type": "str",
             "description": "Desired tone: enthusiastic, professional, "
                            "confident."},
            {"name": "highlights", "type": "list[str]",
             "description": "Key achievements to feature."},
        ],
        "voice_profile": "candidate-confident",
    },
    {
        "name": "job_match",
        "description": "Analysis of how well a candidate's profile matches "
                       "a job description, with gap analysis and fit score.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The job description to match against."},
        ],
        "optional_params": [
            {"name": "candidate_profile", "type": "str",
             "description": "The candidate's resume or profile text."},
            {"name": "scoring", "type": "str",
             "description": "Scoring method: percentage, 5-star, "
                            "detailed."},
            {"name": "gap_analysis", "type": "bool",
             "description": "Whether to include skill gap analysis."},
        ],
        "voice_profile": "hiring-manager-neutral",
    },
    {
        "name": "interview_prep",
        "description": "Interview preparation guide with role-specific "
                       "questions, answer frameworks, and company research.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The role and company for interview prep."},
        ],
        "optional_params": [
            {"name": "role", "type": "str",
             "description": "Target role title."},
            {"name": "company", "type": "str",
             "description": "Company name for research context."},
            {"name": "interview_type", "type": "str",
             "description": "Type: technical, behavioral, case, "
                            "panel, screening."},
            {"name": "question_count", "type": "int",
             "description": "Number of practice questions to generate."},
        ],
        "voice_profile": "recruiter-persuasive",
    },
    {
        "name": "salary_benchmark",
        "description": "Salary range research and benchmarking for a role, "
                       "considering location, experience, and industry.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The role and location for salary research."},
        ],
        "optional_params": [
            {"name": "role", "type": "str",
             "description": "Target role title."},
            {"name": "location", "type": "str",
             "description": "Geographic location or remote."},
            {"name": "seniority", "type": "str",
             "description": "Seniority level."},
            {"name": "industry", "type": "str",
             "description": "Industry for context."},
            {"name": "currency", "type": "str",
             "description": "Currency code (USD, EUR, GBP, etc.)."},
        ],
        "voice_profile": "hiring-manager-neutral",
    },
]

# ---------------------------------------------------------------------------
# Voice profile definitions
# ---------------------------------------------------------------------------

DOMAIN_VOICE_PROFILES: list[dict[str, Any]] = [
    {
        "name": "recruiter-persuasive",
        "description": "Recruiter voice: persuasive, enthusiastic, "
                       "selling the opportunity while vetting fit.",
        "tone": "persuasive",
        "style_guide": (
            "Frame everything as an opportunity. Use enthusiastic but "
            "professional language. Balance selling the role with "
            "assessing fit. Include clear next steps in every "
            "communication."
        ),
    },
    {
        "name": "candidate-confident",
        "description": "Candidate voice: confident yet humble, "
                       "achievement-focused without arrogance.",
        "tone": "confident",
        "style_guide": (
            "Lead with measurable achievements. Use active voice and "
            "action verbs (led, built, delivered). Quantify impact "
            "where possible. Be direct about skills without "
            "overselling. Keep it concise — respect the reader's "
            "time."
        ),
    },
    {
        "name": "hiring-manager-neutral",
        "description": "Hiring manager voice: evaluative, neutral, "
                       "criteria-driven assessment.",
        "tone": "neutral",
        "style_guide": (
            "Be objective and criteria-driven. Use structured "
            "evaluation frameworks. Compare against requirements, "
            "not feelings. Flag both strengths and gaps clearly. "
            "Maintain a fair, unbiased tone throughout."
        ),
    },
]

# ---------------------------------------------------------------------------
# Seed request definitions
# ---------------------------------------------------------------------------

DOMAIN_SEED_REQUESTS: list[dict[str, Any]] = [
    # ── resume ─────────────────────────────────────────────────────
    {
        "content_type": "resume",
        "prompt": "Senior Python engineer with 8 years of experience in "
                  "distributed systems, FastAPI, and PostgreSQL. "
                  "Led a team of 5 at a fintech startup, reducing API "
                  "latency by 40%. Seeking a staff-level role in "
                  "AI infrastructure.",
        "parameters": {
            "format": "hybrid",
            "seniority": "senior",
            "industry": "technology",
        },
    },
    {
        "content_type": "resume",
        "prompt": "ML engineer transitioning from academia with a PhD in "
                  "computational linguistics. Built 3 production NLP "
                  "pipelines during internships at Google and Meta. "
                  "Published 12 papers with 500+ citations.",
        "parameters": {
            "format": "functional",
            "seniority": "mid",
            "industry": "research",
        },
    },

    # ── cover_letter ───────────────────────────────────────────────
    {
        "content_type": "cover_letter",
        "prompt": "Applying for a Lead Platform Engineer role at Saimon. "
                  "The role requires deep experience with MCP servers, "
                  "PostgreSQL, and AI agent infrastructure. I have built "
                  "6 MCP servers and designed a self-extending content "
                  "platform.",
        "parameters": {
            "company": "Saimon",
            "role": "Lead Platform Engineer",
            "tone": "confident",
        },
    },
    {
        "content_type": "cover_letter",
        "prompt": "Applying for a Senior Data Scientist position at "
                  "Stripe. I have 5 years of experience in fraud "
                  "detection ML, deployed models serving 10M+ "
                  "transactions/day, and mentored 3 junior data "
                  "scientists.",
        "parameters": {
            "company": "Stripe",
            "role": "Senior Data Scientist",
            "tone": "professional",
        },
    },

    # ── job_match ──────────────────────────────────────────────────
    {
        "content_type": "job_match",
        "prompt": "Job Description: We're looking for a Staff Engineer "
                  "with 10+ years in distributed systems, expert-level "
                  "Python and Go, experience leading 10+ person "
                  "engineering teams, and a track record of shipping "
                  "platform infrastructure used by 100+ developers.",
        "parameters": {
            "scoring": "percentage",
            "gap_analysis": True,
        },
    },
    {
        "content_type": "job_match",
        "prompt": "Job Description: Seeking a founding engineer for an "
                  "AI startup. Must have full-stack skills (React, "
                  "Python, AWS), experience with LLM APIs and prompt "
                  "engineering, and comfort with ambiguity and 0→1 "
                  "product development.",
        "parameters": {
            "scoring": "5-star",
            "gap_analysis": True,
        },
    },

    # ── interview_prep ─────────────────────────────────────────────
    {
        "content_type": "interview_prep",
        "prompt": "Preparing for a technical interview at Anthropic for "
                  "a Research Engineer role. The interview process "
                  "includes: system design round, coding round (Python), "
                  "ML fundamentals, and a research presentation.",
        "parameters": {
            "role": "Research Engineer",
            "company": "Anthropic",
            "interview_type": "technical",
            "question_count": 15,
        },
    },
    {
        "content_type": "interview_prep",
        "prompt": "Behavioral interview prep for a Product Manager role "
                  "at Notion. Needs: STAR method examples, leadership "
                  "stories, product sense frameworks, and cross-"
                  "functional collaboration scenarios.",
        "parameters": {
            "role": "Product Manager",
            "company": "Notion",
            "interview_type": "behavioral",
            "question_count": 10,
        },
    },

    # ── salary_benchmark ───────────────────────────────────────────
    {
        "content_type": "salary_benchmark",
        "prompt": "Salary research for a Senior Software Engineer role "
                  "in San Francisco, with 7 years of experience, "
                  "specializing in AI/ML infrastructure and platform "
                  "engineering.",
        "parameters": {
            "role": "Senior Software Engineer",
            "location": "San Francisco, CA",
            "seniority": "senior",
            "industry": "technology",
            "currency": "USD",
        },
    },
    {
        "content_type": "salary_benchmark",
        "prompt": "Salary benchmarking for a remote Data Engineering "
                  "Manager role, managing a team of 8, with expertise "
                  "in Spark, Airflow, and cloud data warehouses.",
        "parameters": {
            "role": "Data Engineering Manager",
            "location": "Remote (US)",
            "seniority": "lead",
            "currency": "USD",
        },
    },
]
