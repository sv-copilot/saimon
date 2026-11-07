# Voice profile → content type mapping

Single source of truth for which `spencer-*` voice profile binds to which
content type, confirmed against `list_content_types` output (not just seed
data). Owned by `SAIMON-VOICE-PROFILE-AUDIT-1` (#213); the executable mirror is
`tests/saimon_mcp/test_voice_profiles.py`.

## Declared `spencer-*` profiles

| Voice profile | Tone |
| --- | --- |
| `spencer-default` | Neutral, clear, general-purpose |
| `spencer-technical` | Precise, detailed, assumes domain knowledge |
| `spencer-casual` | Friendly, conversational, short sentences |
| `spencer-formal` | Polished, diplomatic, executive audiences |
| `spencer-marketing` | Persuasive, benefit-focused, call to action |

## Content type → voice profile (handoff §5)

The handoff (§5 *Content type → voice profile → site section*) lists seven
types explicitly and asks that `white_paper` and the *remainder* be confirmed
via `list_content_types`. The audit confirmed every content-ops type is bound;
no new bindings were required.

| Content type | Voice profile |
| --- | --- |
| `blog_post` | `spencer-default` |
| `summary` | `spencer-default` |
| `research_note` | `spencer-technical` |
| `social_post` | `spencer-casual` |
| `email_draft` | `spencer-default` |
| `press_release` | `spencer-formal` |
| `case_study` | `spencer-marketing` |
| `white_paper` | `spencer-technical` |
| `job_posting` | `spencer-formal` |
| `meeting_notes` | `spencer-default` |
| `proposal` | `spencer-formal` |
| `tutorial` | `spencer-technical` |
| `product_review` | `spencer-technical` |
| `bibliography` | `spencer-technical` |

## Flagged to operator — storage-only universe types

The five universe content types are world-building storage types
(`SAIMON-UNIVERSE-TYPES`), not generation-oriented content. They are
deliberately left **unbound** (`voice_profile: None`) and must not be silently
wired to a `spencer-*` profile:

| Content type | Voice profile |
| --- | --- |
| `character` | `None` (storage-only) |
| `location` | `None` (storage-only) |
| `faction` | `None` (storage-only) |
| `timeline_event` | `None` (storage-only) |
| `lore_rule` | `None` (storage-only) |

## Audit result

- ✅ Every handoff §5 content type resolves a declared `spencer-*` profile.
- ✅ No missing bindings among content-ops types — nothing needed wiring.
- ⚠️ Universe types remain intentionally unbound (flagged above, not a defect).
