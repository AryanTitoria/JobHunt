# Validation record

Validated on 18 November 2026 in an isolated Python 3.13 environment on Windows.

## Completed

- 101 Django tests pass. They cover registration, authenticated screens, complete resume-upload/discovery flow, per-user seen/saved state, private reviews/tasks/data export, CSRF enforcement, template escaping, file validation, PDF/DOCX/text extraction, model consent, provider fallback, cooldowns, atomic budgets, review caching, and source deduplication/closure.
- Database migrations applied successfully. `makemigrations --check --dry-run` reports no missing migrations.
- `manage.py check` reports no issues. `manage.py check --deploy` also reports no issues with production-mode security settings and a test secret configured.
- Static assets collected successfully. JavaScript passes Node's syntax check; Python modules compile.
- A real local HTTP smoke test starts the development launcher and its managed worker, requests the homepage and CSS/JS assets, registers a synthetic account, uploads the fictional resume, waits for a discovery task to finish, loads matches, selects a job, and confirms seen state plus resume guidance. The owned test server is stopped after the check.
- Read-only live connector checks succeeded: Greenhouse Stripe returned 789 postings, one Arbeitnow page returned 300, and Remotive returned 16. These counts are time-dependent and do not represent all internet jobs.
- The project uses the existing JobHunt public-source parsing/discovery foundations, with an independent Django database and per-user state. Email digest, SMTP delivery, and local-model dependencies are absent from the new application.

## Not verified here

- No real Gemini, Groq, OpenAI, Tavily, Brave, Adzuna, or USAJOBS credentials were used. Hosted-model and search control flow are covered by stubs and inherited parsing code; availability for your model/account requires your own configured keys.
- No real resume was sent to an external service. Test accounts and resumes are synthetic.
- Browser automation/visual screenshot review is unavailable in this session. Templates and routes were exercised through Django's client and real HTTP requests; CSS is responsive by construction, but visual layout has not been inspected in a browser.
- Docker is not installed in the execution environment. Docker/PostgreSQL configuration is included but was not built or deployed. The supplied cross-platform CI matrix has not been run remotely.
- No public host, production schedule, domain, or provider account was created. The deliverable is a runnable source project and deployment foundation, not an already hosted service.

## Practical boundaries

Coverage is limited to accessible supported sources and search indexing. Match scores are deterministic skill/role similarity, not a prediction of hiring success. Hosted AI is optional, metered, and requires user consent. Suggestions require review; evidence checks do not guarantee truthfulness. SQLite and the managed development worker are suitable for the mentor demo; use PostgreSQL, a separate worker, HTTPS, backups, and operational controls for a hosted multi-user deployment.


## Multi-source update

- Live no-key checks succeeded: Jobicy returned 100 postings on a sampled page, Remote OK returned 97, and Himalayas returned 20. Counts change over time. These checks did not modify the user's live database.
- Tavily basic-search payloads, rotating search providers, monthly web caps, daily registered-job-API caps, source failures, cursor pagination, original application links, attribution, snippets, and optional-source state are covered by offline tests.
- The SQLite concurrency regression remains part of the passing suite: a resume upload overlaps a 300-posting collector and verifies 900 final matches on a real SQLite file.
- Model changes include a committed migration adding the original application URL and a description-completeness flag. Existing user data does not need to be reset.
- Live registered-provider requests require user-owned credentials and remain unverified here. Docker/PostgreSQL and browser visual inspection remain unverified as described above.


## Collection orchestration repair

Fixed a provider metadata argument collision that stopped the live collection pipeline before public feed polling. Added an end-to-end live-mode orchestration regression with all five public feeds and dashboard match assertions, plus a direct metadata regression. The full suite now passes 70 tests. Failed discovery is also visible on the dashboard, and empty results show the number of active jobs before filtering.


## Signup feedback and validation

Registration accepts standard Django username characters, including email-style usernames, with explicit matching help text. Invalid forms show an accessible error summary without retaining passwords. Password hashing happens before the short account-creation transaction. Common/weak passwords, mismatched passwords, duplicate usernames and database-busy cases are tested. All 78 tests pass. User accounts and credentials were not reset.


## Experience and field-internship update (18 November 2026)

101 Django tests pass, including strict experience ranges, senior title exclusion, unknown-experience opt-in, field internships without a resume or keyword overlap, location gates, seen state, profile saving, preservation of confirmed experience, and stale-match reclassification. New ATS fixtures cover Recruitee and bounded SmartRecruiters results; page tests cover one-hop same-host extraction and explicit extraction failures.

A real public Freshworks SmartRecruiters fetch returned 20 postings successfully. The actual HTTP launcher/managed-worker smoke passed signup, upload, discovery, assets, job display, seen marking and guidance. Migrations were applied to an isolated SQLite backup of the existing installation and matching was exercised there; no live account or resume was reset. This does not verify every company site or guarantee all vacancies.


## Remote internship and collection repair

113 Django tests cover remote eligibility worldwide/India versus US-only, remote opt-out, city-only Indian locations, preservation of Lever/Ashby remote flags, the remote-internship page, education-duration and preferred-section parsing, and early publication of direct internship matches even if later discovery fails. Excluded jobs skip unnecessary skill extraction while detailed resume guidance retains full scoring.

Live collection of Hevo Data, Weekday and Freshworks public boards succeeded (40, 53 and 20 postings respectively). Reclassification found four eligible internships for each existing CS/zero-year profile, including one remote client vacancy via Weekday. Counts are a point-in-time check, not a promise of future availability. No matching internship was invented to populate an empty screen.


## Questionnaire-driven search (18 November 2026)

133 Django tests pass. The new questionnaire suite verifies that ordinary jobs and internships remain visible without resume skills, that unrelated resumes and resume replacement/deletion do not change search results, that experience comes from answers, and that field/role scope, opportunity type, location, remote restrictions, hybrid/on-site preferences and unknown requirements are applied. Pagination exposes every eligible collected posting. Resume skill comparison and grounded gaps are created only on selection; per-user seen state and safe return from reference upload are covered.

The actual HTTP launcher/worker smoke passed signup to questionnaire, opportunity display before resume upload, reference upload, discovery, selection, seen marking and resume advice. Migrations 0006–0007 were applied to an isolated backup of the existing SQLite installation before delivery. The update preserves confirmed field/role/location/experience choices and removes resume-score thresholds from discovery. Company/source coverage limits still apply. UI templates were rendered through Django tests and the HTTP smoke; no visual browser screenshot inspection was performed.


## JobSearch, parser accuracy and sourced tailoring (19 November 2026)

168 Django tests pass. New regressions cover required versus preferred/professional/internship/project/education experience, months and fractional years, unknown/conflicting ranges, remote restrictions, exact aliases, structured source IDs, source-backed draft validation, invented claims/numbers/certification rejection, private JSON downloads, AI evidence/ID rejection and caches, multiple-master conflicts and explicit version dates, and education/role union search. Existing registration, privacy, discovery, quotas, SQLite concurrency and questionnaire-independence checks remain included.

Desktop/mobile layouts include responsive grids, reduced-motion styling, a mobile navigation toggle, native page transitions with progressive fallback, and a navigation progress indicator. Static Django render previews were generated. Chrome and Edge headless screenshot processes failed under the managed session; visual screenshot inspection was not completed. Live HTTP validation and actual-installation migration results are recorded below when completed. No paid model call is required by the automated tests.


The live HTTP launcher/worker smoke passed after network access was granted: JobSearch branding and static assets, signup, questionnaire, results before resume upload, resume reference upload, collection, selected-job requirements/advice, source-backed draft creation and JSON download. No hosted model call was made. The upgrade was applied first to an isolated copy of the existing installation, preserving all three accounts and two resume records. Existing Desktop data and API keys are preserved during delivery; the legacy SQLite filename is reused automatically, while new installations default to JobSearch.sqlite3.


Desktop delivery completed: additive migration 0008 applied successfully after a consistent SQLite backup. All three existing accounts and both resume records were preserved. Questionnaire-based opportunities were reclassified under policy 5, and the dashboard rendered HTTP 200 with JobSearch branding for every account. API-key settings were preserved. The final suite passes 168 tests and the live synthetic HTTP flow passes through source-backed tailoring and JSON download. Hosted AI behavior is tested with mocked responses and source-validation failures, not a paid live API call.


## Bottom account navigation repair

The avatar/name now links to Profile independently of the logout form. Logout has an explicit Sign out label. Three targeted tests passed: account-link authentication persistence and separate logout behavior, authenticated page rendering, and POST-only logout. Updated Desktop templates/styles and the source archive; no database or API-key change.


## Repository replacement verification — 22 November 2026

All 169 Django tests passed from a clean export of the exact staged Git tree. Migration consistency and staged whitespace checks passed. The upload excludes .env, runtime databases, private resumes, caches and editor state. A staged-file scan found no configured Desktop credential values or private-key/token patterns. The legacy CLI, its unused example configurations and the scheduled email workflow were removed. The previous main commit is retained through Git history and the jobhunt-legacy tag; the replacement is marked jobsearch-v2.0.0.
