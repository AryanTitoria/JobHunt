# JobSearch

> **Current version: JobSearch v2.0.0 — web platform.** This repository previously hosted the JobHunt CLI/email-digest application. The current `main` branch contains its replacement. The old implementation is preserved in Git history and the [`jobhunt-legacy`](https://github.com/AryanTitoria/JobHunt/tree/jobhunt-legacy) tag. Use [`jobsearch-v2.0.0`](https://github.com/AryanTitoria/JobHunt/tree/jobsearch-v2.0.0) for this platform release. The GitHub repository name remains JobHunt.


A questionnaire-driven job discovery platform built from JobHunt. Users answer search questions, browse available opportunities, and use a resume reference for advice after selecting a job or internship. Seen/saved/applied history stays private to each user. No email digest and no local model installation.

The application uses Django, a shared public-job inventory, private per-user resume data, a durable task worker, and optional hosted Gemini, Groq, or OpenAI models. Matching does not call a model for every posting. Detailed AI reviews happen on demand and are cached.

## Start on Windows

Install Python 3.11 or newer (3.12 recommended). Open a terminal in the repository root, containing `manage.py` (your existing Desktop copy may still be named `jobabc`):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe run.py --demo
```

Open **http://127.0.0.1:8000**, create an account, answer the Search questionnaire, and upload `examples/resume.txt` as a fictional resume reference. The launcher applies migrations and starts the web app with separate managed collection and interactive workers. Ctrl+C stops both. No activation or PowerShell execution-policy change is necessary. On macOS/Linux replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`.

`--demo` uses a separate database in `data/demo/` and clearly labelled fictional jobs, including examples from non-technical fields. It does **not** use an offline AI model. You can enable a real hosted model in this demo, or use the essential non-AI guidance without keys. The bundled example resume is fictional, not your private resume.

## Enable hosted AI

Edit `.env`. For example, to start with Gemini:

```dotenv
AI_PROVIDERS=gemini,groq,openai
GEMINI_API_KEY=your-server-side-key
GEMINI_MODEL=gemini-3.5-flash-lite
GROQ_API_KEY=
OPENAI_API_KEY=
```

The supplied model IDs are configurable examples. Check the provider console for models available to your account and update `GEMINI_MODEL`, `GROQ_MODEL`, or `OPENAI_MODEL` as needed. You can put `openai` first and use your existing OpenAI key. No Anthropic SDK or Ollama is required.

Restart the application after changing environment variables. Sign in, open **Profile & preferences**, and enable hosted AI. The primary provider receives redacted resume excerpts and a selected job description. Fallback to another configured provider requires a separate user opt-in. Keys are server-side only; never put them in browser JavaScript or commit `.env`.

After enabling AI, open a job from the results. Essential advice appears immediately. A worker prepares the detailed hosted-model review and the page updates when it is ready. Reopening the same resume/job version uses the saved review, not another API call. If a provider is unavailable, the essential guidance remains visible with a clear notice.

Read **AI_OPTIONS.md** for free API options, quota behavior, privacy considerations, and the cost-control design. There is no guaranteed unlimited free hosted model.

## Enable live discovery

For web discovery, add a Tavily key (free monthly allowance) to your existing `.env`:

```dotenv
SEARCH_PROVIDERS=tavily
TAVILY_API_KEY=your-tavily-key
TAVILY_MONTHLY_LIMIT=800
```

Brave remains supported through `BRAVE_SEARCH_API_KEY`. The public job APIs work even without either search key. See **SOURCES.md** for all providers, optional Adzuna/USAJOBS credentials, quotas, and attribution requirements. Start without `--demo`:

```powershell
.\.venv\Scripts\python.exe run.py
```

Create an account, answer the Search questionnaire, then upload a resume reference. Saving search answers refreshes collected opportunities and queues background discovery. Uploading a resume never changes your search answers or result eligibility. **Refresh discovery** requests a new web search subject to usage limits (job feeds retain their cooldowns); meanwhile the existing shared inventory remains searchable.

Search receives target titles and locations, not the full resume. Search results are only candidate URLs. Actual postings must be fetched from supported sources before they are shown as jobs.

Included sources:

- Automatically discovered Greenhouse, Lever, and Ashby boards using the reused JobHunt parsers.
- Remotive, Arbeitnow, Jobicy, Remote OK, and Himalayas public APIs, with attribution and bounded polling.
- Optional Adzuna and USAJOBS registered job-search APIs, with per-provider attempt caps and partial-description labels.
- Public career pages containing JobPosting JSON-LD, subject to robots.txt.
- Optional RSS/Atom feeds and manually supplied seed career URLs.

Edit `discovery.json` for seed URLs, optional RSS feeds, the default scheduled search field, and feed settings. Per-user discovery uses that user's confirmed roles and locations. A predefined company list is not required.

No source can guarantee every available job on the internet. Restricted or unindexed listings, delayed feeds, unsupported markup, and pages requiring browser rendering can be missing. Login/CAPTCHA bypass and scraping of restricted platforms are not included. Remotive's public listings are delayed by approximately 24 hours; source links and attribution are retained.

## What users can do

1. Register and sign in using their own account.
2. Upload PDF, DOCX, TXT or Markdown resumes, up to 5 MB. PDFs must contain text; scanned documents need OCR first.
3. Review extracted skills and experience, choose target roles/locations, and set a minimum match score.
4. Browse matching jobs with search, remote-only/unseen filters, sorting, and pagination.
5. Select **View job & resume tips**. This marks the job seen for that user only.
6. Read the posting, matching skills, gaps, and resume-specific suggestions. Optional hosted AI adds evidence-grounded wording suggestions.
7. Save a job or mark it applied. Applications stay on the employer's original site.
8. Export their resume text/history or delete all resume versions, matches, and reviews. Seen/saved history remains after resume deletion.

Profile, resume text, analysis, and job state are scoped to the authenticated owner. The raw uploaded binary is not retained or publicly served. Resume text is stored in the database and must be protected by your hosting, database access rules, and backups. Hosted AI is opt-in; free-tier provider data terms may differ from paid tiers. Redaction and evidence validation reduce risk, but they do not guarantee removal of all identifying data or model factual correctness.

## Matching and AI usage

Search eligibility uses questionnaire answers only: field or selected roles, professional experience, jobs/internships/both, location and work arrangement. Every eligible collected posting is accessible through pagination; there is no resume-skill gate or minimum resume-match threshold. Search relevance ordering is based on selected roles and field. Resume skills are compared only in selected-posting advice. Unknown experience and work arrangement have explicit questionnaire options. Broadening answers cannot recover a job a source never supplied.

Limits in `.env` control daily user attempts, daily global attempts, and a conservative daily token-reservation budget. Attempts, including failures, consume the platform allowance because providers may also count failed requests. These application limits are not a provider billing guarantee. Model requests have output ceilings, provider cooldowns, and no automatic repeated retries. A provider 429 response opens a circuit rather than repeatedly spending requests. With explicit fallback consent the next configured provider can be tried. When everything is unavailable, non-AI matching and essential advice continue.

Job inventory is deduplicated by canonical URL and conservative exact-content identity. Source failures preserve prior inventory. A complete ATS snapshot can deactivate a disappeared job, and stale feed copies cannot revive it. Jobs must have been observed within three days and must not be explicitly expired. Source presence is a freshness signal; always check that applications remain open.

## Worker and scheduled collection

The launcher starts the web app and two managed worker threads for local development. On a host, run them separately:

```text
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn --bind 0.0.0.0:8000 --workers 2 --timeout 60 platform_config.wsgi:application
python manage.py worker --lane collection
python manage.py worker --lane interactive
```

The worker handles durable database-backed tasks, so discovery and AI requests do not block web requests. Keep both lanes running so a long collection cannot delay an AI review. `python manage.py worker --once` drains pending tasks and exits. Failed tasks retain a safe message and can be retried. Stale running tasks become retryable after 30 minutes.

Schedule `python manage.py collect_jobs` hourly or daily on your deployment platform to update the shared inventory and refresh every user's matches. This repository does not create a schedule automatically. Respect source cooldowns; Remotive is not polled more than once per six hours.

For administration, run `python manage.py createsuperuser` and visit `/admin/`. Admin tools expose source health, inventory, and task status. Resume content is intentionally not registered in the admin interface. Password-reset email is not implemented; a platform operator can use Django's `changepassword` command. This mentor-oriented application is not an enterprise identity service.

## Deploy beyond your machine

Nothing requires a model running on your machine. Deploy the Python web service and worker together with PostgreSQL using the included Dockerfile and Compose configuration, or on another Python/Docker host.

For Docker:

1. Copy `.env.example` to `.env` and configure your hosted keys.
2. Add `POSTGRES_PASSWORD` with a strong URL-safe password, such as a randomly generated hexadecimal string. Compose stores the database in a persistent volume.
3. Run `docker compose up --build`. The migration service runs first, then web and worker start.
4. For an internet deployment set `DEBUG=false`, a strong unique `SECRET_KEY`, your domain in `ALLOWED_HOSTS`, and `https://your-domain` in `CSRF_TRUSTED_ORIGINS`. Put the web service behind HTTPS. Set `TRUST_PROXY_HTTPS=true` only when a trusted reverse proxy sets and controls the forwarded protocol header. The default Compose port binds to localhost for use behind that proxy.
5. Back up PostgreSQL, run the worker continuously, and configure scheduled collection on the host.

Install `requirements-production.txt` on a Linux host for Gunicorn and PostgreSQL support. SQLite is appropriate for a small local demo, not a scaled multi-process hosted platform. The app is delivered as source; no paid hosting account, domain, external deployment, or production schedule has been created. Docker/PostgreSQL deployment instructions are provided but were not executed in this environment.

## Development and validation

```powershell
python manage.py test tests
python manage.py check
python manage.py makemigrations --check --dry-run
```

See `VALIDATION.md` for checks actually performed and `SOURCES.md` for the multi-provider discovery setup. The frontend uses server-rendered templates, CSS, and a small polling script; there is no Node build step. The project includes committed database migrations and the fictional sample resume. Runtime accounts, databases, API keys, and original uploaded files are excluded from the downloadable archive.

## Code map

```text
platform_config/       Django settings, routes, WSGI
careers/models.py      users' profiles, resumes, matches, seen state, tasks, budgets
careers/views.py       authenticated platform screens and actions
careers/services/      resume parsing, matching, hosted AI, collection, durable queue
careers/management/    background worker, scheduled collection, demo loading
discovery_core/        reused JobHunt parsers and public-source discovery
templates/            landing, accounts, dashboard, detail, profile, upload, sources
static/jobabc/         responsive styles and task polling
tests/                privacy, web flow, uploads, budgets, fallback, ingestion tests
examples/             fictional resume, sample profile, optional old company examples
```

Original project: https://github.com/AryanTitoria/JobHunt . JobSearch reuses the public fetching/discovery foundations and replaces the single-user CLI/email workflow with a multi-user browser platform. This build is a mentor-demonstrable application and a foundation for further production hardening, not an exhaustive global job index.


## Experience and field internships

In **Profile & preferences**, choose your career stage, confirm your field of study, and enter **years of professional experience**. Use **Student / final-year student**, **Computer Science**, and **0** for a CS fresher. Personal projects and degree duration should not be counted as employment.

Experience is an eligibility gate. Zero years excludes senior/lead titles and postings requiring prior experience; explicit ranges such as 0–2 years are accepted. An unstated requirement is excluded unless you enable **Include jobs with an unstated experience requirement**. Parsing is rule based and can miss unusual wording or requirements absent from a partial posting; always check the original vacancy.

Choose **Jobs and internships** or **Internships only** in the questionnaire. Internships and jobs both use the same questionnaire eligibility policy; neither depends on resume keywords. Browse the **Internships** tab or **Remote internships** link. Upload a resume reference for selected-posting advice. Other requirements, including graduation year and availability, must be checked on the original posting.

India discovery includes an editable `india_careers.json` directory of official company career starting pages, public Greenhouse/Lever/Ashby/SmartRecruiters/Recruitee boards, and bounded structured-page extraction. A starting-page link is not a guarantee of imported jobs. JavaScript-only, restricted, and custom sites can require dedicated connectors. Freshworks' SmartRecruiters connector fetches at most 20 job details per check and never interprets that bounded result as a complete board. Web search remains subject to your configured key and budget. Set `india_career_sites` to false in `discovery.json` to disable automatic directory checks.

Restart `run.py` after updating. It applies migrations while preserving existing accounts and resumes. Old matches are hidden until the managed worker refreshes them under the current eligibility policy; saving Profile refreshes them immediately.


### Remote internships and reliable direct collection

Choose **Remote only** or **Any arrangement** with remote opportunities enabled in the questionnaire for internships open worldwide or in your selected location. The **Remote internships** link selects field internships with remote status. US-only remote vacancies do not become eligible for India merely because they are remote. Unknown remote geography is not treated as worldwide. Lever `workplaceType` and Ashby `isRemote` are preserved; known Indian city-only locations and Bangalore/Bengaluru spelling variants are recognized.

`india_ats_boards.json` contains direct public ATS sources (Hevo Data, Weekday client vacancies, and Freshworks), checked before generic discovery when India is selected. Field internships are matched immediately after these checks, so later slow or failed searches do not hide imported internships. Sources still have collection cooldowns. The 11 company-directory links alone are not 11 working company-specific connectors, and a working connector does not guarantee an eligible internship is currently open. Academic duration and preferred qualification sections do not count as required professional experience. Matching policy 4 refreshes existing results after restart.


## Search questionnaire and resume reference

New accounts start at **Search questionnaire**. Answer career stage, professional experience, desired field, broad-field versus selected-role search, jobs/internships/both, location, work arrangement, and how to handle unstated requirements. AI review consent is separate. Saving answers refreshes existing inventory and queues discovery using those answers.

A resume is reference material for application advice. It never fills or overwrites search answers, filters results, or controls relevance order. You can browse with no resume, then upload one for the selected posting. A safe return link brings you back to that posting. Changing or deleting the reference preserves questionnaire-based results. Uploaded document text and current skills remain private per user; resume gaps are calculated only when viewing a selected opportunity.

This project provides suggestions and optional grounded AI review; it does not automatically rewrite the original resume or invent experience. Coverage remains limited by the connected public sources. On update, `run.py` applies migrations, preserving existing user choices and data. Restart the app and review the questionnaire; existing field/role/location/experience answers are retained. Legacy skill-score settings no longer affect discovery.


## JobSearch upgrade: parsers, education and evidence-backed tailoring

The product is named **JobSearch**. The project folder stays `jobabc`; existing `data/jobabc.sqlite3` is kept for account/resume compatibility. New static assets live under `static/JobSearch`. Existing API keys and runtime data are never included in the downloadable archive.

The questionnaire now supports education level, degree/course, specialization, graduation year, career stage, professional experience, career field, work categories, targeted roles, excluded roles, employment types, location/work arrangement and availability. Choose **Education or selected roles** for the union of education-related opportunities and a different career direction. Role-only search supports a career switch. Availability and graduation year remain reference answers when the posting does not supply dependable requirements; they are not guessed filters. Resume parsing never replaces these explicit answers.

### Parser behavior

Required and preferred experience are separated from education, internships and personal projects. Months and fractional years are supported. Contradictory ranges and missing requirements stay unknown. Entry/intern title classification is labelled as an inference rather than a stated zero-year requirement. Remote country restrictions override worldwide marketing text. Unknown remote geography is flagged. Qualifications and required/preferred skills are separated in selected-job details.

Resume parsing recognizes summary, skills, employment, internships, projects, education and certification sections. Stable IDs identify exact source lines, for example `M1:Experience[0].bullet[2]`. Unclassified text is retained in the reference but omitted from structured tailoring; clearer section headings may be needed. Skill aliases are true synonyms (JS/JavaScript, ReactJS/React); related technologies are not interchangeable.

### Source-backed resume tailoring

1. Upload one or more master resume versions under **Resume reference**. An optional version date is an explicit user answer; upload time never settles conflicts.
2. Open a job or internship. Review the parsed requirements and choose up to five master resumes.
3. Select **Generate tailored resume with AI** or **Build factual draft**. The engine selects and reorders existing source content. AI may propose conservative wording changes, validated against cited originals. It does not invent, strengthen claims, add missing JD skills, or rewrite numbers/dates/tools.
4. Review the evidence ledger, requirement mapping, skill gaps, changes log and detected conflicts. Use **Download resume PDF** for a selectable-text, single-column PDF, or download the evidence JSON. The application PDF omits internal citations, scores and gap notes.

All candidate facts are validated against cited sources. Identical facts may share citations; differently named projects are kept separate. Detected conflicts are omitted unless all conflicting masters have distinct, explicit version dates, allowing a most-recent version to be selected. Conflict detection is conservative and not exhaustive; review source facts. Ambiguous source structure can produce an incomplete draft, which is preferred to fabricated content. A conservative validator rejects unsupported wording, changed numbers, tools, dates and stronger claims; rejected proposals retain their original wording. These checks are not a guarantee of semantic correctness: review every draft before applying.

### Optional hosted assistance

Enable AI consent in the questionnaire before explicitly requesting hosted assistance. **Interpret unclear requirements** queues a cached model request for exact JD evidence. Unsupported quotations are rejected and AI never silently changes discovery eligibility. **Generate tailored resume with AI** requests source ordering and grounded wording proposals. Code assembles and validates candidate facts; arbitrary model-written resume content is rejected. Both use the existing configured online providers, quotas and cooldowns. Cached requests do not consume another model call. Failure falls back to source-preserving rules. No offline model is installed.

Drafts, evidence ledgers and downloads belong to the authenticated owner. Deleting resume data also removes drafts and parser caches. Source-backed tailoring does not guarantee that the candidate qualifies or that every contradiction was recognized.

### Questionnaire research

The design was informed by official descriptions of job titles, work areas, employment types, education/qualifications, location settings and availability in [Indeed profile preferences](https://www.indeed.com/help/job-seekers/articles/32603395892109-adding-or-editing-job-search-preferences?co=US&hl=en) and [LinkedIn job recommendations](https://www.linkedin.com/help/linkedin/answer/a512279/). JobSearch implements its own explicit-answer search policy; it does not copy those platforms' recommendation algorithms.

### Resume-specific compatibility and interactive reviews

On a selected job, choose a master resume and press **Compare**. The report uses that resume text, never questionnaire skills. Discovery still follows questionnaire answers. Cached reports are invalidated when resume text, job content or scoring version changes.

Default weights are required skills 35, preferred skills 10, relevant evidence 15, professional experience 20, education 10, relevant projects 5 and text readability 5. Employment, internships and projects are distinguished. Evidence in work/project bullets is stronger than a keyword list. Unknown employer criteria are excluded and remaining weights normalized; insufficient descriptions show no score. This is an advisory estimate, not a validated employer ATS result or hiring probability.

Interactive tasks use a separate worker lane from collection. Buttons show queued/running/ready/failed states and prevent duplicate requests. Provider quota/model/key failures display an explanation. Successful AI results are cached. Failed tailoring can be retried after two minutes; a factual PDF remains available. ReportLab generates the PDF on the server.

Validation: 203 automated tests, local HTTP workflow, desktop/mobile layout checks, PDF extraction and rendering, and successful live Gemini review/tailoring using fictional candidate data.
