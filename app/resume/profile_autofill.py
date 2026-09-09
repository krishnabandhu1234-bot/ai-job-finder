"""Seeding the Job Search Profile from an uploaded resume.

Without this, a new user has to type their target titles, seniority,
industries and locations into the Job Search Profile page by hand -
after the app has *already* extracted exactly those things from their
resume onto the Candidate Profile. That's redundant data entry, and
until it's done matching has nothing to work with, so the app appears
to "find nothing" on a first scan.

The rule this module follows: **only fill fields the user hasn't set.**
Every value written here is a suggestion derived from the resume, and a
suggestion must never overwrite an explicit human choice - if the user
cleared "Job titles" on purpose, a later resume upload silently
repopulating it would be the app fighting them. So a field is seeded
only while it is still empty, and everything remains fully editable on
the Job Search Profile page afterwards (section 3: auto-detected values
are always shown and correctable, never hidden).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Seniority levels adjacent to the candidate's own, so matching doesn't
# hard-filter away a role one notch either side of where the resume
# happens to land. Keyed by the detected level; the value is the set of
# levels seeded into `UserPreferences.seniority_levels`.
_ADJACENT_SENIORITY = {
    "entry": ["entry", "mid"],
    "mid": ["entry", "mid", "senior"],
    "senior": ["mid", "senior", "staff", "lead"],
    "staff": ["senior", "staff", "principal", "lead"],
    "principal": ["staff", "principal", "lead", "director"],
    "lead": ["senior", "staff", "lead", "manager"],
    "manager": ["lead", "manager", "director"],
    "director": ["manager", "director", "vp"],
    "vp": ["director", "vp", "executive"],
    "executive": ["vp", "executive"],
}


@dataclass
class AutofillResult:
    """What was actually seeded, so the UI can tell the user rather than
    silently changing their settings behind their back."""

    filled: dict[str, list[str]] = field(default_factory=dict)
    skipped_already_set: list[str] = field(default_factory=list)

    @property
    def any_filled(self) -> bool:
        return bool(self.filled)

    def summary(self) -> str:
        if not self.filled:
            return "Your job search profile was already filled in - nothing was changed."
        parts = []
        for key, values in self.filled.items():
            label = key.replace("_", " ").capitalize()
            shown = ", ".join(values[:4])
            more = f" (+{len(values) - 4} more)" if len(values) > 4 else ""
            parts.append(f"• {label}: {shown}{more}")
        return "Filled in from your resume:\n" + "\n".join(parts)


def autofill_preferences_from_profile(session, context, profile, prefs) -> AutofillResult:
    """Seeds empty Job Search Profile fields from the parsed resume.

    Returns what changed. Never raises and never overwrites a non-empty
    field - see the module docstring for why that restraint matters."""
    result = AutofillResult()
    updates: dict[str, list] = {}

    def seed(field_name: str, values: list[str]) -> None:
        cleaned = [v for v in (values or []) if str(v).strip()]
        if not cleaned:
            return
        if getattr(prefs, field_name, None):
            result.skipped_already_set.append(field_name)
            return
        updates[field_name] = cleaned
        result.filled[field_name] = cleaned

    seed("target_titles", list(profile.target_roles or []))
    seed("industries", list(profile.industries or []))
    seed("locations", list(profile.locations or []))

    seniority = (profile.seniority or "").strip().lower()
    if seniority:
        seed("seniority_levels", _ADJACENT_SENIORITY.get(seniority, [seniority]))

    if updates:
        context.preferences_repo.save(session, prefs, **updates)
        logger.info("Auto-filled job search profile fields from resume: %s", ", ".join(updates))

    return result
