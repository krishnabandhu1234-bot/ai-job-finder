# Getting Started with AI Job Finder

**What this app does:** you give it your resume, it watches company job
boards for you, reads every new posting, and tells you the few that are
genuinely worth your time — optionally emailing you a short list each
morning.

**What you need:** a Windows PC. That's it. No API keys, no accounts, no
payment. (There are optional AI upgrades later in this guide, but the
app works fully without them.)

**Time to set up:** about five minutes.

---

## Step 1 — Install it

Double-click **`AIJobFinder-Setup.exe`** and follow the prompts.

Windows will probably show a blue "Windows protected your PC" warning.
That appears for any app that hasn't been code-signed with a paid
certificate — it isn't a virus warning. Click **More info** →
**Run anyway**.

When it finishes, launch **AI Job Finder** from your Start Menu.

> **Where your data lives:** everything stays on your computer, in
> `C:\Users\<you>\AppData\Local\AIJobFinder`. Uninstalling the app never
> deletes it.

---

## Step 2 — Follow the Setup Guide

The app opens on a page called **Setup Guide**. It lists everything that
needs doing, shows a ✅ next to what's finished, and has a button on each
row that takes you to the right place.

You can just follow it top to bottom. The rest of this document explains
each step in more detail if you want it.

---

## Step 3 — Upload your resume

Sidebar → **Resumes** → **Upload Resume (PDF, DOCX, TXT)** → pick your file.

The app reads it immediately and shows a **Candidate Profile** below:
your skills, job titles, years of experience, employers, education, and
so on.

**Look this over — it drives everything else.** It's a computer reading
your resume, so it gets things wrong sometimes. Fix anything that's off,
then click **Save Candidate Profile**.

When you save, the app also fills in your **Job Search Profile**
automatically (what job titles to look for, what seniority, where), so
you don't have to type it all again. A popup tells you exactly what it
filled in.

> **Scanned or photographed resumes won't work.** If your PDF is really
> a picture of a page, there's no text to read and the app will say so.
> Export a fresh PDF from Word or Google Docs instead.

**If it read your resume badly**, there's a **Read My Resume with AI**
button on the same page. The built-in reader only recognises skills it
already knows by name; the AI one actually understands the document and
is much better at unusual career paths. It needs an API key (see
*Optional upgrades*) and it sends your resume's text to that provider —
the button says so before you press it. Everything it finds is still
shown for you to check and edit.

---

## Step 4 — Check what it's looking for

Sidebar → **Job Search Profile**.

Most of this is already filled in from your resume. Check the top field,
**Job titles** — these are the roles it hunts for. Add or remove titles
so they match what you actually want. Separate them with commas:

```
Machine Learning Engineer, Software Engineer, Data Engineer
```

Also worth setting while you're here:

| Field | What it does |
|---|---|
| **Locations** / **Countries willing to work** | Filters out jobs you couldn't take |
| **Work arrangement** | Set to `remote` if you only want remote roles |
| **Minimum match score for email** | How good a job must be to reach your inbox. Leave at 75 unless you're getting too many or too few |
| **Excluded companies** | Anywhere you never want to see |

Click **Save Job Search Profile**.

---

## Step 5 — Companies (the app searches for these itself)

**You don't need to do anything here, and you don't need an API key.**

Every time it runs, the app looks for companies by itself, from four
directions at once:

1. **It searches job platforms** for roles matching your resume — the
   same way you'd search a job site, but across every company on those
   platforms at once, using terms taken from your own target titles and
   skills. Matching postings are pulled in immediately, so you get real
   results on your very first scan.
2. **It sweeps the open job feeds** for the *names* of companies that
   are hiring anywhere — thousands of them, well beyond whatever your
   search terms happened to match.
3. **It remembers every company it has ever seen a posting from**, from
   any source.
4. **It asks your AI** (if you set one up) to name more.

Every name found this way goes into a list, and each run the app checks
a batch of them against the five job-board platforms it can read. When
one matches, that company's **full job board** gets added — so from then
on it sees *everything* they post, not just the roles that happened to
contain your search words.

**The important part: nothing here resets between runs.** Names the app
hasn't checked yet wait their turn, so the set of companies it watches
**grows every single run** rather than starting over. Leave it running
and the list keeps getting longer on its own. One shallow first pass
already collects **800+ company names** to work through, and later runs
keep adding to that pile faster than they empty it.

In testing, a single run on a fresh install found **340 postings across
179 different companies** — places like Syntiant, Albi, Parisi Labs and
Portless that no one would think to name from memory.

Sidebar → **Job Sources** shows everything it has found, including a
row called *"Job search (matches your resume)"* — that's the search
itself, and it lists the exact terms being searched on your behalf.

None of this needs an AI provider or an API key. An AI provider adds
step 4 on top, which reaches companies too small or too new to appear in
any public feed — a bonus, not a requirement.

The two options below are entirely optional.

### Optional — Add a specific company yourself (free, no AI needed)

If there's a company you want to watch, find its job board URL and use
the matching row below:

| If their jobs page looks like… | Choose | And enter |
|---|---|---|
| `boards.greenhouse.io/stripe` | Greenhouse | `stripe` |
| `jobs.lever.co/palantir` | Lever | `palantir` |
| `jobs.ashbyhq.com/ramp` | Ashby | `ramp` |
| `apply.workable.com/blueground` | Workable | `blueground` |
| `jobs.smartrecruiters.com/smartrecruiters` | SmartRecruiters | `smartrecruiters` |

*(Those are all real, working examples — try one if you want to see it
work before hunting down your own.)*

Type a name for it, paste that last bit into the box, click **Add
Source**. Press **Fetch Now** on the row to confirm it works — it'll
report how many jobs it found.

**If a company isn't on any of those five platforms**, choose source
type **Company career page (any URL)** instead and paste their actual
careers page URL (e.g. `https://company.com/careers`) — no slug or
special format needed. This reads the page directly, the same way you
would: it looks for links that read like job postings, and if you've
set up an AI provider, hands the page to it to read off every open role
the way a person would, which handles far more page layouts than a
fixed pattern ever could. If the page's job list only appears after
JavaScript runs (some modern sites work this way), it automatically
falls back to rendering the page in a real headless browser before
reading it — slower, but it still gets there. A site whose `robots.txt`
explicitly disallows automated access is skipped, same as it would be
for a person's browser extension or crawler.

> **This one type genuinely works on any company**, not five — but it's
> a manual add: you still have to supply that company's URL yourself.
> The app can't yet turn "Acme Corp" into the right URL on its own
> (that would need a paid web-search API this app doesn't use); once you
> give it a URL, though, it reads that page about as well as engineering
> allows.

### Optional — Just try it out (free, no AI, no internet)

Choose source type **Demo (example data)**, give it any name, click
**Add Source**. You'll get realistic sample jobs so you can see how
everything works before setting up an AI provider.

---

## Step 6 — Run your first scan

Sidebar → **Dashboard** → press **SCAN NOW**.

Each scan does three things in order: **finds new companies** to watch,
fetches every posting from all of them, then scores each posting against
your resume. A progress bar appears under the button — it fills in as it
works through your job sources and, later, each AI-analyzed posting;
during steps that don't have a countable total (like looking for new
companies) it just animates so you know it's still working.

Because the company list grows with every scan, **later scans see more
than earlier ones**. If your first scan finds less than you hoped, run
it again — it will be looking at more companies the second time.

**The first scan takes a minute or two longer than later ones** — it
downloads the AI model that reads job descriptions (about 90 MB, one
time only). After that it's fast and works offline.

When it's done, go to **Job Matches** to see your results, best first.
Click any job to see why it matched, what's missing, and an **Apply**
link.

**That's the whole app.** Everything from here is optional.

---

## Step 7 (optional) — Get matches emailed to you

Instead of opening the app, have it email you a short list each morning.

Full instructions, including how to get a Gmail app password:
**[EMAIL_SETUP.md](EMAIL_SETUP.md)**.

Short version: **Email Settings** → fill in your address and SMTP
details → **Send Test Email** to check it works → then **Scheduler** →
tick **Run scheduled scans automatically** → **Save Schedule**.

> The app has to be running for scheduled scans to happen. Turn on
> **Start with Windows** under **Settings** so it's always ready.

---

## Setting up an AI provider (paid, or free on your own PC)

Scanning, matching and email all work without this. An AI provider adds
the parts that need judgement:

| What it enables | Why it matters |
|---|---|
| **Extra company discovery** | The AI names employers too small or too new to appear in any public job feed, adding them to the list the app works through |
| **AI match explanations** | Written reasoning on your top matches instead of bullet points |
| **AI resume reading** | A much better read of your resume — infers roles and expertise the offline reader can't |

None of these are required. The app searches for jobs and finds
companies without any AI provider at all (Step 5).

All three need an **LLM provider** turned on under **AI Settings**.
You have two ways to do that:

**Option A — free, runs on your own PC, nothing sent anywhere.**
Install [Ollama](https://ollama.com/download), pull a model
(`ollama pull llama3.1` in a terminal), then in AI Settings set
**LLM provider** to `local`, **LLM model** to `llama3.1`, and leave the
endpoint URL at its default. Full walkthrough with LM Studio and other
options: **[AI_MODELS.md](AI_MODELS.md)**, section "Running an LLM
locally too". Quality depends on the model and your hardware — a small
local model is less reliable than a hosted one, but it's free and fully
private.

**Option B — pay-per-use, better quality, needs an API key.**
Get a key from any of:

- **[Anthropic (Claude)](https://console.anthropic.com/settings/keys)**
- **[OpenAI](https://platform.openai.com/api-keys)**
- **[Google (Gemini)](https://aistudio.google.com/apikey)** — has a free tier

Add it under **AI Settings**, set **LLM provider** to match, click
**Save**. Typically a few cents per discovery run, a few cents a day for
match explanations.

Full setup details and privacy notes for both: **[AI_MODELS.md](AI_MODELS.md)**.

> **Privacy:** by default nothing leaves your computer — resume reading
> and job matching both run locally. Options A and B above differ in
> exactly this respect: Option A (a `local` LLM) never sends anything
> anywhere, same as the defaults; Option B sends data to that provider,
> and each feature says exactly what before you use it. Ticking
> **Local-only mode** in AI Settings blocks Option B entirely — but
> Option A keeps working even with it on, since a model on your own
> machine already satisfies what that toggle promises.

---

## App updates

When a newer version of AI Job Finder is available, you'll be told three
ways:

- a banner right on the **Dashboard** — the screen you land on every
  time you open the app — with a **Get Update** button,
- a line at the bottom of your daily email, and
- a notice on the **Settings** page (which also has a **Check for
  Updates Now** button to check immediately instead of waiting).

**Get Update** opens the download link in your browser. The app never
downloads or installs anything by itself — it tells you what's
available and hands you the link, and you decide when to install it.
Update checks happen at most once a day, and if no update source is
configured for your build the app never contacts anything at all.

### Turning this on (only needed once, when you ship a new version)

The app checks a small JSON file you host yourself — there's no update
server to run. To enable it:

1. Host a file (a GitHub release asset works well — it's free, static,
   and gets you a stable HTTPS URL). A ready-to-edit starting point is
   checked in at `packaging/update_manifest.json`:
   ```json
   {
     "version": "0.2.0",
     "download_url": "https://github.com/you/ai-job-finder/releases/download/v0.2.0/AIJobFinder-Setup.exe",
     "notes": "What changed in this release"
   }
   ```
   Edit the `download_url` to point at your own repo/release, upload
   `packaging\dist_installer\AIJobFinder-Setup.exe` as that release's
   asset, then upload this JSON file itself as a release asset too (or
   anywhere else static) to get its hosted URL.
2. Point the app at that URL, either:
   - set the environment variable `AIJF_UPDATE_MANIFEST_URL` before
     building the installer (so every install checks it automatically), or
   - enter the URL as the `updates.manifest_url` setting from inside
     the running app (Settings page), no rebuild needed.
3. Every time you cut a new release, update the `version` and
   `download_url` in that one JSON file — existing installs pick it up
   within a day, or immediately if the user clicks **Check for Updates
   Now**.

Nothing else changes: the app still never installs anything for the
user, it just tells them a newer version and a link exist.

---

## When something's wrong

| What you see | What's happening |
|---|---|
| **Nothing on the Dashboard** | Open the **Setup Guide** — it shows which step is unfinished. |
| **"No matches found" after a scan** | Check your **Job titles** in Job Search Profile — those are literally the search terms. An unusual or very specific title finds little; try a more conventional one alongside it. A single restrictive country filter can also exclude nearly everything. Running more scans also helps: the company list grows every run, so scan three or four times before judging. |
| **Scans feel slow** | Most of that time is the app checking new companies for job boards, a few seconds each. It's deliberately polite to those sites. It gets through a batch per run and picks up where it left off next time, so nothing is wasted. |
| **Scores look low (70s and 80s)** | That's normal and expected. Most job ads don't state seniority or salary, so those parts of the score stay neutral. A genuinely strong match lands around 78–80 — judge by the ranking and the listed strengths, not by chasing 95%. |
| **No email arriving** | Send Test Email first (Email Settings) — that isolates whether it's your email settings or your match threshold. Then check **History** to see whether the scheduled run actually happened. |
| **A company shows "error"** | Click **Fetch Now** on it to see the actual message. Usually a wrong board name, or the company closed its board. |
| **Something crashed** | Sidebar → **Logs**. Passwords and API keys are never written there, so it's safe to read and share. |

---

## Quick reference

| Page | What it's for |
|---|---|
| **Setup Guide** | What's done, what's left |
| **Dashboard** | Today's numbers, Scan Now |
| **Resumes** | Your resume and what was read from it |
| **Job Search Profile** | What you're looking for |
| **Job Matches** | Your scored results |
| **Companies** | Who's hiring, across everything scanned |
| **Job Sources** | Which companies get watched |
| **Email Settings** | Daily email |
| **Scheduler** | When scans run |
| **AI Settings** | Optional AI providers, privacy |
| **History** | Past scans and emails |
| **Logs** | Diagnostics |
| **Settings** | Start with Windows, data folder |
