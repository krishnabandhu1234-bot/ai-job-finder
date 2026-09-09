"""High-level daily-email orchestration (section 11): resolves the
current user/profile/preferences, builds the report, sends it, and
records the outcome - the single entry point the scheduler (Phase 8)
and the Dashboard's manual "Send Daily Email Now" call into.

Marking jobs as notified only happens AFTER a successful send, so a
failed send is safely retried next time instead of silently dropping
jobs from the report forever (section 11: "Do not send duplicate
notifications" - the flip side is equally important: never lose a job
because of a transient SMTP error).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.constants import DEFAULT_MIN_EMAIL_SCORE
from app.database.models import EmailHistory, Job, utc_now
from app.email.report import DailyReport, build_daily_report
from app.email.sender import EmailSendError, resolve_email_config, send_email

logger = logging.getLogger(__name__)


@dataclass
class EmailRunResult:
    sent: bool
    skipped_reason: str | None = None
    error: str | None = None
    job_count: int = 0
    report: DailyReport | None = None


def send_daily_report_now(session, context) -> EmailRunResult:
    user = context.users_repo.get_or_create_default_user(
        session, context.config.email_to or "local-user@aijobfinder.local"
    )
    profile = context.candidate_profile_repo.get_current(session, user.id)
    prefs = context.preferences_repo.get_active(session, user.id)
    # "Max jobs per email" has a dedicated control on the Email Settings
    # page (email.max_jobs) - that's what actually gets edited day to day,
    # so it takes priority over the UserPreferences column of the same
    # meaning, which only exists as a schema-level default/fallback.
    max_jobs = context.settings_repo.get_int(session, "email.max_jobs", prefs.max_email_jobs or 15)

    report = build_daily_report(
        session, context, profile.id,
        min_score=prefs.min_email_score or DEFAULT_MIN_EMAIL_SCORE,
        max_jobs=max_jobs,
    )

    if not report.items:
        logger.info("No new jobs met the minimum score - skipping today's email (quality over quantity).")
        return EmailRunResult(sent=False, skipped_reason="No new jobs met your minimum match score.", report=report)

    email_config = resolve_email_config(session, context)
    try:
        send_email(email_config, report.subject, report.html_body, report.text_body)
    except EmailSendError as exc:
        session.add(
            EmailHistory(
                sent_at=utc_now(), recipient=email_config.recipient, subject=report.subject,
                job_count=len(report.items), job_match_ids=report.job_match_ids,
                status="failed", error_message=str(exc), html_body=report.html_body,
            )
        )
        session.flush()
        logger.warning("Daily email send failed: %s", exc)
        return EmailRunResult(sent=False, error=str(exc), job_count=len(report.items), report=report)

    now = utc_now()
    for item in report.items:
        # `all_job_ids`, not just `job_id`: one shown entry can represent
        # the same role posted across several offices (collapsed by
        # `report._collapse_duplicate_roles`). Marking only the primary
        # would leave its siblings unnotified, and they'd come back as
        # "new" matches in tomorrow's email - the exact duplicate-
        # notification problem section 11 forbids.
        for job_id in item.all_job_ids:
            job = session.get(Job, job_id)
            if job is not None:
                job.notified = True
                job.notification_date = now

    session.add(
        EmailHistory(
            sent_at=now, recipient=email_config.recipient, subject=report.subject,
            job_count=len(report.items), job_match_ids=report.job_match_ids,
            status="sent", html_body=report.html_body,
        )
    )
    session.flush()
    logger.info("Daily email sent to %s with %d job(s).", email_config.recipient, len(report.items))
    return EmailRunResult(sent=True, job_count=len(report.items), report=report)


def send_test_email(session, context) -> None:
    """Section 29: "Send Test Email" - sends a tiny, clearly-labeled
    message using the current SMTP settings, independent of match
    scores/thresholds, purely to verify credentials work."""
    email_config = resolve_email_config(session, context)
    subject = "AI Job Finder — Test Email"
    text = (
        "This is a test email from AI Job Finder.\n\n"
        "If you're reading this, your SMTP settings are configured correctly and your "
        "daily job report will be delivered to this address."
    )
    html = (
        "<div style=\"font-family:sans-serif;padding:24px;\">"
        "<h2 style=\"color:#111827;\">AI Job Finder — Test Email</h2>"
        "<p style=\"color:#4b5563;\">If you're reading this, your SMTP settings are configured "
        "correctly and your daily job report will be delivered to this address.</p></div>"
    )
    send_email(email_config, subject, html, text)
