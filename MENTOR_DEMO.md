# Current mentor demonstration flow

1. Create an account; the Search questionnaire opens.
2. Choose Student / final-year student, Computer Science, 0 professional years, all roles in the field, jobs and internships, India, and the work arrangement you want. Decide whether to include unstated requirements.
3. Save answers. Browse collected opportunities and internships, including remote results eligible for India or worldwide. Pagination retains all eligible collected results.
4. Upload a resume reference. Discovery does not compare resume keywords or use resume-match thresholds.
5. Select a posting. It is marked seen for that account and the app compares the actual resume against that specific description, showing truthful improvement suggestions and skill gaps. Optional hosted AI provides a deeper review after consent.
6. Replace the reference with a different resume: search answers and opportunity eligibility remain the same, while selected-job advice uses the new reference.

The app cannot guarantee every vacancy on the internet. Official career-page links are not guarantees of extractable postings. No demo data is presented as a live vacancy.

---
Previous implementation notes follow for historical context; the questionnaire flow above is current.

# Mentor demonstration

JobSearch turns the original JobHunt job-search agent into a multi-user, resume-first platform. The browser replaces the email digest. Hosted Gemini/OpenAI/Groq APIs replace any need for a model installed on a user's machine.

## A five-minute demonstration

1. Start `python run.py --demo` and open the displayed local URL. Demo data is explicitly fictional.
2. Register one account and upload `examples/resume.txt`.
3. Show the extracted skills and preferences, then show ranked jobs and the reasons they match.
4. Select a job. Show the full description, existing strengths, missing requirements and specific resume suggestions.
5. Go back: the selected job is now viewed for this user.
6. Register a different account and upload the same example. The first user's seen/saved state does not affect it.
7. If a hosted provider key is configured, enable AI in Profile, open a job and show the evidence-grounded review. Reopening it uses the cached result.
8. Explain the fallback: when AI quota is unavailable, jobs and basic guidance remain useful. No unlimited free inference is promised.

## What changed from JobHunt

- Fixed company watchlists became automatic discovery plus public feeds and career-page extraction.
- A single profile file became authenticated, private per-user resumes and preferences.
- A global seen.json became per-user seen/saved/applied records.
- A daily email became a searchable browser dashboard.
- Application kits became job-specific resume guidance with evidence and gap explanations.
- All-job LLM screening became deterministic matching plus on-demand hosted AI, reducing token costs.

## What to say about coverage

“The platform searches accessible internet sources and automatically discovers new companies. It cannot guarantee every job worldwide because some sources restrict access, some vacancies are not indexed, and feeds can be delayed.”

## What to say about the score

“The score measures explainable skill and role overlap with this resume. It is not a hiring probability or an employer's assessment.”

## What to say about deployment

“The application can run on a Python/Docker host with a shared PostgreSQL database and a background worker. Visitors use a browser; models run at configured online providers. The delivered package is source code and has not been deployed to an external host yet.”
