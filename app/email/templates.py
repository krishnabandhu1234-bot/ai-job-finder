"""Daily email content generation (section 11).

Pure functions - no SMTP/network here, so both the real sender and the
"Preview Daily Email" button in the UI render from exactly the same
code path and can never drift apart.

Every job shown here must come from a real `Job`/`JobMatch` row (section
32: no fake jobs) - this module never invents content, it only formats
what's already in the database.
"""

from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass, field


@dataclass
class ReportItem:
    match_id: int
    job_id: int
    title: str
    company: str
    location: str
    remote: bool
    overall_score: float
    category: str
    salary_text: str
    posted_date: dt.datetime | None
    apply_url: str
    strengths: list[str]
    gaps: list[str]
    reasoning: str
    # Companies routinely post one role once per office, which the
    # deduplicator correctly keeps as distinct `Job` rows (distinct
    # locations, distinct apply URLs) but which a reader experiences as
    # the same job five times. `build_daily_report` collapses those into
    # a single item; these carry the ones that were folded in, so the
    # sender still marks every underlying posting as notified (otherwise
    # the copies resurface in tomorrow's email) and the reader can see
    # every location the role is open in.
    other_locations: list[str] = field(default_factory=list)
    duplicate_job_ids: list[int] = field(default_factory=list)
    duplicate_match_ids: list[int] = field(default_factory=list)

    @property
    def all_job_ids(self) -> list[int]:
        return [self.job_id, *self.duplicate_job_ids]

    @property
    def all_match_ids(self) -> list[int]:
        return [self.match_id, *self.duplicate_match_ids]

    @property
    def location_display(self) -> str:
        """Every location this role is open in, deduplicated and in a
        stable order, e.g. "San Francisco, CA + 4 other locations"."""
        base = self.location or ("Remote" if self.remote else "Location unspecified")
        if not self.other_locations:
            return base
        return f"{base} (+{len(self.other_locations)} other location{'s' if len(self.other_locations) > 1 else ''})"


def _e(text: str) -> str:
    return html.escape(text or "", quote=True)


def _score_color(score: float) -> str:
    if score >= 95:
        return "#7c3aed"
    if score >= 90:
        return "#2563eb"
    if score >= 85:
        return "#059669"
    if score >= 75:
        return "#d97706"
    return "#6b7280"


def format_salary(salary_min: float | None, salary_max: float | None, currency: str) -> str:
    if salary_min is None and salary_max is None:
        return "Unknown"
    currency = currency or ""
    if salary_min is not None and salary_max is not None and salary_min != salary_max:
        return f"{currency} {salary_min:,.0f} - {salary_max:,.0f}".strip()
    value = salary_min if salary_min is not None else salary_max
    return f"{currency} {value:,.0f}".strip()


def render_subject(item_count: int, generated_at: dt.datetime) -> str:
    date_str = generated_at.strftime("%B %d, %Y")
    if item_count == 0:
        return f"AI Job Finder — No new high-match jobs today — {date_str}"
    noun = "Job" if item_count == 1 else "Jobs"
    return f"AI Job Finder — {item_count} New High-Match {noun} — {date_str}"


def render_text_body(
    items: list[ReportItem], generated_at: dt.datetime, update_notice: str = ""
) -> str:
    lines = [render_subject(len(items), generated_at), ""]
    if not items:
        lines.append("No new jobs met your minimum match score since the last report.")
        if update_notice:
            lines.extend(["", update_notice])
        return "\n".join(lines)

    lines.append(f"{len(items)} new opportunit{'y' if len(items) == 1 else 'ies'} discovered:\n")
    for i, item in enumerate(items, start=1):
        lines.append(f"{i}. {item.title} — {item.company}")
        lines.append(f"   Match: {item.overall_score:.0f}% ({item.category})")
        lines.append(f"   Location: {item.location_display}{' (Remote)' if item.remote else ''}")
        lines.append(f"   Salary: {item.salary_text}")
        if item.strengths:
            lines.append(f"   Why it matches: {'; '.join(item.strengths[:3])}")
        if item.gaps:
            lines.append(f"   Potential gap: {'; '.join(item.gaps[:2])}")
        lines.append(f"   Apply: {item.apply_url}")
        lines.append("")
    if update_notice:
        lines.append(update_notice)
    return "\n".join(lines)


def _render_update_banner(update_notice: str) -> str:
    """A quiet notice that a newer version of the app exists.

    Deliberately placed at the END of the email and styled down: the
    user opened this for job matches, and an update nag competing with
    those for attention would make the email worse at its actual job."""
    if not update_notice:
        return ""
    return (
        "<div style=\"margin-top:20px;padding:12px 16px;background:#eff6ff;"
        "border-left:3px solid #2563eb;border-radius:4px;color:#1e40af;font-size:13px;\">"
        f"{_e(update_notice)}</div>"
    )


def render_html_body(
    items: list[ReportItem], generated_at: dt.datetime, update_notice: str = ""
) -> str:
    date_str = generated_at.strftime("%B %d, %Y")

    if not items:
        body = (
            "<p style=\"color:#4b5563;font-size:15px;\">No new jobs met your minimum match "
            "score since the last report. You'll hear from us as soon as something strong "
            "comes up.</p>"
        )
    else:
        cards = "".join(_render_job_card(item) for item in items)
        intro = (
            f"<p style=\"color:#4b5563;font-size:15px;margin:0 0 20px;\">"
            f"{len(items)} new opportunit{'y' if len(items) == 1 else 'ies'} discovered since your last report.</p>"
        )
        body = intro + cards

    body += _render_update_banner(update_notice)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;">
        <tr>
          <td style="background:#111827;padding:24px 32px;">
            <div style="color:#ffffff;font-size:20px;font-weight:700;">AI Job Finder</div>
            <div style="color:#9ca3af;font-size:13px;margin-top:4px;">{_e(date_str)}</div>
          </td>
        </tr>
        <tr><td style="padding:28px 32px;">{body}</td></tr>
        <tr>
          <td style="padding:16px 32px;background:#f9fafb;color:#9ca3af;font-size:12px;">
            You're receiving this because you set up AI Job Finder to search worldwide for jobs
            matching your resume. All matching runs locally on your computer.
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _render_job_card(item: ReportItem) -> str:
    color = _score_color(item.overall_score)
    location_bits = _e(item.location_display)
    if item.remote:
        location_bits += " • Remote"
    posted = item.posted_date.strftime("%b %d, %Y") if item.posted_date else "Date unknown"

    strengths_html = ""
    if item.strengths:
        strengths_html = "<div style=\"margin-top:10px;\"><b style=\"color:#059669;font-size:13px;\">Why it matches:</b><ul style=\"margin:4px 0 0;padding-left:18px;color:#374151;font-size:13px;\">"
        strengths_html += "".join(f"<li>{_e(s)}</li>" for s in item.strengths[:4])
        strengths_html += "</ul></div>"

    gaps_html = ""
    if item.gaps:
        gaps_html = "<div style=\"margin-top:8px;\"><b style=\"color:#d97706;font-size:13px;\">Potential gap:</b><ul style=\"margin:4px 0 0;padding-left:18px;color:#374151;font-size:13px;\">"
        gaps_html += "".join(f"<li>{_e(g)}</li>" for g in item.gaps[:3])
        gaps_html += "</ul></div>"

    apply_html = ""
    if item.apply_url:
        apply_html = (
            f'<a href="{_e(item.apply_url)}" style="display:inline-block;margin-top:14px;background:#3457d5;'
            f'color:#ffffff;text-decoration:none;padding:9px 18px;border-radius:6px;font-size:13px;font-weight:600;">'
            f"Apply Now</a>"
        )

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:10px;margin-bottom:16px;">
      <tr>
        <td style="padding:18px 20px;">
          <table role="presentation" width="100%"><tr>
            <td style="font-size:22px;font-weight:800;color:{color};width:70px;">{item.overall_score:.0f}%</td>
            <td>
              <div style="font-size:16px;font-weight:700;color:#111827;">{_e(item.title)}</div>
              <div style="font-size:14px;color:#4b5563;">{_e(item.company)}</div>
              <div style="font-size:12px;color:#9ca3af;margin-top:2px;">{location_bits} • {_e(item.salary_text)} • Posted {_e(posted)}</div>
            </td>
          </tr></table>
          {strengths_html}
          {gaps_html}
          {apply_html}
        </td>
      </tr>
    </table>"""
