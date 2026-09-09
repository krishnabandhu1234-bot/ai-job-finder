"""Demo Mode example jobs (section 28).

These are illustrative, hand-authored example postings for trying out the
app without any real job source configured or any API key. They are NOT
real job listings and are never presented as such:

  - every "company" here is an obviously fictional placeholder name
    (never a real company - see section 32/33: never invent jobs and
    never misattribute them to a real employer),
  - every apply/company URL points at a clearly-marked example.com page
    rather than a real destination,
  - `JobSourceConfig.source_type` is "demo", which the UI uses to render
    a persistent "DEMO DATA" badge wherever these appear, and this source
    is only ever enabled when `AppConfig.demo_mode` is True.
"""

from __future__ import annotations

import datetime as dt

from app.core.constants import SourceType
from app.database.models import utc_now
from app.jobs.source import JobSource, RawJobPosting

_EXAMPLE_POSTINGS = [
    dict(
        external_job_id="demo-1",
        company="Example Aerospace Co.",
        title="Principal Thermal Engineer",
        description=(
            "Example Aerospace Co. (a fictional company for demo purposes) is looking for a "
            "Principal Thermal Engineer to lead thermal analysis for next-generation satellite "
            "payloads. You'll own thermal architecture decisions, mentor a team of engineers, and "
            "work closely with structures and power teams."
        ),
        requirements=[
            "10+ years of thermal/CFD engineering experience",
            "Deep expertise with ANSYS Fluent and/or OpenFOAM",
            "Experience with satellite or spacecraft thermal control systems",
        ],
        preferred_qualifications=["M.S. or Ph.D. in Mechanical/Aerospace Engineering", "Python scripting for simulation automation"],
        location_raw="Austin, TX",
        employment_type_raw="Full-time",
        salary_min=170000,
        salary_max=210000,
        salary_currency="USD",
        days_ago=1,
    ),
    dict(
        external_job_id="demo-2",
        company="Northwind Robotics (Example)",
        title="Senior Simulation Architect",
        description=(
            "Northwind Robotics (a fictional company for demo purposes) is hiring a Senior "
            "Simulation Architect to design and scale our multiphysics simulation platform used "
            "across robotics product lines."
        ),
        requirements=[
            "8+ years building simulation software or leading simulation engineering",
            "Strong background in multiphysics simulation (CFD, FEA, or similar)",
            "Proficiency in C++ or Python for simulation tooling",
        ],
        preferred_qualifications=["Experience with cloud-scale distributed simulation"],
        location_raw="Remote - United States",
        employment_type_raw="Full-time",
        salary_min=180000,
        salary_max=225000,
        salary_currency="USD",
        days_ago=2,
    ),
    dict(
        external_job_id="demo-3",
        company="BluePeak Data Systems (Example)",
        title="AI Solutions Architect",
        description=(
            "BluePeak Data Systems (a fictional company for demo purposes) needs an AI Solutions "
            "Architect to design and deploy machine learning systems for enterprise clients, from "
            "requirements gathering through production deployment."
        ),
        requirements=[
            "7+ years of ML engineering or applied AI experience",
            "Experience with PyTorch or TensorFlow in production",
            "Strong client-facing communication skills",
        ],
        preferred_qualifications=["Experience with LLM-based systems", "Prior consulting or solutions architecture experience"],
        location_raw="New York, NY",
        employment_type_raw="Full-time",
        salary_min=160000,
        salary_max=200000,
        salary_currency="USD",
        days_ago=1,
    ),
    dict(
        external_job_id="demo-4",
        company="Meridian Cloud Labs (Example)",
        title="Machine Learning Engineer",
        description=(
            "Meridian Cloud Labs (a fictional company for demo purposes) is building ML "
            "infrastructure for real-time recommendation systems and is looking for an ML "
            "Engineer to join the core platform team."
        ),
        requirements=[
            "3+ years of ML engineering experience",
            "Experience with feature stores and online inference",
        ],
        preferred_qualifications=["Experience with Kubernetes-based ML platforms"],
        location_raw="Toronto, Canada",
        employment_type_raw="Full-time",
        salary_min=None,
        salary_max=None,
        salary_currency="",
        days_ago=3,
    ),
    dict(
        external_job_id="demo-5",
        company="Riverstone Manufacturing (Example)",
        title="CFD Engineer",
        description=(
            "Riverstone Manufacturing (a fictional company for demo purposes) is seeking a CFD "
            "Engineer to support product development for industrial cooling systems."
        ),
        requirements=["3-5 years of CFD experience", "Proficiency with ANSYS Fluent"],
        preferred_qualifications=["Experience with heat exchanger design"],
        location_raw="Bangalore, India",
        employment_type_raw="Full-time",
        salary_min=1800000,
        salary_max=2600000,
        salary_currency="INR",
        days_ago=5,
    ),
]


class DemoSource(JobSource):
    """Only ever instantiated/enabled when AppConfig.demo_mode is True -
    see app/jobs/scan_orchestrator.py."""

    source_type = SourceType.DEMO.value

    def _fetch(self) -> list[RawJobPosting]:
        now = utc_now()
        postings = []
        for item in _EXAMPLE_POSTINGS:
            posted_date = now - dt.timedelta(days=item.get("days_ago", 0))
            postings.append(
                RawJobPosting(
                    external_job_id=item["external_job_id"],
                    company=item["company"],
                    title=item["title"],
                    description=item["description"],
                    requirements=item.get("requirements", []),
                    preferred_qualifications=item.get("preferred_qualifications", []),
                    location_raw=item.get("location_raw", ""),
                    employment_type_raw=item.get("employment_type_raw", ""),
                    salary_min=item.get("salary_min"),
                    salary_max=item.get("salary_max"),
                    salary_currency=item.get("salary_currency", ""),
                    posted_date=posted_date,
                    apply_url=f"https://example.com/demo-jobs/{item['external_job_id']}",
                    company_url="https://example.com/demo-company",
                    raw_source_data={"demo": True},
                )
            )
        return postings
