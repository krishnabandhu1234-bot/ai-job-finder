# AI Job Finder

A local-first, AI-powered desktop application that discovers new job
postings worldwide and tells you which few are genuinely worth your time,
based on your actual resume - not keyword matching.

**What it does, end to end:** you give it your resumes (as many as you
have). It **searches job platforms** for roles matching them - across
every company on those platforms at once - pulls in the matching
postings, and adds the full job boards of the employers it finds, so it
keeps watching them. It scores every posting against your resume and
emails you the few worth your time each morning. You never supply a list
of companies, and none of that needs an API key.

Optionally pick an AI provider - Claude, OpenAI, Gemini, or a model
running on your own machine - to additionally get AI-written match
reasoning, better resume understanding, and employers whose boards
aren't searchable. It also tells you when a new version is available.

On a fresh install with no AI key, one run found **340 postings across
179 companies**, and produced a daily email topping out at a 92% match.

Windows desktop app built with PySide6 (Qt), SQLite, and a pluggable
embeddings/LLM matching pipeline. Runs entirely on your machine; external
AI calls are optional and limited to a small, final shortlist of jobs.

---

### 👉 Just want to use the app? Read **[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)**

That's a five-minute, plain-language walkthrough: install, upload your
resume, pick companies, get matches. No API keys or setup required.

The rest of this README is for people working on the code.

| Guide | For |
|---|---|
| **[Getting Started](docs/GETTING_STARTED.md)** | Using the app, start to finish |
| **[Email Setup](docs/EMAIL_SETUP.md)** | Getting the daily digest into your inbox |
| **[AI Models](docs/AI_MODELS.md)** | Local vs. paid AI providers, privacy, cost control |

---

## Current status

Feature-complete and verified end-to-end against live job boards
(743 real postings scanned, scored and assembled into a real daily
email during testing). 350 automated tests, all passing.

**What works right now:**

- Full desktop shell: sidebar navigation across all 12 planned sections
  (Dashboard, Resumes, Job Search Profile, Job Matches, Companies, Job
  Sources, Email Settings, Scheduler, AI Settings, History, Logs,
  Settings), plus a **Setup Guide** that checks the real state of each
  setup step, shows which one is still outstanding, and links straight
  to the page that fixes it. A fresh install opens on it rather than on
  a Dashboard of zeros.
- Complete local SQLite database with the full production schema (users,
  resumes, candidate profiles, jobs, embeddings, matches, preferences,
  feedback, email/scan/application history, settings), migration
  versioning, and encrypted secret storage.
- **Resumes**: upload PDF/DOCX/TXT resumes (multiple at once). Each is
  parsed, and a structured candidate profile - target roles, seniority,
  years of experience, technical skills, programming languages, software,
  certifications, education, companies, leadership signal, and
  quantified achievements - is extracted with a rule-based parser (no
  API key needed) and merged across all uploaded resumes. Every
  auto-detected field is shown to you and fully editable before it's
  saved. Optionally, **"Read My Resume with AI"** additionally has your
  configured LLM read the resume - it infers roles, seniority and domain
  expertise the fixed taxonomy can't - and merges that with the offline
  parse rather than replacing it. That is the one feature that sends
  resume text off the machine, so it's opt-in, clearly labeled, and
  disabled outright by Local-only mode. Saving also **auto-fills your
  Job Search Profile** (target
  titles, industries, locations, and a sensible band of seniority levels
  around your own) from what was extracted, so the same facts aren't
  typed twice and matching has something to work with immediately - it
  only ever fills fields still empty, so it can't overwrite a choice you
  made. Corrupt/unsupported/scanned-image files fail gracefully with a
  clear message instead of crashing.
- **Job Search Profile** is fully functional: define target titles,
  locations, work arrangement, seniority, compensation, industries,
  preferred/excluded companies, keywords, employment type, and visa/work
  authorization preferences. Saved to your local database.
- **Job search across whole platforms** (`app/jobs/job_search.py`): the
  primary way companies are found. Queries built from the candidate's
  own target titles/skills are run against the public search endpoints
  Workable and Jobicy publish, returning live postings from across every
  company on those platforms. This needs **no API key and no AI
  provider**, gives a brand-new user real matches on their first scan,
  and surfaces employers - small startups especially - that no model
  would reliably recall. Because a company only appears if it's
  advertising a matching role *right now*, live hiring activity is the
  discovery signal rather than anyone's recollection.
- **Unbounded company discovery** (`app/core/pipeline.py:run_auto_discovery`,
  `app/jobs/company_universe.py`): runs at the start of every scan,
  manual or scheduled, and has no fixed ceiling on how many companies it
  can eventually reach.

  The constraint it works around: Greenhouse, Lever, Ashby and
  SmartRecruiters serve **one company at a time** and publish no index
  of their boards (verified against the live APIs - `/v1/boards`,
  `/v1/postings` and `posting-api/search` all 404/401). So the app can
  only read a board it can already *name*, and the real problem is not
  "search every company" but "keep learning company names".

  It is therefore built as a **persisted, compounding queue**
  (`company_candidates`). Names arrive from four independent directions:
  resume-derived platform search, a sweep of the keyless job aggregators
  (Himalayas/RemoteOK/Arbeitnow/Jobicy, which index employers across
  every ATS including the unsearchable ones), the company of every job
  already ingested, and - where an LLM is configured - its suggestions.
  Each run probes a bounded batch of queued names against all five ATS
  platforms concurrently, adding the **full** board of each that
  resolves, so later scans see everything those companies post rather
  than only what matched a search term.

  The batch size paces a run; it is not a limit on coverage. Unprobed
  names wait for the next run instead of being discarded, so the watched
  set grows every single run. Measured on a fresh install: one shallow
  harvest queues **612 company names in 12 seconds**, and names come in
  faster than a run can drain them. Every board is verified against the
  real API before being stored - a hallucinated or wrong company costs
  one 404 and is dropped, and nothing unverified is ever written.
  See [docs/AI_MODELS.md](docs/AI_MODELS.md).
- **Job Sources**: five ATS connectors - Greenhouse, Lever, Ashby,
  Workable and SmartRecruiters, each against that platform's own public
  job-board API (the endpoint powering the embeddable board companies
  put on their careers page), never scraping. Add boards directly (or the
  built-in, clearly-labeled Demo source) from the UI, enable/disable
  them, and test connectivity with "Fetch Now". **Scan Now** on the
  Dashboard runs a real ingestion pass - fetch, normalize (salary/
  location/employment type), cross-source dedupe by fingerprint, and
  new-vs-already-seen job detection with reappearance handling - across
  every enabled source, with live progress, then automatically chains
  into AI matching (below) before showing a combined summary. A failing
  source never stops the others.
- **AI/ML matching engine** (the heart of the app): a real multi-layer
  pipeline in `app/ai/` -
  1. **Hard filters** (`hard_filters.py`) - excluded companies, wrong
     employment type, a large seniority mismatch, an unacceptable
     country when the role isn't remote, keyword requirements/exclusions.
     Conservative by design: unknown fields never cause a rejection.
  2. **Semantic similarity** (`embeddings.py`) - local
     sentence-transformers by default (no API key, nothing leaves your
     computer), or OpenAI/Voyage if you configure one in AI Settings.
     Embeddings are cached per job in `job_embeddings` and never
     recomputed for an unchanged posting, and run on *every* job when
     they're local/free rather than a capped shortlist, so a strong
     match is never eliminated on its title before its description is
     read. Raw cosine similarity is calibrated onto a meaningful 0-100
     scale (measured, not assumed - see `calibrate_similarity`) and
     combined so this fuzzy signal can lift a job the keyword matcher
     missed without vetoing one it confidently matched. See
     [docs/AI_MODELS.md](docs/AI_MODELS.md) for how to switch providers,
     pick a different model, or run entirely local vs. add an LLM.
  3. **Skill matching** (`skill_matcher.py`) - exact vs. related
     (transferable) vs. missing skills, not naive keyword counting.
  4. **Experience & seniority matching** (`scoring.py`).
  5. **Career trajectory** (`scoring.py`) - a 20-year veteran doesn't
     get ranked highly for an entry-level posting just because the
     keywords match.
  6. **LLM reasoning** (`llm_analyzer.py`) - Anthropic or OpenAI,
     applied only to the smallest final shortlist (cost-optimization
     funnel in `ranker.py`, section 17), with the job description always
     wrapped as inert data and an explicit prompt-injection guard - the
     model is told to never follow instructions embedded in a posting.
  Every score is grounded in real resume/job text - gaps and strengths
  are never fabricated. The combined weighted score (configurable via
  `DEFAULT_SCORE_WEIGHTS`) produces the 0-100 match and category shown
  everywhere in the UI.
- **Feedback loop** (section 16): 👍 Excellent/Good, 😐 Not interested,
  👎 Poor, 🚫 Never show similar buttons on every match's detail dialog.
  Feedback nudges a lightweight, explainable per-title-word affinity
  (`app/ai/feedback.py`) that folds into future scoring - no retraining,
  no black box.
- **Job Matches**: working filters (min score, text search) and sorting
  (best match/newest/salary/company); double-click any row for a full
  detail view - complete AI analysis, evidence-based strengths/gaps,
  an Apply button linked to the real posting, an application-status
  tracker (interested/applied/interview/rejected/offer/archived), and
  the feedback buttons above.
- **Companies** shows real per-company stats (job count, remote count,
  average posted salary where known) aggregated from whatever's been
  scanned in.
- **Daily email** (`app/email/`): a professional HTML report generated
  from real `JobMatch` rows only - title, company, match %, why it
  matches, potential gaps, salary, and an Apply link. "Preview Daily
  Email" on the Email Settings page shows exactly what would be sent
  (no send, no side effects); "Send Test Email" verifies your SMTP
  credentials independent of match scores. A job is only ever emailed
  once (`Job.notified`), and a failed send never marks anything notified
  so it's retried automatically next run. See
  [docs/EMAIL_SETUP.md](docs/EMAIL_SETUP.md) for step-by-step setup
  (Gmail/Outlook app passwords, scheduling, troubleshooting).
- **Scheduler**: a real background APScheduler instance
  (`app/core/scheduler.py`) runs the full scan → AI matching → email
  pipeline at the frequency/time/time zone you configure (daily, every
  12 hours, weekly, or manual-only), independent of which page you're
  on. "Run Full Pipeline Now" on the Scheduler page fires it immediately
  for testing. An optional **Start with Windows** toggle (Settings page)
  registers a Startup-folder shortcut in the packaged app so the
  scheduler is already running at your chosen time.
- **Email Settings** and **AI Settings** are fully functional forms
  (SMTP config, provider/model selection, API keys) - values are
  encrypted before being written to disk, and .env-derived API keys are
  never silently copied into the database.
- **History** shows real scan runs; **Logs** tails the real log file.
- Global error handling: unhandled exceptions are logged and shown to you
  instead of crashing silently; a single corrupted stored secret degrades
  gracefully instead of blocking the app from starting; every pipeline
  stage (scan/rank/email) commits and fails independently so one broken
  stage never discards another's work.

**Not implemented yet**: code signing (needs a purchased certificate, not
something this project can generate) - everything else in Phase 10 (the
`.exe`, an app icon, and an Inno Setup installer wrapper) is done, see
"Building the installer" below. The frozen `.exe` was verified end-to-end
including local (no-API-key) AI matching - see "Building the Windows
.exe" below for how a real, non-trivial PyInstaller/Python 3.12/torch
packaging bug along the way was diagnosed and fixed.

## Quick start (run from source)

Requires Python 3.11-3.12 (a real interpreter, not the Microsoft Store
stub - PyInstaller and native wheels like PySide6 don't play well with
it).

```powershell
cd ai-job-finder
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python main.py
```

The app runs in Demo Mode by default (`AIJF_DEMO_MODE=true` in `.env`),
which requires no API keys. All data is stored locally at
`%LOCALAPPDATA%\AIJobFinder` (database, logs, uploaded resumes).

Matching also runs fully locally by default (no API keys, nothing leaves
your machine). To switch to a remote embedding provider (OpenAI/Voyage)
and/or turn on LLM-written match explanations (Anthropic/OpenAI), see
**[docs/AI_MODELS.md](docs/AI_MODELS.md)**. To get the daily digest
emailed to you (Gmail/Outlook app password, scheduling), see
**[docs/EMAIL_SETUP.md](docs/EMAIL_SETUP.md)**.

## Running the tests

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
```

Tests never touch the real app data directory, the network, or any
external API - they run against a temporary SQLite database and (for any
future Qt widget tests) an offscreen Qt platform plugin, so they also run
headless in CI.

## Building the Windows .exe

```powershell
.venv\Scripts\Activate.ps1
pip install pyinstaller
pyinstaller --noconfirm packaging/aijobfinder.spec
```

Produces `dist/AIJobFinder/AIJobFinder.exe`, with the app icon at
`packaging/app_icon.ico` baked in. This is a one-folder build (not
one-file) for faster startup. The spec bundles the ML/LLM stack
(sentence-transformers, torch, anthropic, openai, voyageai) via
`collect_all()` - expect a large `dist/` folder (mostly `torch`, ~1 GB)
and always smoke-test the frozen build (upload a resume, Scan Now, and
specifically try AI matching) before shipping.

**Verify a build quickly** with the built-in self-test instead of
clicking through the whole UI by hand:

```powershell
$env:AIJF_SELFTEST=1; .\dist\AIJobFinder\AIJobFinder.exe
```

It runs headlessly (no window), checks database bootstrap, the local
embedding model, and resume parsing, and exits 0/1 - see
`app/core/selftest.py`. Results go to the log file
(`%LOCALAPPDATA%\AIJobFinder\logs\aijobfinder.log`), not the console,
since the shipped `.exe` has no attached console window. All three
checks, including the local embedding model, pass in the current build.

Getting there uncovered a genuinely deep PyInstaller + Python 3.12 +
torch/scipy packaging bug: two unrelated third-party files
(`scipy/stats/_distn_infrastructure.py`, `torch/_numpy/_ufuncs.py`) each
use a `for x in [...]: ...` idiom relying on a bare, no-argument
`dir()`/`vars()` call to see their own module's namespace - which,
**only** under PyInstaller's frozen module loader (confirmed fine when
run from source), doesn't see it, leaving the loop variable unbound and
raising `NameError`. Two different, precisely-scoped fixes in
`app/ai/embeddings.py` (a `sys.meta_path` stub for the
`scipy.stats`/`sklearn` code paths this app never actually calls, and a
temporary `vars()`/`dir()` builtin patch for the one that's genuinely
needed - `torch._numpy`, pulled in by
`transformers.modeling_utils.PreTrainedModel` itself) resolve it - see
the extensive comments at the top of `packaging/aijobfinder.spec` and on
those two functions for the full diagnosis, including which fix turned
out to be necessary for which module and why one alone wasn't enough
for both.

## Building the installer

Once you have a `dist/AIJobFinder` build (above), wrap it into a single
double-click installer with [Inno Setup 6](https://jrsoftware.org/isinfo.php)
(free):

```powershell
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

Produces `packaging\dist_installer\AIJobFinder-Setup.exe` - this is the
one file to hand a non-technical user. It installs to Program Files,
adds Start Menu/optional Desktop shortcuts, and offers to launch the app
when done. It deliberately never touches `%LOCALAPPDATA%\AIJobFinder`
(the user's resumes/database/logs), so installing, upgrading, or
uninstalling never affects a user's data - see the comments at the top
of `packaging/installer.iss`. The installer itself isn't code-signed (no
certificate is included with this project); Windows SmartScreen will
show an "unrecognized publisher" prompt until you sign it with your own
certificate.

## Project layout

```
main.py                     entry point
app/
  core/                      config, logging, security, scheduler, pipeline, startup, shared constants
  database/                   SQLAlchemy models, session mgmt, migrations, repositories
  resume/                      resume parsing
  jobs/                         job source connectors, normalization, dedup, scan orchestrator
  ai/                             hard filters, embeddings, skill/experience/career scoring,
                                    the matching funnel (ranker.py), LLM analysis, feedback learning
  email/                           templates, SMTP sender, report assembly, send orchestration
  ui/
    main_window.py                  sidebar nav shell
    theme.py                         app-wide stylesheet
    base_page.py                      shared page layout helpers
    pages/                             one module per sidebar section
packaging/
  aijobfinder.spec              PyInstaller build spec (bundles the ML/LLM stack)
tests/                            pytest suite, no external dependencies required
```

## Privacy

See the in-app **Settings** page for the full breakdown. Summary: your
resumes, candidate profile, job data, and match history never leave your
computer. If you configure an external LLM/embedding provider in **AI
Settings**, only job description text and small excerpts of your
candidate profile for the final shortlist are sent to it - never your raw
resume file. A **Local-only mode** toggle disables all external AI calls
entirely.

## Security

- No API keys or passwords are ever hardcoded or committed - see
  `.env.example`.
- Secrets entered via the UI (SMTP password, API keys) are encrypted with
  a locally-generated Fernet key before being stored in the database.
- Job posting content is always treated as untrusted data, never as
  instructions - the LLM analysis system prompt (`app/ai/llm_analyzer.py`)
  explicitly tells the model to ignore any instruction embedded in a job
  description and to base every claim only on the real profile/job text
  it was given.

## Development phases

1. **Desktop application shell** - *done*. Navigation, database, config, logging, settings persistence.
2. **Resume upload, parsing, and candidate profile extraction** - *done*. PDF/DOCX/TXT parsing, rule-based structured extraction, multi-resume merging, full review/edit UI.
3. **Job source architecture, connectors, normalization, deduplication, and new-job detection** - *done*. Greenhouse/Lever/Ashby + Demo sources, salary/location/employment-type normalization, cross-source fingerprint dedup, reappearance handling, a background-thread scan orchestrator wired to Scan Now, and per-company aggregation on the Companies page.
4. **Semantic matching** - *done*. Hard filters, pluggable embeddings (local/OpenAI/Voyage) with per-job caching, skill/experience/seniority matching in `app/ai/`.
5. **LLM reasoning layer for the final shortlist** - *done*. Anthropic/OpenAI structured-JSON analysis (`app/ai/llm_analyzer.py`), prompt-injection guarded, applied only to the funnel's smallest shortlist.
6. **Career-trajectory-aware ranking + funnel cost optimization** - *done*. `app/ai/scoring.py` (career trajectory layer) and `app/ai/ranker.py` (the hard-filter → embedding-top-N → LLM-top-K funnel, thresholds configurable via Settings).
7. **Daily email generation and sending, with preview/test-send** - *done*. `app/email/` (templates, sender, report, service), wired into Email Settings' Preview/Send Test buttons.
8. **Scheduler (daily/12h/weekly/manual) + Windows background operation** - *done*. `app/core/scheduler.py` (APScheduler) + `app/core/pipeline.py` (scan → rank → email), plus an optional Start-with-Windows shortcut (`app/core/startup.py`).
9. **Feedback-driven personalized ranking** - *done*. `app/ai/feedback.py` + feedback buttons on the Job Matches detail dialog; an application-status tracker (section 31) is included there too.
10. Windows `.exe` packaging polish + installer wrapper (icon, code signing, Inno Setup script). The `.exe` itself already builds and runs today - see below.

Each phase keeps the app fully runnable - nothing is left half-wired.
