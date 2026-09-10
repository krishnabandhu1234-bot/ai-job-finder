# AI Models: local vs. paid providers

Reference documentation for the AI side of the app - which models it can
use, what each costs, what leaves your computer, and how to control it.

**New to the app?** Start with
**[GETTING_STARTED.md](GETTING_STARTED.md)** instead - it walks through
setup end to end and only mentions AI where it matters. Come here when
you want the detail.

---

## The two AI settings

AI Job Finder has two independent AI knobs, and you can mix and match
them freely:

| Knob | Used for | Runs during |
|---|---|---|
| **Embedding provider** | Layer 2 semantic similarity - comparing your candidate profile to a job's text | Every job that survives hard filters + the heuristic score (the "shortlist", not all 10,000 jobs - see the funnel below) |
| **LLM provider** | Layer 6 reasoning, plus "Find Companies" and "Read My Resume with AI" | Only the very top of the match shortlist (~10-50 jobs/day) for Layer 6; on demand for the other two |

Embeddings default to **fully local, zero-API-key, zero-cost**
operation already. LLM provider defaults to `none` (off) - turn it on
using either a paid provider (sections 2-3) or, for zero cost and
nothing sent anywhere, **a model on your own computer** (section 1b).

Everything below can be set either from the app's **AI Settings** page
(recommended - values are encrypted and stored in the local database) or
via environment variables in `.env` (see `.env.example`). The AI
Settings page always wins if both are set.

---

## 1. Running fully local (default, no API keys)

This is what you get out of the box:

- **Embeddings**: `sentence-transformers` (`all-MiniLM-L6-v2`) runs on
  your CPU. Nothing about your resume or the jobs it's compared against
  ever leaves your machine.
- **LLM reasoning**: off. Layer 6 simply doesn't run; every job match
  still gets a full score and a rule-based "why it matches" explanation
  from Layers 1-5 (hard filters, skills, experience, seniority, career
  trajectory) - just not an LLM-written paragraph.

To make this explicit and guarantee no PAID/external AI call is ever
made (even if you'd previously entered API keys), turn on **"Local-only
mode"** at the top of the AI Settings page. That flag is checked before
every embedding/LLM call and short-circuits to local-only regardless of
what provider is selected below it - **with one deliberate exception**:
a `local` LLM provider (section 1b below) still works even with this on,
since a model running on your own machine already satisfies the promise
this toggle makes.

Nothing to configure - this is the default (`AIJF_EMBEDDING_PROVIDER=local`,
`AIJF_LLM_PROVIDER=none` in `.env.example`).

## 1b. Running an LLM locally too (Ollama/LM Studio - no API key, no cost)

Embeddings run locally by default already (above). This section is about
the OTHER AI knob - LLM reasoning, "Find Companies", and "Read My Resume
with AI" - which otherwise needs a paid Anthropic/OpenAI key. You can
point all three at a model on your own computer instead.

**How it works:** most local model runners (Ollama, LM Studio, llama.cpp's
built-in server, vLLM, ...) expose the same API shape OpenAI's does -
`/v1/chat/completions`. The app talks to that, so it works with any of
them without needing a dedicated integration per tool.

### Setup (using Ollama - free, the simplest option)

1. Install Ollama: **https://ollama.com/download** (Windows installer).
2. Open a terminal and pull a model - anything reasonably capable works
   for this app's purposes, e.g.:
   ```powershell
   ollama pull llama3.1
   ```
   Ollama then runs a local server automatically at
   `http://localhost:11434`.
3. In the app, **AI Settings** → set **LLM provider** to `local`.
4. Set **LLM model** to the exact name you pulled - `llama3.1`.
5. Leave **Local LLM endpoint URL** at its default,
   `http://localhost:11434/v1` (this is what Ollama's OpenAI-compatible
   endpoint listens on - LM Studio's default is
   `http://localhost:1234/v1` instead, if you use that).
6. Click **Save AI Settings**.

That's it - "Find Companies", "Read My Resume with AI", and Layer 6
match reasoning now all run against your local model, for $0, with
nothing sent anywhere, and it keeps working even with Local-only mode
checked.

### What to expect

- **No API key needed at all** - the endpoint URL is the only thing that
  matters. (The app does send a dummy placeholder key under the hood,
  because the `openai` client library requires *some* non-empty string;
  Ollama/LM Studio ignore it - there's nothing to authenticate on your
  own machine.)
- **Quality depends entirely on the model you pick and your hardware.** A
  small model (7-8B parameters) on a laptop CPU will be slower and less
  reliable at following the JSON-output instructions than Claude/GPT-4
  are - expect more `[FAIL]`-style skips on individual jobs than with a
  hosted provider. A larger model, or a GPU, helps a lot.
- **Nothing happens silently if it's misconfigured.** If Ollama isn't
  running, the model wasn't pulled, or the URL is wrong, the relevant
  feature reports a clear error (e.g. "Local LLM call to
  http://localhost:11434/v1 failed: ... (is Ollama/LM Studio running,
  and is the model pulled?)") rather than pretending to work.
- Env var equivalents (`.env`):
  ```
  AIJF_LLM_PROVIDER=local
  AIJF_LLM_MODEL=llama3.1
  AIJF_LOCAL_LLM_BASE_URL=http://localhost:11434/v1
  ```

### Choosing a different local embedding model

Any [sentence-transformers model](https://www.sbert.net/docs/sentence_transformer/pretrained_models.html)
works - set **Embedding model** on the AI Settings page (or
`AIJF_EMBEDDING_MODEL` in `.env`) to its Hugging Face model id, e.g.:

```
all-MiniLM-L6-v2      # default - fast, 384 dims, good general quality
all-mpnet-base-v2      # slower, 768 dims, noticeably better quality
multi-qa-mpnet-base-dot-v1   # tuned for matching a query against a longer document (arguably closer to "resume vs. job description")
```

The first time a new model is used it downloads from Hugging Face
(requires internet once, then it's cached locally under
`%USERPROFILE%\.cache\huggingface`); after that, matching runs fully
offline again.

---

## 2. Remote embedding providers (better semantic quality, small cost)

Set **Embedding provider** to `openai` or `voyage` on the AI Settings
page, add the matching API key, and optionally set a model name.

| Provider | Get a key | Default model | Typical cost |
|---|---|---|---|
| OpenAI | https://platform.openai.com/api-keys | `text-embedding-3-small` | ~$0.02 per 1M tokens - a few cents/month for typical usage |
| Voyage AI | https://dash.voyageai.com | `voyage-3-lite` | Free tier available; Anthropic's recommended embeddings partner (Anthropic has no embeddings API of its own) |

Env var equivalents (`.env`):

```
AIJF_EMBEDDING_PROVIDER=openai        # or "voyage"
AIJF_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_API_KEY=sk-...
# or:
AIJF_EMBEDDING_PROVIDER=voyage
VOYAGE_API_KEY=pa-...
```

If **Local-only mode** is on, or the key is missing/invalid, the app
automatically falls back to the local model rather than failing the
whole matching run (see `app/ai/embeddings.py:get_embedding_backend`) -
you'll see a log line noting the fallback, never a crash.

---

## 3. LLM reasoning (AI-written match explanations)

Off by default. Turning this on sends the **final shortlist only**
(configurable, ~10-50 jobs/day, never the raw job pool - see the funnel
below) to an LLM for a structured strengths/gaps/reasoning writeup.
What's sent is a compact, structured summary of your candidate profile
(target roles, skills, years of experience, etc.) plus the job posting
text - **never the raw resume file**.

Want this without a paid API? Set **LLM provider** to `local` instead
and point it at a model on your own machine - see section 1b above. This
section covers the two hosted alternatives.

Set **LLM provider** to `anthropic` or `openai` on the AI Settings page,
add the matching API key, and optionally a model name.

| Provider | Get a key | Default model |
|---|---|---|
| Anthropic (Claude) | https://console.anthropic.com/settings/keys | `claude-sonnet-5` |
| OpenAI | https://platform.openai.com/api-keys | `gpt-4o-mini` |
| Google Gemini | https://aistudio.google.com/apikey | `gemini-2.0-flash` |

Gemini is reached through Google's own OpenAI-compatible endpoint, so it
needs no extra package - and it currently has a free tier, which makes
it the cheapest way to get hosted-model quality.

Env var equivalents (`.env`):

```
AIJF_LLM_PROVIDER=anthropic           # or "openai"
AIJF_LLM_MODEL=claude-sonnet-5
ANTHROPIC_API_KEY=sk-ant-...
# or:
AIJF_LLM_PROVIDER=openai
AIJF_LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...
```

Note: `LLMProvider.LOCAL` exists as a value in the schema (for future
use, e.g. a locally-hosted model server) but Layer 6 doesn't call
anything for it yet - selecting it behaves the same as `none` (no LLM
reasoning; you still get the full rule-based score/explanation from
Layers 1-5). Local LLM support would go in `app/ai/llm_analyzer.py`.

If an LLM call fails or times out for a given job (rate limit, network
issue, bad key), that one job just keeps its heuristic-only score and
explanation - it never blocks or fails the rest of the run (see
`app/ai/ranker.py`).

### What never happens, regardless of provider

- The raw resume file is never uploaded anywhere.
- Job descriptions are always treated as untrusted **data** - the
  system prompt explicitly instructs the model to ignore any
  instruction-like text inside a job posting (prompt-injection guard,
  see `app/ai/llm_analyzer.py`'s `_SYSTEM_PROMPT`).
- The model's raw chain-of-thought is never requested or stored - only
  a structured score + short, evidence-grounded strengths/gaps.

---

## 4. Finding companies for you (automatic, no ceiling)

**This runs by itself.** Every scan - manual or scheduled - starts by
looking for new companies that match your resume, so you never have to
know or supply a list of employers, and there is no fixed limit on how
many it can eventually watch.

### Why this needs a queue, not a single search

Greenhouse, Lever, Ashby and SmartRecruiters each serve **one company at
a time** and publish no index of their boards - there is no endpoint
that lists "every company on Greenhouse." So the app can only ever read
a board it can already *name*. The real problem discovery solves is not
"search every company at once" but "keep learning company names from
everywhere it can, forever."

### 4a. Feeding the queue (no AI provider needed)

Every run, company names arrive from four directions and get recorded
in a persisted list (`company_candidates`):

1. **Resume-driven search** - terms built from your own target titles
   and skills run against the public search endpoints Workable and
   Jobicy publish. Matching postings are ingested immediately, so a
   brand-new user gets real matches on their first scan.
2. **Keyless job aggregators** - Himalayas, RemoteOK, Arbeitnow and
   Jobicy each publish an open feed of postings across many employers,
   which the app sweeps purely for company *names*, regardless of
   whether they match your resume yet. One shallow pass on a fresh
   install queued **612 distinct company names in 12 seconds**.
3. **Every company already ingested** - once a job from any source is in
   your database, its employer becomes a candidate for having a full
   board worth watching, not just the one posting that was seen.
4. **AI suggestion**, where an LLM is configured (see 4b below).

### 4b. Draining the queue

Each run, a batch of queued names is probed - concurrently, against all
five supported ATS platforms - through the same rate-limited client used
for scanning. A name that resolves gets its **full** board added, so
later scans see everything that company posts, not just whatever
matched a search term. A name that doesn't resolve stays in the queue
and is retried (up to 3 attempts) on a later run, since a miss can be a
site being briefly unreachable rather than a wrong guess.

**Nothing here resets.** Whatever isn't reached this run waits for the
next one - that's what makes coverage grow every run instead of
capping out at whatever one pass could check.

Verified on a fresh install: one run found 340 postings across 179
distinct companies from search alone, before the queue mechanism even
starts draining its backlog.

### 4c. AI suggestion (a supplement, needs an LLM provider)

Where you have an LLM configured, the app additionally asks it to name
relevant employers - useful for companies too small or new to appear in
any public feed. Suggested names go through the same verification as
everything else: checked against the real Greenhouse/Lever/Ashby/
Workable/SmartRecruiters APIs, trying a few plausible slug spellings
(`Acme Robotics` -> `acmerobotics`, `acme-robotics`, `acme`). **Only a
board that actually responds with real openings is added.** A
hallucinated company costs one HTTP 404 and is dropped; anything that
misses is queued rather than thrown away, same as everything else.

So every source it adds is verified-working at the moment it was added,
never a guess written into your database.

**Requirements and limits:**
- **Needs nothing to run at all** - no API key, no AI provider. An LLM
  (section 3 above, or a free local model per section 1b) only adds the
  extra suggestions in 4c; the local *embedding* model can't do it.
- Only resolves companies using Greenhouse/Lever/Ashby/Workable/
  SmartRecruiters. Those cover a large share of venture-backed, mid-size
  and European employers, but a company on Workday, Taleo, or a bespoke
  careers page won't be found even once its name is known.
- **Coverage compounds with no ceiling.** Each run probes a bounded
  batch so a single run stays fast, but names keep arriving faster than
  a run can drain them - leave the app scheduled and the watched list
  keeps growing indefinitely.
- Turn it off with the `discovery.auto_enabled` setting if you'd rather
  curate sources by hand.
- Deliberately polite: probes go through the same rate-limited client
  used for scanning, with a descriptive User-Agent, and back off
  automatically for any host that asks it to slow down. It runs in the
  background - keep using the app.
- Already-watched companies are skipped rather than re-probed, so a run
  only ever spends its budget on names it hasn't settled yet.

### 4d. Reading any company's own careers page (not just those five platforms)

**Job Sources page → add a source, type "Company career page (any
URL)".** Paste any company's careers page URL and this reads it
directly - it isn't limited to Greenhouse/Lever/Ashby/Workable/
SmartRecruiters the way everything above is.

How it reads the page:
1. Checks `robots.txt` first (the one source type that does - it's
   reading a page meant for a human browser, not a documented API).
2. Fetches the page and looks for links that read like job postings -
   this needs no AI and works on most career pages, since most render
   their job list directly in the page's HTML.
3. If that finds almost nothing, falls back to rendering the page in a
   real headless (invisible) browser before looking again - this is what
   catches a page whose job list is drawn in by JavaScript after the
   page loads, which a plain fetch can never see. Slower, but it gets
   there.
4. **If even that fails** and you've opted in (see below), falls back
   once more to a real browser you're already logged into - some sites
   specifically block anonymous automated browsers but allow a real,
   real-cookies one. This is the slowest and most capable tier, and it's
   the only one that ever touches your own browser.
5. **Where an LLM is configured**, the page (however it was obtained) is
   handed to it instead of relying on the link-pattern heuristic - it
   reads an unfamiliar page layout roughly the way a person would, which
   is far more reliable across the huge variety of real career-page
   designs than any fixed pattern can be. Without an LLM, the
   link-pattern heuristic alone is used.
6. Visits each posting's own page (up to a cap) to pull its actual
   description, so these postings get scored against your resume on
   their real content - the same as every other source's postings -
   rather than on a title alone.

**Requirements and limits:**
- Needs no AI for the basic version (steps 2, 6); an LLM makes the
  extraction meaningfully better (step 5) and is what to set up if a
  particular company's page isn't yielding good results.
- The headless-render fallback (step 3) is an optional dependency
  (`playwright`, plus a one-time `playwright install chromium` browser
  download, a few hundred MB) - not bundled into the installer by
  default because of that size. Without it, this source still works on
  every career page that doesn't require JavaScript to show its job
  list, which is most of them; it just can't reach the JS-only ones.
- **The "your own browser" fallback (step 4) is off by default** and
  needs two things: turning it on under AI Settings → "Browser fallback
  for Company career page sources", AND starting your own Chrome/Edge
  with the `--remote-debugging-port=9222` command-line flag before a
  scan runs (close the browser first, then relaunch it with that flag).
  The app attaches to that running browser, opens one extra tab to read
  a page, and closes only that tab - it never closes your browser or
  touches your other tabs, and this tier is never used unless every
  faster one already failed.
- **This is a manual add, not something automatic discovery can do on
  its own.** Turning a company's name into the right URL for their
  careers page would need a real web-search API - a separate, paid
  capability this app doesn't use. Give it the URL, though, and it reads
  that page about as well as engineering allows.
- Respects `robots.txt` - a site that disallows automated access is
  skipped, the same as it would be for a browser extension or crawler.

## 5. Letting the AI read your resume

**Resumes page → "Read My Resume with AI".** Off unless you press it.

Your resume is always read first by a built-in offline parser that needs
no API key and sends nothing anywhere. That parser matches against a
fixed vocabulary: it reliably finds "Python" and "Kubernetes", but it
can't work out that someone whose resume never contains the phrase
"Machine Learning Engineer" is clearly one, or turn a career history
into industries and domain expertise.

This option additionally has your configured LLM read the resume, which
does understand that. Results are **merged** with the offline parse (the
taxonomy's concrete findings are never dropped just because the model
didn't repeat them) and everything stays editable before you save.

⚠ **This is the one feature that sends your resume's text off your
machine.** Everywhere else, only a compact structured profile is ever
sent - never the resume itself, and never the file. Accordingly:

- it is off by default and never runs as a side effect of uploading;
- **Local-only mode disables it entirely**, whatever else is set;
- the button says plainly what it sends before you press it.

Costs a few cents once. Worth it for an unusual career history or a
resume the offline parser clearly misread; unnecessary for a
conventional one it already got right.

## 6. Controlling how many jobs reach the (paid) AI layers

To keep remote-API costs predictable regardless of how many jobs get
scanned, matching runs as a funnel (section 17 of the spec):

```
all active jobs  ->  free heuristic score (Layers 1-5, always runs)
                 ->  top N  ->  embedding similarity (Layer 2)
                            ->  top M  ->  LLM reasoning (Layer 6, only if configured)
```

`N` ("Jobs sent to embedding similarity") and `M` ("Jobs sent to LLM
analysis") are both editable on the AI Settings page, under "Matching
funnel (cost optimization)".

**`N` defaults to 0, meaning "every job".** With local embeddings this
costs nothing and runs offline, and capping it actively hurts: the
heuristic score that decides the cut is only ~15% job-title-driven, so a
cap can eliminate a genuinely great match on unusual phrasing *before
anything reads its description semantically*. If you switch to a paid
remote embedding provider, 0 automatically becomes a bounded 300 so a
large scan can't run up an unexpected bill - set an explicit number to
override that either way.

`M` still has a real cap, since every LLM call costs money. Setting `M`
to 0 disables LLM reasoning entirely without touching the provider
setting.

### Why match scores top out around 80

Worth knowing so the numbers don't read as "nothing is a good match":
several scoring components deliberately stay neutral when a posting
simply doesn't state something (most postings don't publish seniority,
employment type, or salary), which caps the achievable total. Measured
against ~750 real postings, a genuinely strong match lands around
**78-80**, and the 95-100 band is effectively unreachable in practice.

That's why the default "Minimum match score for email" is **75**, not a
higher-sounding number - at 85 the daily email would never send at all.
Judge matches by their *ranking* and the specific strengths/gaps shown,
not by expecting a 95%.

---

## 7. Verifying a packaged build

If you're running `AIJobFinder.exe` (the packaged build) rather than
from source, local embeddings should work correctly as of the current
build (a real PyInstaller/torch packaging bug was found and fixed - see
the "KNOWN LIMITATION" section at the top of `packaging/aijobfinder.spec`
for the full diagnosis if you rebuild and hit it again). You can verify
any given build with the self-test:

```powershell
$env:AIJF_SELFTEST=1; .\dist\AIJobFinder\AIJobFinder.exe
```

Check `%LOCALAPPDATA%\AIJobFinder\logs\aijobfinder.log` for `[OK]`/`[FAIL]`
lines. If local embeddings ever fail in a build you produce, an OpenAI
or Voyage embedding provider (section 2 above) is unaffected, since
neither touches `torch`/`sentence-transformers` at all - a reliable
fallback while any packaging issue is being investigated.

---

## Quick reference: all the settings in one place

| Setting | UI location | `.env` variable |
|---|---|---|
| Local-only mode | AI Settings | *(no env equivalent - UI only)* |
| Embedding provider | AI Settings | `AIJF_EMBEDDING_PROVIDER` |
| Embedding model | AI Settings | `AIJF_EMBEDDING_MODEL` |
| LLM provider | AI Settings | `AIJF_LLM_PROVIDER` (`none`/`anthropic`/`openai`/`local`) |
| LLM model | AI Settings | `AIJF_LLM_MODEL` |
| Local LLM endpoint URL | AI Settings (only shown when LLM provider = `local`) | `AIJF_LOCAL_LLM_BASE_URL` |
| Anthropic API key | AI Settings | `ANTHROPIC_API_KEY` |
| OpenAI API key | AI Settings | `OPENAI_API_KEY` |
| Voyage API key | AI Settings | `VOYAGE_API_KEY` |
| Jobs sent to embeddings (funnel N) | AI Settings | *(no env equivalent - UI only, defaults to 300)* |
| Jobs sent to LLM (funnel M) | AI Settings | *(no env equivalent - UI only, defaults to 20)* |
| Score weights (how the 0-100 score is composed) | *(not yet exposed in UI)* | `app/core/constants.py:DEFAULT_SCORE_WEIGHTS`, stored per-user in `user_preferences.score_weights` |

Restart isn't required for provider/key changes - they're read fresh
from the database on the next scan/match run.

