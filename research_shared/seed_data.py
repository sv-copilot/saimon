"""seed_data.py — domain bootstrap definitions.

Provides the canonical content types, voice profiles, and seed requests
that bootstrap the Saimon platform.  These definitions are the source of
truth — schema.sql mirrors them for first-run init, and this module
provides programmatic access for runtime loading and re-seeding.
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

SEED_DATA_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Content type definitions
# ---------------------------------------------------------------------------

CONTENT_TYPES: list[dict[str, Any]] = [
    # ── bootstrapped types (match schema.sql) ──────────────────────
    {
        "name": "blog_post",
        "description": "Long-form blog article with introduction, body, "
                       "and conclusion.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The topic or writing prompt."},
        ],
        "optional_params": [
            {"name": "tone", "type": "str",
             "description": "Desired tone (e.g. analytical, casual)."},
            {"name": "max_length", "type": "int",
             "description": "Maximum word count."},
            {"name": "audience", "type": "str",
             "description": "Target audience description."},
        ],
        "voice_profile": "spencer-default",
        "document_family": "long_form",
        "form_factor": "section",
        "profile_key": "long_form",
        "system_prompt": (
            "You are a blog author writing for a technical audience. "
            "Write clear, engaging prose with short paragraphs. Use "
            "active voice. Include a compelling introduction and a "
            "conclusion that ties ideas together. Prefer specific "
            "examples over abstract claims. Use only supplied source "
            "facts; do not invent statistics, dates, or names."
        ),
        "banlist": [
            "delve into", "it is worth noting", "in today's rapidly evolving",
            "in the realm of", "a testament to", "it goes without saying",
        ],
    },
    {
        "name": "summary",
        "description": "Concise summary of source material.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The material to summarise."},
        ],
        "optional_params": [
            {"name": "max_length", "type": "int",
             "description": "Maximum word count for the summary."},
            {"name": "style", "type": "str",
             "description": "Summary style (e.g. bullet, paragraph)."},
        ],
        "voice_profile": "spencer-default",
        "document_family": "general",
        "form_factor": "passage",
        "profile_key": "general",
        "system_prompt": (
            "You are a concise summarizer. Extract the core message "
            "and key details. Be brief, accurate, and objective. "
            "Use bullet points when appropriate for clarity."
        ),
        "banlist": [
            "delve into", "it is worth noting",
        ],
    },
    {
        "name": "research_note",
        "description": "Structured research note with citations.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The research question or topic."},
        ],
        "optional_params": [
            {"name": "tone", "type": "str",
             "description": "Desired tone."},
            {"name": "depth", "type": "str",
             "description": "Depth level: brief, standard, comprehensive."},
            {"name": "format", "type": "str",
             "description": "Output format: markdown, outline, bullets."},
        ],
        "voice_profile": "spencer-technical",
        "document_family": "long_form",
        "form_factor": "section",
        "profile_key": "long_form",
        "system_prompt": (
            "You are a research analyst. Structure findings with clear "
            "citations and evidence. Be precise with terminology. "
            "Flag uncertainty explicitly. Prefer accuracy over brevity. "
            "Use only supplied source facts and cited material."
        ),
        "banlist": [
            "delve into", "it is worth noting", "in today's landscape",
            "furthermore", "moreover",
        ],
    },
    {
        "name": "social_post",
        "description": "Short-form social media post.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The topic or announcement."},
        ],
        "optional_params": [
            {"name": "platform", "type": "str",
             "description": "Target platform: twitter, linkedin, mastodon."},
            {"name": "tone", "type": "str",
             "description": "Desired tone."},
            {"name": "max_length", "type": "int",
             "description": "Maximum character count."},
        ],
        "voice_profile": "spencer-casual",
        "document_family": "marketing",
        "form_factor": "short_paragraph",
        "profile_key": "marketing",
        "system_prompt": (
            "You are a social media writer. Write short, punchy posts. "
            "Use emojis sparingly. Lead with the most interesting point. "
            "One key idea per post. End with a call to action or a hook. "
            "Do not use hashtag stuffing."
        ),
        "banlist": [
            "delve into", "leverage", "game-changer", "synergy",
            "cutting-edge", "revolutionary",
        ],
    },
    {
        "name": "email_draft",
        "description": "Polished email draft.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The email topic or intent."},
        ],
        "optional_params": [
            {"name": "tone", "type": "str",
             "description": "Desired tone."},
            {"name": "recipient_role", "type": "str",
             "description": "Role of recipient (e.g. manager, client)."},
        ],
        "voice_profile": "spencer-default",
        "document_family": "correspondence",
        "form_factor": "passage",
        "profile_key": "correspondence",
        "system_prompt": (
            "You are an email writer. Be direct, respectful, and easy to "
            "scan. State the purpose early. One primary ask or next step. "
            "Avoid filler and corporate jargon. Match the recipient's tone."
        ),
        "banlist": [
            "just circling back", "touch base", "synergy",
            "hope this email finds you well",
        ],
    },

    # ── domain types ──────────────────────────────────────────────
    {
        "name": "press_release",
        "description": "Formal press release announcing news or a product "
                       "launch.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The announcement topic."},
        ],
        "optional_params": [
            {"name": "embargo_date", "type": "str",
             "description": "ISO date before which the release is "
                            "embargoed."},
            {"name": "distribution", "type": "str",
             "description": "Distribution channel: wire, blog, email."},
            {"name": "tone", "type": "str",
             "description": "Desired tone."},
        ],
        "voice_profile": "spencer-formal",
        "document_family": "marketing",
        "form_factor": "section",
        "profile_key": "marketing",
        "system_prompt": (
            "You are a press release writer. Follow AP style. Lead with "
            "the news hook in the first paragraph. Include boilerplate "
            "about the organization. Use quotes for human interest. "
            "End with ###. Do not invent product capabilities, customers, "
            "or endorsements."
        ),
        "banlist": [
            "delve into", "leverage", "game-changer", "world-class",
            "best-in-class", "synergy", "cutting-edge", "revolutionary",
        ],
    },
    {
        "name": "case_study",
        "description": "Customer or project case study with problem, "
                       "solution, and results.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The case study topic or subject."},
        ],
        "optional_params": [
            {"name": "industry", "type": "str",
             "description": "Industry vertical."},
            {"name": "format", "type": "str",
             "description": "Output format: narrative, slides, one-pager."},
            {"name": "tone", "type": "str",
             "description": "Desired tone."},
        ],
        "voice_profile": "spencer-marketing",
        "document_family": "long_form",
        "form_factor": "section",
        "profile_key": "long_form",
        "system_prompt": (
            "You are a case study writer. Structure with problem, solution, "
            "and results sections. Use specific metrics and quotes where "
            "available. Ground claims in supplied source facts. Make the "
            "customer the hero of the story."
        ),
        "banlist": [
            "delve into", "it is worth noting", "furthermore",
            "it goes without saying", "needless to say",
        ],
    },
    {
        "name": "white_paper",
        "description": "In-depth white paper on a technical or strategic "
                       "topic.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The white paper topic."},
        ],
        "optional_params": [
            {"name": "audience", "type": "str",
             "description": "Target audience: technical, executive, "
                            "general."},
            {"name": "depth", "type": "str",
             "description": "Depth: overview, detailed, comprehensive."},
            {"name": "tone", "type": "str",
             "description": "Desired tone."},
            {"name": "sections", "type": "list[str]",
             "description": "Requested section titles."},
        ],
        "voice_profile": "spencer-technical",
        "document_family": "long_form",
        "form_factor": "section",
        "profile_key": "long_form",
        "system_prompt": (
            "You are a white paper author. Write for a professional audience. "
            "Use clear claims, concrete support, and logical flow. Include "
            "an executive summary. Cite sources. Use only supplied source "
            "facts; do not invent statistics, quotes, or events."
        ),
        "banlist": [
            "delve into", "it is worth noting", "furthermore", "moreover",
            "it goes without saying", "needless to say",
        ],
    },
    {
        "name": "job_posting",
        "description": "Job posting with role description, qualifications, "
                       "and responsibilities.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The role title and brief description."},
        ],
        "optional_params": [
            {"name": "role", "type": "str",
             "description": "Specific role title."},
            {"name": "company", "type": "str",
             "description": "Company name."},
            {"name": "seniority", "type": "str",
             "description": "Seniority level: junior, mid, senior, lead."},
        ],
        "voice_profile": "spencer-formal",
        "document_family": "marketing",
        "form_factor": "section",
        "profile_key": "marketing",
        "system_prompt": (
            "You are a job posting writer. Structure with role overview, "
            "responsibilities, qualifications, and benefits. Use inclusive "
            "language. Be specific about requirements. Avoid jargon and "
            "clichés like 'rockstar' or 'ninja'."
        ),
        "banlist": [
            "rockstar", "ninja", "guru", "wizard",
            "world-class", "best-in-class", "synergy",
            "fast-paced environment",
        ],
    },
    {
        "name": "meeting_notes",
        "description": "Structured meeting notes with agenda, discussion "
                       "points, and action items.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The meeting topic or raw transcription."},
        ],
        "optional_params": [
            {"name": "attendees", "type": "list[str]",
             "description": "List of attendee names."},
            {"name": "format", "type": "str",
             "description": "Output format: bullet, narrative, template."},
            {"name": "action_items", "type": "bool",
             "description": "Whether to extract and list action items."},
        ],
        "voice_profile": "spencer-default",
        "document_family": "general",
        "form_factor": "bullet",
        "profile_key": "general",
        "system_prompt": (
            "You are a meeting notes writer. Structure with agenda, "
            "discussion points, decisions, and action items. Use bullet "
            "points for clarity. Assign action items to roles. Be "
            "objective and factual."
        ),
        "banlist": [
            "delve into", "it is worth noting",
        ],
    },
    {
        "name": "proposal",
        "description": "Business or project proposal with executive "
                       "summary, scope, timeline, and budget.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The proposal topic or RFP description."},
        ],
        "optional_params": [
            {"name": "client", "type": "str",
             "description": "Client or stakeholder name."},
            {"name": "budget", "type": "str",
             "description": "Budget range or constraints."},
            {"name": "timeline", "type": "str",
             "description": "Project timeline."},
            {"name": "format", "type": "str",
             "description": "Output format: brief, full, slides."},
        ],
        "voice_profile": "spencer-formal",
        "document_family": "long_form",
        "form_factor": "section",
        "profile_key": "long_form",
        "system_prompt": (
            "You are a proposal writer. Structure with executive summary, "
            "scope, timeline, budget, and deliverables. Be precise about "
            "numbers and dates. Use confident but not arrogant language. "
            "Ground all claims in supplied source facts."
        ),
        "banlist": [
            "delve into", "it is worth noting", "furthermore",
            "game-changer", "synergy",
        ],
    },
    {
        "name": "tutorial",
        "description": "Step-by-step tutorial or how-to guide.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The tutorial topic."},
        ],
        "optional_params": [
            {"name": "skill_level", "type": "str",
             "description": "Target skill level: beginner, intermediate, "
                            "advanced."},
            {"name": "format", "type": "str",
             "description": "Output format: markdown, notebook, video "
                            "script."},
            {"name": "prerequisites", "type": "list[str]",
             "description": "Required knowledge or tools."},
        ],
        "voice_profile": "spencer-technical",
        "document_family": "long_form",
        "form_factor": "section",
        "profile_key": "long_form",
        "system_prompt": (
            "You are a tutorial writer. Write step-by-step instructions. "
            "Use numbered steps for sequential actions. Include code "
            "blocks where relevant. Define terms before using them. "
            "Include troubleshooting tips. Assume the reader is following along."
        ),
        "banlist": [
            "delve into", "it is worth noting", "furthermore",
            "it is important to note",
        ],
    },
    {
        "name": "product_review",
        "description": "Structured product or service review with pros, "
                       "cons, and rating.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The product or service to review."},
        ],
        "optional_params": [
            {"name": "rating_scale", "type": "str",
             "description": "Rating scale: 5-star, 10-point, letter."},
            {"name": "pros_cons", "type": "bool",
             "description": "Whether to include pros/cons list."},
            {"name": "tone", "type": "str",
             "description": "Desired tone."},
        ],
        "voice_profile": "spencer-technical",
        "document_family": "long_form",
        "form_factor": "passage",
        "profile_key": "long_form",
        "system_prompt": (
            "You are a product reviewer. Structure with pros, cons, and "
            "a balanced verdict. Be specific about features and trade-offs. "
            "Compare to alternatives where relevant. Give concrete examples "
            "of use cases. Avoid hype and superlatives."
        ),
        "banlist": [
            "delve into", "it is worth noting", "game-changer",
            "revolutionary", "best-in-class",
        ],
    },
    {
        "name": "bibliography",
        "description": "Ranked, annotated bibliography with DOIs and "
                       "source index attribution.",
        "required_params": [
            {"name": "prompt", "type": "str",
             "description": "The research topic or question."},
        ],
        "optional_params": [
            {"name": "source_indexes", "type": "list[str]",
             "description": "Shadow library source indexes to search."},
            {"name": "limit", "type": "int",
             "description": "Maximum number of entries."},
            {"name": "annotation_style", "type": "str",
             "description": "Annotation style: descriptive, evaluative, "
                            "combined."},
            {"name": "tone", "type": "str",
             "description": "Desired tone."},
        ],
        "voice_profile": "spencer-technical",
        "document_family": "general",
        "form_factor": "bullet",
        "profile_key": "general",
        "system_prompt": (
            "You are a bibliographer. List sources with DOIs, titles, "
            "authors, years, and annotations. Format entries consistently. "
            "Rank by relevance. Include source index attribution."
        ),
        "banlist": [
            "delve into", "it is worth noting",
        ],
    },

    # ── Universe / world-building types (SAIMON-UNIVERSE-TYPES) ────
    {
        "name": "character",
        "description": "A fictional character in a narrative universe — "
                       "backstory, traits, relationships, and arc.",
        "required_params": [
            {"name": "name", "type": "str",
             "description": "Character name."},
            {"name": "description", "type": "str",
             "description": "Physical and personality description."},
        ],
        "optional_params": [
            {"name": "faction", "type": "str",
             "description": "Faction or organization the character belongs to."},
            {"name": "location", "type": "str",
             "description": "Primary location or residence."},
            {"name": "role", "type": "str",
             "description": "Role or occupation."},
            {"name": "traits", "type": "str",
             "description": "Key personality traits or abilities."},
            {"name": "backstory", "type": "str",
             "description": "Character history and backstory."},
        ],
        "voice_profile": None,
        "document_family": "general",
        "form_factor": "narrative",
        "profile_key": "general",
        "system_prompt": None,
        "banlist": [],
    },
    {
        "name": "location",
        "description": "A physical or virtual place in a fictional universe — "
                       "geography, atmosphere, significance.",
        "required_params": [
            {"name": "name", "type": "str",
             "description": "Location name."},
            {"name": "description", "type": "str",
             "description": "Description of the place."},
        ],
        "optional_params": [
            {"name": "region", "type": "str",
             "description": "Parent region or city."},
            {"name": "atmosphere", "type": "str",
             "description": "Mood, aesthetic, or vibe."},
            {"name": "significance", "type": "str",
             "description": "Why this location matters in the story."},
        ],
        "voice_profile": None,
        "document_family": "general",
        "form_factor": "narrative",
        "profile_key": "general",
        "system_prompt": None,
        "banlist": [],
    },
    {
        "name": "faction",
        "description": "An organization, group, or faction in a fictional "
                       "universe — goals, structure, members, influence.",
        "required_params": [
            {"name": "name", "type": "str",
             "description": "Faction name."},
            {"name": "description", "type": "str",
             "description": "Description of the faction."},
        ],
        "optional_params": [
            {"name": "goals", "type": "str",
             "description": "Faction objectives and motivations."},
            {"name": "structure", "type": "str",
             "description": "Organizational structure."},
            {"name": "leader", "type": "str",
             "description": "Current leader or leadership."},
            {"name": "influence", "type": "str",
             "description": "Sphere of influence or territory."},
        ],
        "voice_profile": None,
        "document_family": "general",
        "form_factor": "narrative",
        "profile_key": "general",
        "system_prompt": None,
        "banlist": [],
    },
    {
        "name": "timeline_event",
        "description": "A significant event in a fictional timeline — "
                       "date, participants, consequences.",
        "required_params": [
            {"name": "name", "type": "str",
             "description": "Event name."},
            {"name": "description", "type": "str",
             "description": "What happened."},
        ],
        "optional_params": [
            {"name": "date", "type": "str",
             "description": "When it occurred (in-universe date)."},
            {"name": "participants", "type": "str",
             "description": "Characters or factions involved."},
            {"name": "consequences", "type": "str",
             "description": "What changed as a result."},
        ],
        "voice_profile": None,
        "document_family": "general",
        "form_factor": "narrative",
        "profile_key": "general",
        "system_prompt": None,
        "banlist": [],
    },
    {
        "name": "lore_rule",
        "description": "A rule, law, or principle governing a fictional "
                       "universe — magic systems, technology constraints, "
                       "social norms.",
        "required_params": [
            {"name": "name", "type": "str",
             "description": "Rule name or short descriptor."},
            {"name": "description", "type": "str",
             "description": "How the rule works."},
        ],
        "optional_params": [
            {"name": "domain", "type": "str",
             "description": "What domain this rule applies to (magic, tech, social)."},
            {"name": "exceptions", "type": "str",
             "description": "Known exceptions or edge cases."},
            {"name": "source", "type": "str",
             "description": "Origin of this rule in-universe."},
        ],
        "voice_profile": None,
        "document_family": "general",
        "form_factor": "narrative",
        "profile_key": "general",
        "system_prompt": None,
        "banlist": [],
    },
]


# ---------------------------------------------------------------------------
# Voice profile definitions
# ---------------------------------------------------------------------------

VOICE_PROFILES: list[dict[str, Any]] = [
    {
        "name": "spencer-default",
        "description": "Default Spencer Varadi voice: direct, analytical, "
                       "slightly informal.",
        "tone": "analytical",
        "style_guide": (
            "Use short paragraphs. Prefer active voice. Be direct but "
            "not blunt. Use bullet points for lists."
        ),
    },
    {
        "name": "spencer-formal",
        "description": "Formal Spencer voice: polished, diplomatic, "
                       "suitable for executive audiences.",
        "tone": "formal",
        "style_guide": (
            "Use proper grammar and full sentences. Avoid contractions. "
            "Maintain a diplomatic tone. Structure with clear headings. "
            "Include executive summary for long documents."
        ),
    },
    {
        "name": "spencer-casual",
        "description": "Casual Spencer voice: friendly, approachable, "
                       "conversational.",
        "tone": "casual",
        "style_guide": (
            "Write like you are talking to a colleague. Use contractions "
            "freely. Keep sentences short and punchy. Use em-dashes for "
            "asides. One idea per paragraph."
        ),
    },
    {
        "name": "spencer-marketing",
        "description": "Marketing Spencer voice: persuasive, "
                       "benefit-focused, engaging.",
        "tone": "persuasive",
        "style_guide": (
            "Lead with benefits, not features. Use social proof where "
            "possible. Keep the reader moving with short paragraphs and "
            "compelling transitions. Include a clear call to action."
        ),
    },
    {
        "name": "spencer-technical",
        "description": "Technical Spencer voice: precise, detailed, "
                       "assumes domain knowledge.",
        "tone": "technical",
        "style_guide": (
            "Be precise with terminology. Define acronyms on first use. "
            "Use code blocks and diagrams where appropriate. Cite "
            "sources. Prioritise accuracy over brevity."
        ),
    },
]


# ---------------------------------------------------------------------------
# Seed request definitions
# ---------------------------------------------------------------------------

SEED_REQUESTS: list[dict[str, Any]] = [
    # ── blog_post ─────────────────────────────────────────────────
    {
        "content_type": "blog_post",
        "prompt": "The future of AI agents in personal productivity: how "
                  "autonomous agents will reshape daily workflows by 2030.",
        "parameters": {
            "tone": "analytical",
            "audience": "tech professionals",
        },
    },
    {
        "content_type": "blog_post",
        "prompt": "Lessons learned from building six microservices that "
                  "share one knowledge graph.",
        "parameters": {
            "tone": "casual",
            "max_length": 1200,
        },
    },

    # ── summary ───────────────────────────────────────────────────
    {
        "content_type": "summary",
        "prompt": "Summarise the Saimon platform architecture: six atomic "
                  "MCP services (search, generate, export, evaluate, "
                  "verify, explore) sharing one PostgreSQL knowledge graph "
                  "with runtime content type registration.",
        "parameters": {
            "style": "bullet",
            "max_length": 150,
        },
    },

    # ── research_note ─────────────────────────────────────────────
    {
        "content_type": "research_note",
        "prompt": "Retrieval-augmented generation (RAG): how grounding LLM "
                  "outputs in a knowledge graph improves factuality and "
                  "reduces hallucination.",
        "parameters": {
            "depth": "comprehensive",
            "format": "markdown",
        },
    },

    # ── social_post ───────────────────────────────────────────────
    {
        "content_type": "social_post",
        "prompt": "Announce Saimon v1.0: an open-source, self-extending "
                  "content platform powered by six MCPs and one knowledge "
                  "graph. Built for agents, by agents.",
        "parameters": {
            "platform": "linkedin",
            "tone": "casual",
        },
    },
    {
        "content_type": "social_post",
        "prompt": "Hot take: the best AI tools are the ones that know when "
                  "to stay out of your way. Saimon is designed around this "
                  "principle.",
        "parameters": {
            "platform": "twitter",
            "max_length": 280,
        },
    },

    # ── email_draft ───────────────────────────────────────────────
    {
        "content_type": "email_draft",
        "prompt": "Invite the engineering team to adopt AI-assisted "
                  "development workflows using Saimon's MCP tools.",
        "parameters": {
            "tone": "casual",
            "recipient_role": "engineering team",
        },
    },

    # ── press_release ─────────────────────────────────────────────
    {
        "content_type": "press_release",
        "prompt": "Saimon launches as open-source self-extending content "
                  "platform: six MCPs, one knowledge graph, runtime type "
                  "registration.",
        "parameters": {
            "tone": "formal",
            "distribution": "wire",
        },
    },

    # ── case_study ────────────────────────────────────────────────
    {
        "content_type": "case_study",
        "prompt": "How a research team reduced content creation time by "
                  "60% after adopting Saimon for automated research notes "
                  "and summaries.",
        "parameters": {
            "industry": "technology",
            "format": "narrative",
        },
    },

    # ── white_paper ───────────────────────────────────────────────
    {
        "content_type": "white_paper",
        "prompt": "The case for self-extending AI platforms: why static "
                  "content pipelines fail and how runtime type "
                  "registration solves the adaptability problem.",
        "parameters": {
            "audience": "technical",
            "depth": "comprehensive",
        },
    },

    # ── job_posting ───────────────────────────────────────────────
    {
        "content_type": "job_posting",
        "prompt": "Senior Python Engineer — help us build the future of "
                  "AI-assisted content tooling with FastAPI, PostgreSQL, "
                  "and MCP.",
        "parameters": {
            "seniority": "senior",
        },
    },

    # ── meeting_notes ─────────────────────────────────────────────
    {
        "content_type": "meeting_notes",
        "prompt": "Weekly engineering sync: reviewed Saimon architecture, "
                  "discussed self-extension flow, planned domain tools "
                  "sprint, identified need for seed data module.",
        "parameters": {
            "format": "bullet",
            "action_items": True,
        },
    },

    # ── proposal ──────────────────────────────────────────────────
    {
        "content_type": "proposal",
        "prompt": "Proposal for implementing AI governance in enterprise "
                  "content pipelines: audit trails, quality gates, "
                  "human-in-the-loop review workflows.",
        "parameters": {
            "format": "brief",
            "timeline": "Q1-Q2 2026",
        },
    },

    # ── tutorial ──────────────────────────────────────────────────
    {
        "content_type": "tutorial",
        "prompt": "Getting started with Saimon: build and register your "
                  "first custom content type in 10 minutes.",
        "parameters": {
            "skill_level": "beginner",
            "format": "markdown",
        },
    },

    # ── product_review ────────────────────────────────────────────
    {
        "content_type": "product_review",
        "prompt": "Review of Saimon v1.0 as a content generation platform: "
                  "architecture, extensibility, developer experience, and "
                  "limitations.",
        "parameters": {
            "rating_scale": "5-star",
            "pros_cons": True,
        },
    },
]


# ---------------------------------------------------------------------------
# Loader functions
# ---------------------------------------------------------------------------

async def load_content_types(db: Any) -> int:
    """Load all content types into the database.

    Uses UPSERT (INSERT ... ON CONFLICT DO UPDATE) so the operation is
    idempotent — safe to run repeatedly.

    Args:
        db: A DatabasePool with an ``execute`` method.

    Returns:
        Number of content types loaded.
    """
    for ct in CONTENT_TYPES:
        await db.execute(
            "INSERT INTO content_type_registry "
            "(name, description, required_params, optional_params, "
            "voice_profile) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (name) DO UPDATE SET "
            "description = EXCLUDED.description, "
            "required_params = EXCLUDED.required_params, "
            "optional_params = EXCLUDED.optional_params, "
            "voice_profile = EXCLUDED.voice_profile, "
            "updated_at = now()",
            ct["name"],
            ct["description"],
            json.dumps(ct["required_params"]),
            json.dumps(ct["optional_params"]),
            ct.get("voice_profile"),
        )
    return len(CONTENT_TYPES)


async def load_voice_profiles(db: Any) -> int:
    """Load all voice profiles into the database.

    Uses UPSERT so the operation is idempotent.

    Args:
        db: A DatabasePool with an ``execute`` method.

    Returns:
        Number of voice profiles loaded.
    """
    for vp in VOICE_PROFILES:
        await db.execute(
            "INSERT INTO voice_profiles "
            "(name, description, tone, style_guide) "
            "VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (name) DO UPDATE SET "
            "description = EXCLUDED.description, "
            "tone = EXCLUDED.tone, "
            "style_guide = EXCLUDED.style_guide",
            vp["name"],
            vp["description"],
            vp["tone"],
            vp.get("style_guide"),
        )
    return len(VOICE_PROFILES)


async def load_seed_requests(db: Any) -> int:
    """Load all seed requests into the database.

    Does NOT use UPSERT — seed requests are append-only.  Each call
    inserts new rows with status 'pending'.  Use ``--replay`` to
    process them.

    Args:
        db: A DatabasePool with an ``execute`` method.

    Returns:
        Number of seed requests loaded.
    """
    for sr in SEED_REQUESTS:
        await db.execute(
            "INSERT INTO seed_requests "
            "(content_type, prompt, parameters, status) "
            "VALUES ($1, $2, $3, 'pending')",
            sr["content_type"],
            sr["prompt"],
            json.dumps(sr["parameters"]),
        )
    return len(SEED_REQUESTS)


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def get_all_definitions() -> dict[str, Any]:
    """Return all seed data definitions as a single dict.

    Returns:
        Dict with keys ``content_types``, ``voice_profiles``,
        ``seed_requests``.
    """
    return {
        "content_types": CONTENT_TYPES,
        "voice_profiles": VOICE_PROFILES,
        "seed_requests": SEED_REQUESTS,
    }
