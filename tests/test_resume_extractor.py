"""Tests for structured field extraction from raw resume text."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from app.resume.extractor import extract_resume

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_TEXT = (FIXTURES_DIR / "sample_resume.txt").read_text(encoding="utf-8")

REFERENCE_DATE = dt.date(2024, 6, 1)  # fixed "today" so years-of-experience math is deterministic


def _extract():
    return extract_resume(SAMPLE_TEXT, reference_date=REFERENCE_DATE)


def test_extracts_contact_info():
    result = _extract()
    assert result.contact.name == "Jordan Smith"
    assert result.contact.email == "jordan.smith@example.com"
    assert "555-0199" in result.contact.phone
    assert "linkedin.com/in/jordansmith" in result.contact.linkedin


def test_extracts_experience_entries_in_document_order():
    result = _extract()
    assert len(result.experience) == 2
    assert result.experience[0].title == "Senior Thermal Engineer"
    assert result.experience[0].company == "Acme Aerospace"
    assert result.experience[1].title == "Thermal Engineer"
    assert result.experience[1].company == "Beta Dynamics"


def test_extracts_bullets_per_role():
    result = _extract()
    acme_bullets = result.experience[0].bullets
    assert any("18%" in b for b in acme_bullets)
    assert any("40%" in b for b in acme_bullets)
    assert len(acme_bullets) == 3


def test_computes_merged_years_of_experience():
    result = _extract()
    # Jun 2015 - Dec 2019 (Beta) is adjacent to Jan 2020 - Present (Acme) as
    # of the reference date, so total experience is one continuous span:
    # Jun 2015 through Jun 2024 = 9.0 years, not the sum of both intervals
    # counted separately (which would double count nothing here, but
    # verifies the merge logic doesn't under/over count adjacent roles).
    assert result.years_experience == 9.0


def test_infers_target_roles_from_titles():
    result = _extract()
    assert result.target_roles == ["Senior Thermal Engineer", "Thermal Engineer"]


def test_extracts_companies():
    result = _extract()
    assert result.companies == ["Acme Aerospace", "Beta Dynamics"]


def test_extracts_education_with_institution_and_year():
    result = _extract()
    assert len(result.education) == 2
    ms = result.education[0]
    assert ms.degree == "M.S."
    assert ms.institution == "Stanford University"
    assert ms.year == "2015"

    bs = result.education[1]
    assert bs.institution == "University of Texas at Austin"
    assert bs.year == "2013"


def test_extracts_skills_from_curated_taxonomy():
    result = _extract()
    assert "ANSYS" in result.technical_skills
    assert "OpenFOAM" in result.technical_skills
    assert "SolidWorks" in result.technical_skills
    assert "Python" in result.programming_languages
    assert "MATLAB" in result.programming_languages


def test_extracts_certifications():
    result = _extract()
    assert "Six Sigma" in result.certifications


def test_extracts_projects_and_publications():
    result = _extract()
    assert any("Satellite Thermal Control" in p for p in result.projects)
    assert any("Advances in Satellite Thermal Modeling" in p for p in result.publications)


def test_extracts_leadership_signal():
    result = _extract()
    assert any("managed a team" in item.lower() for item in result.leadership)


def test_extracts_achievements_with_metrics_only():
    result = _extract()
    assert all(any(ch.isdigit() for ch in a) for a in result.achievements)
    assert any("18%" in a for a in result.achievements)


def test_sections_found_matches_sample_resume_headers():
    result = _extract()
    assert set(result.sections_found) == {
        "certifications", "education", "experience", "projects",
        "publications", "skills", "summary",
    }


def test_handles_empty_text_gracefully():
    result = extract_resume("", reference_date=REFERENCE_DATE)
    assert result.experience == []
    assert result.years_experience == 0.0
    assert result.technical_skills == []


def test_handles_text_with_no_recognizable_sections():
    result = extract_resume("Just some random text with no structure.", reference_date=REFERENCE_DATE)
    assert result.experience == []
    assert result.education == []
