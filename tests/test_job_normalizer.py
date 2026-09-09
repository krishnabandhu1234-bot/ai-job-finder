"""Tests for salary/location/employment-type normalization and the
cross-source dedup fingerprint."""

from __future__ import annotations

import datetime as dt

from app.jobs.normalizer import (
    compute_fingerprint,
    infer_job_seniority,
    normalize_employment_type,
    normalize_posting,
    parse_epoch_millis,
    parse_iso_datetime,
    parse_location,
    parse_salary,
    to_naive_utc,
)
from app.jobs.source import RawJobPosting


def test_parse_salary_range_with_dollar_sign():
    assert parse_salary("$120,000 - $150,000") == (120000.0, 150000.0, "USD")


def test_parse_salary_range_with_k_suffix():
    assert parse_salary("$120k - $150k") == (120000.0, 150000.0, "USD")


def test_parse_salary_range_with_currency_code():
    assert parse_salary("Salary: INR 1,800,000 - 2,600,000") == (1800000.0, 2600000.0, "INR")


def test_parse_salary_handles_reversed_range():
    salary_min, salary_max, currency = parse_salary("$150,000 - $120,000")
    assert salary_min == 120000.0
    assert salary_max == 150000.0


def test_parse_salary_single_value():
    assert parse_salary("Compensation: $140,000") == (140000.0, 140000.0, "USD")


def test_parse_salary_returns_none_when_absent():
    assert parse_salary("We offer competitive compensation and great benefits.") == (None, None, "")
    assert parse_salary("") == (None, None, "")


def test_parse_location_city_state_country():
    assert parse_location("Austin, TX, United States") == ("Austin", "TX", "United States", False)


def test_parse_location_city_state_infers_us():
    assert parse_location("Austin, TX") == ("Austin", "TX", "United States", False)


def test_parse_location_city_country():
    assert parse_location("Bangalore, India") == ("Bangalore", "", "India", False)


def test_parse_location_detects_remote():
    city, state, country, remote = parse_location("Remote - United States")
    assert remote is True


def test_parse_location_remote_worldwide_has_no_place():
    city, state, country, remote = parse_location("Remote")
    assert remote is True
    assert city == "" and state == "" and country == ""


def test_parse_location_single_ambiguous_token_is_city_not_guessed():
    assert parse_location("Springfield") == ("Springfield", "", "", False)


def test_parse_location_empty_string():
    assert parse_location("") == ("", "", "", False)


def test_normalize_employment_type():
    assert normalize_employment_type("Full-time") == "full_time"
    assert normalize_employment_type("Part Time") == "part_time"
    assert normalize_employment_type("Contractor") == "contract"
    assert normalize_employment_type("Internship") == "internship"
    assert normalize_employment_type("Temp") == "temporary"
    assert normalize_employment_type("") == ""  # unknown, never guessed


def test_compute_fingerprint_is_stable_and_case_insensitive():
    a = compute_fingerprint("Acme Corp", "Senior Engineer", "Austin, TX")
    b = compute_fingerprint("acme corp", "senior engineer", "austin, tx")
    assert a == b


def test_compute_fingerprint_differs_for_different_jobs():
    a = compute_fingerprint("Acme Corp", "Senior Engineer", "Austin, TX")
    b = compute_fingerprint("Acme Corp", "Junior Engineer", "Austin, TX")
    assert a != b


def test_to_naive_utc_strips_tzinfo():
    aware = dt.datetime(2024, 1, 1, 12, 0, tzinfo=dt.timezone.utc)
    naive = to_naive_utc(aware)
    assert naive.tzinfo is None
    assert naive == dt.datetime(2024, 1, 1, 12, 0)


def test_parse_iso_datetime():
    assert parse_iso_datetime("2024-03-15T10:30:00Z") == dt.datetime(2024, 3, 15, 10, 30)
    assert parse_iso_datetime(None) is None
    assert parse_iso_datetime("not a date") is None


def test_parse_epoch_millis():
    # 2024-01-01T00:00:00Z in epoch milliseconds
    assert parse_epoch_millis(1704067200000) == dt.datetime(2024, 1, 1, 0, 0)
    assert parse_epoch_millis(None) is None
    assert parse_epoch_millis("not a number") is None


def test_normalize_posting_produces_job_kwargs():
    raw = RawJobPosting(
        external_job_id="123",
        company="Acme Corp",
        title="Senior Engineer",
        description="Great job",
        location_raw="Austin, TX",
        employment_type_raw="Full-time",
        salary_raw_text="$120,000 - $150,000",
        apply_url="https://example.com/apply",
    )
    fields = normalize_posting(raw, source_id=1)

    assert fields["company"] == "Acme Corp"
    assert fields["city"] == "Austin"
    assert fields["state_province"] == "TX"
    assert fields["country"] == "United States"
    assert fields["remote"] is False
    assert fields["employment_type"] == "full_time"
    assert fields["salary_min"] == 120000.0
    assert fields["salary_max"] == 150000.0
    assert fields["salary_currency"] == "USD"
    assert fields["source_id"] == 1


def test_normalize_posting_prefers_structured_salary_over_text():
    raw = RawJobPosting(
        external_job_id="123", company="Acme", title="Eng",
        salary_min=100000, salary_max=130000, salary_currency="USD",
        salary_raw_text="this text should be ignored: $999,000",
    )
    fields = normalize_posting(raw, source_id=1)
    assert fields["salary_min"] == 100000
    assert fields["salary_max"] == 130000


def test_normalize_posting_remote_hint_overrides_location_parsing():
    raw = RawJobPosting(
        external_job_id="123", company="Acme", title="Eng",
        location_raw="Austin, TX", remote_hint=True,
    )
    fields = normalize_posting(raw, source_id=1)
    assert fields["remote"] is True
    assert fields["work_arrangement"] == "remote"


# ---------------------------------------------------------------------------
# Seniority inference from job titles
# ---------------------------------------------------------------------------
# Job boards essentially never publish seniority as a structured field.
# Leaving it empty made three scoring layers (experience, seniority,
# career trajectory - 40% of the total weight) fall back to their
# neutral "unknown" defaults for EVERY real job, capping even a perfect
# match well below the "excellent" band.


def test_infer_job_seniority_reads_common_levels():
    assert infer_job_seniority("Senior Software Engineer") == "senior"
    assert infer_job_seniority("Staff Software Engineer, Kubernetes Platform") == "staff"
    assert infer_job_seniority("Principal Thermal Engineer") == "principal"
    assert infer_job_seniority("Engineering Manager") == "manager"
    assert infer_job_seniority("Director of Engineering") == "director"
    assert infer_job_seniority("VP of Product") == "vp"
    assert infer_job_seniority("Chief Technology Officer") == "executive"
    assert infer_job_seniority("Software Engineering Intern") == "entry"
    assert infer_job_seniority("Junior Data Analyst") == "entry"


def test_infer_job_seniority_prefers_the_more_senior_marker():
    """"Senior Engineering Manager" is a manager role, not an IC senior
    one - the more senior marker has to win."""
    assert infer_job_seniority("Senior Engineering Manager") == "manager"
    assert infer_job_seniority("Senior Staff Engineer") == "staff"


def test_infer_job_seniority_is_word_boundary_safe():
    """A plain substring test reads "cto" out of "dire-cto-r" and "sr"
    out of "u-sr-name", which would badly misclassify roles."""
    assert infer_job_seniority("Director, Data Platform") == "director"  # not executive via "cto"
    assert infer_job_seniority("Usrname Systems Engineer") == ""  # not senior via "sr"
    assert infer_job_seniority("Leadership Development Partner") == ""  # not lead via "lead"


def test_infer_job_seniority_returns_empty_when_the_title_says_nothing():
    """Honest unknown beats a guess - the scoring layers stay neutral for
    an empty value rather than inventing a level (section 33)."""
    assert infer_job_seniority("Software Engineer") == ""
    assert infer_job_seniority("Research Engineer, Machine Learning") == ""
    assert infer_job_seniority("") == ""


def test_normalize_posting_populates_seniority():
    raw = RawJobPosting(
        external_job_id="1", company="Acme", title="Staff Software Engineer, Backend",
        description="Build things.",
    )
    fields = normalize_posting(raw, source_id=1)
    assert fields["seniority"] == "staff"
