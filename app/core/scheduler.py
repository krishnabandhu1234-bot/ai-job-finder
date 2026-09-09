"""Background scheduling (section 13/8's Scheduler page).

Uses APScheduler's `BackgroundScheduler`, which runs jobs on its own
worker thread pool - independent of the Qt event loop, so scheduled
scans keep working even while the user is on a different page (or, once
Windows startup registration is set up via Settings, before they've
opened the UI at all today).

This process only runs while AI Job Finder is running. There is no
Windows Task Scheduler integration (section 13: "If the application is
closed, explain how scheduled execution works") - the honest behavior,
documented in the Scheduler page, is: enable "Start with Windows" in
Settings so the app (and this scheduler) is running in the background
from login, and it will fire at the configured time.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.constants import ScanTrigger, ScheduleFrequency

logger = logging.getLogger(__name__)

_JOB_ID = "aijobfinder-scan"


class AppScheduler:
    def __init__(self, context):
        self.context = context
        self._scheduler = BackgroundScheduler()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._scheduler.start()
        self._started = True
        self.reload()
        logger.info("Scheduler started.")

    def shutdown(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False

    def reload(self) -> None:
        """Re-reads scheduler/email settings from the database and
        reconfigures the job accordingly - called at startup and again
        whenever the user saves the Scheduler or Email Settings page, so
        a change takes effect without restarting the app."""
        if not self._started:
            return

        if self._scheduler.get_job(_JOB_ID):
            self._scheduler.remove_job(_JOB_ID)

        from app.database.db import session_scope

        with session_scope() as session:
            repo = self.context.settings_repo
            enabled = repo.get_bool(session, "scheduler.enabled", False)
            frequency = repo.get(session, "scheduler.frequency", ScheduleFrequency.DAILY.value)
            send_time = repo.get(session, "email.send_time", "07:00")
            timezone = repo.get(session, "email.timezone", "America/Los_Angeles")

        if not enabled or frequency == ScheduleFrequency.MANUAL_ONLY.value:
            logger.info("Scheduled scans are disabled.")
            return

        try:
            hour, minute = (int(p) for p in send_time.split(":"))
        except ValueError:
            hour, minute = 7, 0

        if frequency == ScheduleFrequency.EVERY_12_HOURS.value:
            trigger = IntervalTrigger(hours=12)
        elif frequency == ScheduleFrequency.WEEKLY.value:
            trigger = CronTrigger(day_of_week="mon", hour=hour, minute=minute, timezone=timezone)
        else:  # DAILY
            trigger = CronTrigger(hour=hour, minute=minute, timezone=timezone)

        self._scheduler.add_job(
            self._run, trigger=trigger, id=_JOB_ID, replace_existing=True,
            kwargs={"scan_trigger": ScanTrigger.SCHEDULED.value},
        )
        logger.info("Scheduled scans enabled: frequency=%s, trigger=%s", frequency, trigger)

    def next_run_time(self):
        """The next time the scheduled pipeline will fire, or `None` if
        scheduling is disabled/manual-only - used by the Dashboard to show
        "Next scheduled scan" without reaching into APScheduler internals."""
        job = self._scheduler.get_job(_JOB_ID) if self._started else None
        return job.next_run_time if job else None

    def run_now_async(self) -> None:
        """Fires the full pipeline immediately on the scheduler's thread
        pool, independent of the configured trigger - used for testing
        the schedule without waiting. Recorded as a MANUAL run (not
        SCHEDULED) so History accurately reflects that the user triggered
        it, not the cron/interval trigger."""
        self._scheduler.add_job(
            self._run, id=f"{_JOB_ID}-manual", replace_existing=True,
            kwargs={"scan_trigger": ScanTrigger.MANUAL.value},
        )

    def _run(self, scan_trigger: str = ScanTrigger.SCHEDULED.value) -> None:
        from app.core.pipeline import run_full_pipeline

        try:
            run_full_pipeline(self.context, trigger=scan_trigger)
        except Exception:
            logger.exception("Scheduled pipeline run failed unexpectedly.")


_instance: AppScheduler | None = None


def init_scheduler(context) -> AppScheduler:
    global _instance
    _instance = AppScheduler(context)
    _instance.start()
    return _instance


def get_scheduler() -> AppScheduler | None:
    return _instance
