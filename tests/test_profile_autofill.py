"""Tests for seeding the Job Search Profile from a parsed resume
(`app/resume/profile_autofill.py`).

The behavior that matters most here is the restraint: a resume-derived
suggestion must never overwrite something the user set themselves.
"""

from __future__ import annotations

from app.resume.profile_autofill import autofill_preferences_from_profile


def _profile(session, app_context, **overrides):
    user = app_context.users_repo.get_or_create_default_user(session, "test@example.com")
    profile = app_context.candidate_profile_repo.get_current(session, user.id)
    fields = dict(
        target_roles=["CFD Engineer", "Thermal Engineer"],
        seniority="senior",
        industries=["Aerospace"],
        locations=["Austin, TX"],
    )
    fields.update(overrides)
    app_context.candidate_profile_repo.save(session, profile, **fields)
    return user, profile


def test_autofill_seeds_empty_preference_fields(db_session, app_context):
    user, profile = _profile(db_session, app_context)
    prefs = app_context.preferences_repo.get_active(db_session, user.id)

    result = autofill_preferences_from_profile(db_session, app_context, profile, prefs)

    assert result.any_filled
    assert prefs.target_titles == ["CFD Engineer", "Thermal Engineer"]
    assert prefs.industries == ["Aerospace"]
    assert prefs.locations == ["Austin, TX"]


def test_autofill_includes_adjacent_seniority_levels(db_session, app_context):
    """Filtering to exactly one seniority level would discard roles one
    notch either side of where the resume happens to land."""
    user, profile = _profile(db_session, app_context, seniority="senior")
    prefs = app_context.preferences_repo.get_active(db_session, user.id)

    autofill_preferences_from_profile(db_session, app_context, profile, prefs)

    assert "senior" in prefs.seniority_levels
    assert "staff" in prefs.seniority_levels
    assert "mid" in prefs.seniority_levels
    assert "entry" not in prefs.seniority_levels  # not adjacent to senior


def test_autofill_never_overwrites_a_user_set_field(db_session, app_context):
    user, profile = _profile(db_session, app_context)
    prefs = app_context.preferences_repo.get_active(db_session, user.id)
    app_context.preferences_repo.save(db_session, prefs, target_titles=["Something I Chose"])

    result = autofill_preferences_from_profile(db_session, app_context, profile, prefs)

    assert prefs.target_titles == ["Something I Chose"]
    assert "target_titles" in result.skipped_already_set
    assert "target_titles" not in result.filled
    # Other, still-empty fields are still seeded.
    assert prefs.industries == ["Aerospace"]


def test_autofill_is_a_noop_for_an_empty_profile(db_session, app_context):
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    profile = app_context.candidate_profile_repo.get_current(db_session, user.id)
    prefs = app_context.preferences_repo.get_active(db_session, user.id)

    result = autofill_preferences_from_profile(db_session, app_context, profile, prefs)

    assert not result.any_filled
    assert prefs.target_titles == []


def test_autofill_ignores_blank_values(db_session, app_context):
    user, profile = _profile(db_session, app_context, target_roles=["", "   "], seniority="")
    prefs = app_context.preferences_repo.get_active(db_session, user.id)

    autofill_preferences_from_profile(db_session, app_context, profile, prefs)

    assert prefs.target_titles == []
    assert prefs.seniority_levels == []


def test_autofill_summary_is_human_readable(db_session, app_context):
    user, profile = _profile(db_session, app_context)
    prefs = app_context.preferences_repo.get_active(db_session, user.id)

    result = autofill_preferences_from_profile(db_session, app_context, profile, prefs)
    summary = result.summary()

    assert "Target titles" in summary
    assert "CFD Engineer" in summary


def test_autofill_summary_when_nothing_changed(db_session, app_context):
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    profile = app_context.candidate_profile_repo.get_current(db_session, user.id)
    prefs = app_context.preferences_repo.get_active(db_session, user.id)

    result = autofill_preferences_from_profile(db_session, app_context, profile, prefs)

    assert "already filled in" in result.summary()
