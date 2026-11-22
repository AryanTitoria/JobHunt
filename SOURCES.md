# More job sources and free-allowance web discovery

This version combines five public job APIs, two optional registered job APIs, five ATS connectors, RSS/Atom feeds, structured career pages, and configurable Tavily/Brave web discovery. No single source covers every vacancy. More sources improve coverage, not completeness.

## Job APIs

| Provider | Setup | Coverage / limits |
| --- | --- | --- |
| Remotive | No key | Remote jobs; public data delayed about 24 hours. Polled at most every six hours. |
| Arbeitnow | No key | Mostly European jobs. Bounded page collection; source attribution retained. |
| Jobicy | No key | Remote jobs from the recent seven-day window, with a three-hour publication delay. Public listing links are used; paid direct-link mode is never requested. |
| Remote OK | No key | Remote listings. Source name and followable source links are displayed; its logo is not used. |
| Himalayas | No key | Remote jobs with country/time-zone restrictions and expiry. Original applicationLink is kept unchanged, with visible source credit. |
| Adzuna | APP ID + APP KEY; enable explicitly | Job search by role and location. Free evaluation access and account-specific quotas, not unlimited permanent free use. Standard descriptions are snippets; organisational/commercial licensing requirements apply. |
| USAJOBS | Registered API key + registered email; enable explicitly | US federal vacancies across occupations. Hiring paths, citizenship, qualifications and other eligibility conditions must be checked. Returned context is labelled partial. |

The existing Greenhouse, Lever and Ashby connectors continue to collect discovered company boards. They are not central search engines: a board URL or identifier still has to be discovered first. The user does not have to maintain a predefined company list.

The **Job sources** page distinguishes enabled no-key APIs, optional APIs awaiting credentials, configured search providers, observed source health, posting counts, and application-side usage counters. A configured key is not represented as a verified successful connection until the provider actually responds.

## Add Tavily web search

Keep your existing Gemini key. Add these lines to your existing `.env` (do not replace the file or paste credentials into chat):

```dotenv
SEARCH_PROVIDERS=tavily
TAVILY_API_KEY=your-tavily-key
TAVILY_MONTHLY_LIMIT=800
```

Restart with `python run.py` and click **Refresh discovery**. That button requests a new web search, subject to the button's three-per-hour limit and the shared monthly cap. It does not bypass job-feed cooldowns.

Tavily's free plan currently offers 1,000 credits per month without a credit card. This integration explicitly uses basic search, disables automatic parameter selection, and does not request generated answers or raw page content. Basic search currently costs one credit per request. The default 800-attempt application allowance leaves headroom; it is not a live reading of your Tavily balance and cannot account for other apps using your account. Actual provider terms and pricing remain authoritative. Free-plan requests stop when provider credits are exhausted unless you have enabled a paid arrangement in your account.

You can retain Brave as well:

```dotenv
SEARCH_PROVIDERS=tavily,brave
TAVILY_API_KEY=your-tavily-key
BRAVE_SEARCH_API_KEY=your-brave-key
TAVILY_MONTHLY_LIMIT=800
BRAVE_MONTHLY_LIMIT=800
```

Calls rotate across configured providers within the same total per-run query budget. Adding a second provider does not multiply the query budget. Failed attempts count toward the local cap; quota-counted search requests are not automatically retried. The counters reset by UTC calendar month for this installation, which may differ from an account-specific provider billing cycle. Search receives target role/location queries, not resume contents. Search snippets never become jobs by themselves; the linked posting/board must be fetched and parsed.

## Enable Adzuna

Register at https://developer.adzuna.com/ and review the access and licensing terms applicable to your use. Add to `.env`:

```dotenv
ADZUNA_APP_ID=your-app-id
ADZUNA_APP_KEY=your-app-key
JOB_API_DAILY_LIMIT=40
```

In `discovery.json`:

```json
"adzuna": {"enabled": true, "country": "in", "max_queries": 2, "max_pages": 1}
```

`in` is the requested market code; use a country supported by your Adzuna account. Per-user target roles and the first preferred location drive the request. With multiple preferred countries, configure the intended market rather than assuming one endpoint searches all countries. Application redirect URLs remain unchanged. Every displayed Adzuna-derived listing has a visible linked attribution. The platform does not crawl third-party sites to expand Adzuna snippets. It labels the context as partial and tells the AI not to infer missing requirements.

## Enable USAJOBS

Get credentials through https://developer.usajobs.gov/. Add:

```dotenv
USAJOBS_API_KEY=your-api-key
USAJOBS_USER_AGENT=your-registered-email
```

Set `"usajobs": {"enabled": true, "max_queries": 2, "max_pages": 1}` in `discovery.json`. This searches US federal vacancies, not the entire US private-sector market. The registered email is sent only in the provider's required User-Agent header; it is not shown to visitors.

`JOB_API_DAILY_LIMIT` is a shared per-provider application attempt cap for Adzuna and USAJOBS. A lower provider/account allowance still applies. The cap is not a promise of zero billing on an independently configured paid account.

## Configure public feeds

The new public feeds are enabled by default. You can disable any in `discovery.json`:

```json
"jobicy": true,
"jobicy_pages": 2,
"remoteok": true,
"himalayas": true,
"himalayas_pages": 3
```

All API/page counts are bounded. A single run does not download an entire global index. Increasing a page budget can expand coverage but must respect provider limits. Public feed checks share cached inventory and default six-hour cooldowns across users. A partial feed's absence does not prove a job has closed. Explicit expiry dates and the three-day observation gate still apply; always check the original application page.

Unsupported or undocumented services are not added merely to increase a source count. In particular, an old API URL redirecting to a marketing page is not treated as a working connector. Generic RSS/Atom support remains available for other sources whose feeds you are allowed to use.

## Upgrade

This update adds two job fields and a committed migration. `run.py` applies migrations before starting the web app and worker. Stop the old process with Ctrl+C, update code, and restart normally. Existing accounts, resume data, seen/saved history, Gemini settings and source registry are preserved. No database reset is needed.

## Documentation checked during implementation

- Tavily pricing/credits: https://docs.tavily.com/documentation/api-credits
- Tavily Search request fields: https://docs.tavily.com/documentation/api-reference/endpoint/search
- Jobicy API and attribution: https://jobicy.com/jobs-rss-feed
- Remote OK API and response-embedded terms: https://remoteok.com/api
- Himalayas API and terms links: https://himalayas.app/api
- Adzuna search: https://developer.adzuna.com/docs/search
- Adzuna access and terms: https://developer.adzuna.com/docs/terms_of_service
- USAJOBS Search: https://developer.usajobs.gov/api-reference/get-api-search

The platform does not purchase credits, register provider accounts, enable auto-top-ups, or create extra accounts to evade quota limits.


### India company careers

`india_careers.json` supplies 11 official starting pages, including TCS, Infosys, Wipro, HCLTech, Accenture, Google, Microsoft, Amazon, Zoho, Freshworks and Tech Mahindra. India-location discovery registers these pages automatically. The Sources screen links to them even when extraction is unavailable. Page extraction follows up to eight relevant same-host links, one level deep, under the existing per-run page budget. Empty pages without structured jobs or further discoverable links report an extraction limitation rather than a connected job feed.

Recruitee published offers: https://docs.recruitee.com/reference/offers . SmartRecruiters public postings: https://developers.smartrecruiters.com/docs/posting-api . Authentication errors are reported as source failures; no restricted access is bypassed. SmartRecruiters is bounded to 100 summary rows and 20 details per board per check; it cannot close missing jobs. Broader coverage requires additional sources/connectors, and no configuration covers every company.
