"""Tests for merging one or more extracted resumes into a CandidateProfile."""

from __future__ import annotations

from app.core.constants import Seniority
from app.resume.extractor import EducationEntry, ExtractedResume
from app.resume.profile_builder import build_candidate_profile_fields, infer_seniority


def _resume(**overrides) -> ExtractedResume:
    base = ExtractedResume(
        target_roles=["Software Engineer"],
        years_experience=3.0,
        technical_skills=["Docker"],
        programming_languages=["Python"],
        software=["Git"],
        certifications=[],
        companies=["Acme Corp"],
        leadership=[],
        achievements=["Shipped feature X, +20% engagement"],
        education=[EducationEntry(degree="B.S.", institution="MIT", year="2018")],
        projects=["Side project A"],
        publications=[],
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_single_resume_maps_straight_through():
    fields = build_candidate_profile_fields([(1, _resume())])

    assert fields["source_resume_ids"] == [1]
    assert fields["target_roles"] == ["Software Engineer"]
    assert fields["technical_skills"] == ["Docker"]
    assert fields["companies"] == ["Acme Corp"]
    assert fields["years_experience"] == 3.0
    assert fields["education"] == ["B.S. - MIT"]


def test_multiple_resumes_are_merged_and_deduplicated():
    resume_a = _resume(
        technical_skills=["Docker", "Kubernetes"],
        companies=["Acme Corp"],
        years_experience=3.0,
    )
    resume_b = _resume(
        technical_skills=["kubernetes", "Terraform"],  # case-insensitive duplicate of "Kubernetes"
        companies=["Acme Corp", "Beta Inc"],  # duplicate + new
        years_experience=5.0,
    )

    fields = build_candidate_profile_fields([(1, resume_a), (2, resume_b)])

    assert fields["source_resume_ids"] == [1, 2]
    assert fields["technical_skills"] == ["Docker", "Kubernetes", "Terraform"]
    assert fields["companies"] == ["Acme Corp", "Beta Inc"]
    # Years of experience takes the max across resumes, not the sum - two
    # resumes describing the same person's overlapping career should not
    # double their experience.
    assert fields["years_experience"] == 5.0


def test_achievements_are_capped_and_deduplicated():
    resume = _resume(achievements=[f"Achievement {i}, grew revenue {i}%" for i in range(30)])
    fields = build_candidate_profile_fields([(1, resume)])
    assert len(fields["achievements"]) == 20


def test_infer_seniority_uses_title_markers_first():
    assert infer_seniority(2.0, ["Engineering Director"]) == Seniority.DIRECTOR
    assert infer_seniority(20.0, ["Staff Software Engineer"]) == Seniority.STAFF
    assert infer_seniority(1.0, ["VP of Engineering"]) == Seniority.VP


def test_infer_seniority_falls_back_to_years_of_experience():
    assert infer_seniority(0.5, ["Software Engineer"]) == Seniority.ENTRY
    assert infer_seniority(5.0, ["Software Engineer"]) == Seniority.MID
    assert infer_seniority(10.0, ["Software Engineer"]) == Seniority.SENIOR
    assert infer_seniority(18.0, ["Software Engineer"]) == Seniority.PRINCIPAL


def test_infer_seniority_with_no_experience_or_titles():
    assert infer_seniority(0.0, []) == Seniority.ANY
