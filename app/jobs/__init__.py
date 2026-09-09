"""Job source ingestion, normalization, and deduplication (Phase 3 - done).

  source.py             - JobSource abstract base class, RawJobPosting, SourceFetchResult
  http_client.py          - shared rate-limited/retrying HTTP client + robots.txt check
  html_text.py               - HTML description -> plain text
  greenhouse.py                - Greenhouse public job-board API source
  lever.py                       - Lever public postings API source
  ashby.py                         - Ashby public job-board API source
  demo_source.py                     - clearly-labeled example postings for Demo Mode
  normalizer.py                        - raw source payload -> common Job schema (salary/location/etc)
  deduplicator.py                        - cross-source fingerprinting, new-job/reappearance detection
  scan_orchestrator.py                     - runs fetch -> normalize -> dedupe across all enabled sources

Not yet implemented: CompanyCareerPagesSource, WorkdaySource, and other
public job APIs - the JobSource interface is designed so adding one means
a new module here, not touching the orchestrator.
"""
