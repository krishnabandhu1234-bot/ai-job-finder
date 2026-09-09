"""Daily report email generation and sending. Implemented in Phase 7.

Planned modules:
  templates.py   - HTML email template rendering (Jinja2)
  sender.py        - SMTP sending, dedup against email_history, test/preview support

Note: this is `app.email`, a sub-package - it does not shadow the Python
standard library `email` package, which is only ever imported as the
top-level `email` (e.g. `email.mime.text`) from within these modules.
"""
