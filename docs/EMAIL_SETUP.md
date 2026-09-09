# Setting Up the Daily Email

The app can email you a daily digest of new high-match jobs (section 11
of the spec). This is entirely optional - everything else (scanning,
matching, Job Matches page) works without it - but without it configured
you'll only see results inside the app, not in your inbox.

Email uses plain SMTP with an app-specific password - not a real account
password, and not OAuth (no OAuth client secret is shipped inside a
distributed desktop `.exe`, since that can't be kept secret - see the
note at the top of `app/email/sender.py`). This covers Gmail, Outlook/
Microsoft 365, and effectively any other provider.

---

## Quick start: step by step

### Step 1 - Get an app-specific password from your email provider

**Gmail:**
1. Go to https://myaccount.google.com/security and turn on **2-Step
   Verification** if it isn't already on (required before Google will
   let you create an app password).
2. Go to https://myaccount.google.com/apppasswords.
3. Create a new app password (name it anything, e.g. `AI Job Finder`).
4. Google shows you a 16-character password like `abcd efgh ijkl mnop`.
   **Copy it** (spaces don't matter either way) - this is what you'll
   paste into the app, not your real Gmail password.

**Outlook / Microsoft 365:**
1. Go to https://account.live.com/proofs/AppPassword (personal
   Microsoft account) or your organization's admin portal if it's a
   work/school account (app passwords must be enabled by an admin
   there).
2. Create an app password the same way and copy it.

**Any other provider:** look for "App Passwords" in its account
security settings, or ask it for SMTP credentials - anything that gives
you an SMTP host, port, username, and password works here.

### Step 2 - Enter it in the app

1. **Launch the app** → open **"Email Settings"** in the left sidebar.
2. Fill in the form exactly like this (for Gmail):

   | Field | What to type |
   |---|---|
   | Send report to | the email address that should **receive** the daily digest (can be the same as your SMTP username, or a different inbox entirely) |
   | SMTP host | `smtp.gmail.com` |
   | SMTP port | `587` (already the default - leave it) |
   | SMTP username | your **full email address**, e.g. `you@gmail.com` |
   | SMTP app password | the 16-character app password from Step 1 - **not** your normal email password |
   | Send time | pick what time you want the daily email sent, e.g. `7:00 AM` |
   | Time zone | pick your time zone from the dropdown |
   | Max jobs per email | how many jobs to include at most (default `15`) - quality over quantity, see the note below |

   For Outlook/Microsoft 365, use `smtp.office365.com` as the SMTP
   host and port `587`, same as above otherwise.

3. Click **"Save Email Settings"**.

### Step 3 - Verify it actually works

Right next to Save are two more buttons - use both before relying on
this:

- **"Preview Daily Email"** - builds today's report against whatever
  jobs/matches already exist and shows it in a popup, exactly as it
  would be emailed. Doesn't send anything or need SMTP configured yet -
  useful to check the content itself first.
- **"Send Test Email"** - actually connects to your SMTP server and
  sends a real email to your configured address. **Do this once after
  saving your SMTP settings** - if your host/port/username/app password
  are wrong, this is where you'll find out, with a specific error
  message (e.g. *"SMTP login failed - check your username and app
  password"*) rather than a silent failure days later.

### Step 4 - Turn on the daily schedule

Email Settings alone doesn't make anything send automatically - that's
a separate switch:

1. Open **"Scheduler"** in the sidebar.
2. Check **"Run scheduled scans automatically"**.
3. Pick a **Frequency**: `Daily`, `Every 12 hours`, or `Weekly` (fires
   every Monday). The actual time-of-day and time zone come from the
   Send Time / Time Zone fields you set in Email Settings, not from
   this page.
4. Click **"Save Schedule"**. The page then shows **"Next scheduled
   run: <date/time>"** - if that says "not scheduled" instead, the
   checkbox didn't take; try again.

   **Scheduling only fires while the app is actually running** in the
   background - it's not a Windows-level background service. Enable
   "Start with Windows" on the **Settings** page so it's already open
   in the system tray/background by the time your scheduled hour
   arrives, or leave the app open.

5. Optional: click **"Run Full Pipeline Now (scan + AI matching +
   email)"** right below the schedule to trigger one full run
   immediately (scan → match → and send an email if anything clears
   your minimum score) instead of waiting for the next scheduled time.
   This is different from the Dashboard's "Scan Now" button, which
   deliberately never sends email (so you can test scanning/matching
   repeatedly without spamming your own inbox).

---

## What actually gets sent, and how to control it

- **Only jobs at/above your minimum match score** are included, never
  a firehose of everything scanned. That threshold - **"Minimum match
  score for email"** (default `75`) - is on the **Job Search Profile**
  page, not Email Settings (it's a matching preference, not a delivery
  setting).

  75 rather than a higher-sounding number is deliberate and measured:
  several scoring components stay neutral when a posting doesn't state
  something (most don't publish seniority or salary), so a genuinely
  strong match scores about 78-80 in practice. At 85 the email would
  never send at all. See "Why match scores top out around 80" in
  [AI_MODELS.md](AI_MODELS.md).
- **At most "Max jobs per email"** are included even if more qualify,
  best matches first.
- **The same role posted across several offices counts once.** Companies
  routinely list one job per location; those are collapsed into a single
  entry showing "+N other locations" so five copies of one role don't
  consume five slots, and all of them are marked notified together so
  the copies don't resurface tomorrow.
- **A job is only ever emailed once.** Once a job has been included in
  a sent email it's marked notified and won't appear again in a future
  digest, even if it's still active and still scores well (section 7 -
  "new job detection"). If a run finds zero new qualifying jobs, no
  email is sent that day at all - you won't get an empty "no matches
  today" email.
- Every attempt (sent or failed) is recorded and viewable on the
  **History** page, and errors go to the **Logs** page.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| "SMTP login failed" on Send Test Email | Wrong SMTP username (must be your **full email address**, not just the part before `@`) or you pasted your real password instead of an app password. Gmail also requires 2-Step Verification to be ON before an app password will work at all. |
| "Could not send email: ..." with a connection/timeout detail | Wrong SMTP host or port, or a firewall/network blocking outbound port 587. |
| Test email works, but nothing arrives on schedule | Check Scheduler → is "Run scheduled scans automatically" actually checked, and does it show a "Next scheduled run" time? Also confirm the app was actually running (not fully closed) at that time. |
| Scheduled run happened (see History page) but no email | Check Job Search Profile → "Minimum match score for email". Anything above ~85 will essentially never match (see the note above on why scores top out around 80) - if you raised it, lower it back toward 75. Otherwise some days genuinely have zero new qualifying jobs, which is correct behavior, not a bug. |
| Not enough jobs to email, or matches feel thin | You probably need more companies being scanned. Job Sources → "Find Companies" adds dozens at once based on your resume (see [AI_MODELS.md](AI_MODELS.md) § 3b). |
| Email arrives, but always empty-feeling / same jobs repeated | Shouldn't happen - each job is only ever emailed once (see above). If you're seeing repeats, check the Logs page for errors during the notification-marking step. |

Passwords are encrypted (via `app/core/security.py`) before being
written to the local database and are never written to the log files -
safe to check Logs while debugging without exposing your app password.
