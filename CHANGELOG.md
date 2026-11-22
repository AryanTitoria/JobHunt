# Release history

## JobSearch v2.0.0 — 22 November 2026

The repository's current tracked tree is replaced with the Django JobSearch web platform. Historical commits are retained; no force push or history rewrite is needed.

- Questionnaire-based job and internship discovery, including education/role/category search and remote eligibility.
- Multi-user authentication and private resume references, seen/saved/applied state and reviews.
- Public job feeds, ATS integrations and optional web-search APIs.
- Source-backed resume tailoring with citations, skill gaps, conflict handling and private JSON export.
- Optional cached hosted AI assistance with consent and application budgets.
- JobSearch branding, responsive interface and explicit Profile/Sign out controls.
- SQLite for local use; PostgreSQL/Docker deployment configuration.
- Previous root-level CLI/email files and the scheduled email-digest workflow removed.

This is a replacement application, not a compatible update of the legacy CLI. Follow README.md for installation and run.py for local startup. Configure your own .env; credentials, local databases and personal resumes are not shipped. Legacy runtime databases are not imported automatically.

## JobHunt legacy

The previous CLI application is available at tag `jobhunt-legacy`, pointing to commit `6fbc326616027f647621145adc6a055e83961e23`. Browse or check out that tag separately when historical reference is needed. It is not retained as an extra folder in the current project.
