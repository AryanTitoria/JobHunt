"""Explainable matching runs for every job without spending model tokens."""
import re
from datetime import timedelta
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from careers.models import Job, Match, Preferences
from .resumes import SKILLS, contains, extract_skills
from .opportunities import experience_eligibility, field_internship, field_related, INTERN, FIELDS

STOP = {'and', 'the', 'for', 'with', 'in', 'of', 'a', 'an', 'to', 'at'}
POLICY_VERSION = 5


INDIA_CITIES = r'\b(?:bengaluru|bangalore|bengalore|hyderabad|chennai|pune|mumbai|delhi|noida|gurugram|gurgaon|kolkata|ahmedabad|kochi|indore|jaipur)\b'


def normal_location(value):
    return re.sub(r'\b(?:bangalore|bengalore)\b', 'bengaluru', value.casefold())


def tokens(text):
    return {t for t in re.findall(r'[a-z][a-z0-9+#.]*', text.lower()) if t not in STOP}


def search_ready(preferences):
    if preferences.search_scope in {'education','combined'}:
        return bool(preferences.education_major or preferences.degree_name or (preferences.search_scope=='combined' and preferences.titles))
    return bool(preferences.field_of_study if preferences.search_scope == 'field' and preferences.field_of_study else preferences.titles or preferences.preferred_categories)


def target_role_match(title, roles):
    generic = {'engineer', 'developer', 'development', 'specialist', 'analyst', 'intern', 'internship', 'junior', 'senior'}
    for role in roles:
        terms = tokens(role)
        if not terms:
            continue
        if 'software' in terms or role.casefold() in {'developer', 'software developer', 'software engineer'}:
            if re.search(r'\b(?:software|developer|backend|frontend|full.stack|sde|programmer)\b', title, re.I):
                return True
        specific = terms - generic
        if specific and all(contains(title, term) for term in specific):
            return True
        if not specific and all(contains(title, term) for term in terms):
            return True
    return False


def arrangement(job):
    from .job_parser import remote_details
    return remote_details(job.title, job.location, job.description, job.remote)['mode']


def search_evaluate(job, preferences):
    """Eligibility and ordering depend only on questionnaire answers."""
    reasons = []
    locations = [normal_location(loc.strip()) for loc in preferences.locations if loc.strip()]
    location = normal_location(job.location)
    mode = arrangement(job)
    remote = mode == 'remote'
    from .job_parser import remote_details
    work=remote_details(job.title,job.location,job.description,job.remote)
    global_remote = remote and work['worldwide']
    location_ok = not locations or any(contains(location, loc) for loc in locations)
    foreign = re.search(r'\b(?:united states|usa|canada|germany|australia|united kingdom)\b', location)
    if 'india' in locations and re.search(INDIA_CITIES, location, re.I) and not foreign:
        location_ok = True
    if remote and re.search(r'\bindia\b', location) and any(re.search(INDIA_CITIES, loc, re.I) for loc in locations):
        location_ok = True
    if remote and global_remote:
        location_ok = True
    if not job.location:
        location_ok = not locations
    if remote and work['countries']:
        location_ok = not locations or any(contains(loc, country) or (country=='india' and re.search(INDIA_CITIES,loc,re.I)) for loc in locations for country in work['countries'])
    if remote and not job.location and not work['countries'] and not global_remote:
        location_ok = not locations
    if remote and locations and work.get('excluded_countries'):
        allowed=[loc for loc in locations if not any(contains(loc,country) or (country=='india' and re.search(INDIA_CITIES,loc,re.I)) for country in work['excluded_countries'])]
        if not allowed:location_ok=False
    requested = preferences.work_arrangement
    mode_ok = (mode == requested or requested == 'any' or
               (mode == 'unknown' and requested != 'remote' and preferences.include_unknown_work_arrangement))
    if mode == 'unknown' and not preferences.include_unknown_work_arrangement:
        mode_ok = False
    if requested == 'any' and remote and not preferences.allow_remote:
        mode_ok = False
    experience_ok, experience_reason, level = experience_eligibility(job, preferences)
    internship = level['internship']
    kind_ok = (preferences.opportunity_type == 'both' or
               (preferences.opportunity_type == 'internships' and internship) or
               (preferences.opportunity_type == 'jobs' and not internship))
    if internship and not preferences.include_internships:
        kind_ok = False
    field_match = field_related(job, preferences.field_of_study)
    title_match = target_role_match(job.title, preferences.titles)
    from .education import education_related, employment_type
    education_match=education_related(job,preferences)
    category_match=any(field_related(job,category) for category in preferences.preferred_categories)
    scope=preferences.search_scope
    role_ok=education_match if scope=='education' else (education_match or title_match or category_match) if scope=='combined' else title_match if scope=='roles' else (field_match or category_match or (not preferences.field_of_study and title_match))
    if education_match and scope in {'education','combined'}: reasons.append('Related to your education: '+(preferences.education_major or preferences.degree_name))
    if category_match: reasons.append('Related to a work category you selected')
    kind_ok = kind_ok and (not preferences.employment_types or employment_type(job)=='unknown' or employment_type(job) in preferences.employment_types)
    if any(contains(job.title,phrase) for phrase in preferences.excluded_titles): role_ok=False
    if work['note']: reasons.append(work['note'])
    if role_ok:
        reasons.append(('Related to your chosen field: ' + preferences.field_of_study) if preferences.search_scope == 'field' else 'Matches a role you selected in your questionnaire')
    reasons.append(experience_reason)
    if location_ok:
        reasons.append('Location fits your search answers' if not global_remote else 'Remote opportunity open worldwide')
    else:
        reasons.append('Outside your selected locations or stated remote eligibility')
    if not mode_ok:
        reasons.append('Does not meet your selected work arrangement')
    if mode == 'unknown':
        reasons.append('Work arrangement is unstated; check the original posting')
    if not kind_ok:
        reasons.append('Outside your selected opportunity type')
    eligible = bool(search_ready(preferences) and role_ok and location_ok and experience_ok and mode_ok and kind_ok)
    return {'score': 100 if title_match else 80 if field_match else 0, 'eligible': eligible,
            'matched_skills': [], 'missing_skills': [], 'reasons': reasons,
            'is_field_internship': internship, 'policy_version': POLICY_VERSION}


def evaluate(job, resume, preferences, eligibility_only=False):
    result = search_evaluate(job, preferences)
    if eligibility_only or resume is None:
        return result
    # This comparison runs only for a selected posting's resume advice.
    candidate_skills = preferences.skills or resume.profile.get('core_skills', [])
    jd = f'{job.title}\n{job.description}'
    job_skills = extract_skills(jd)
    matched = [skill for skill in candidate_skills if any(contains(jd, alias) for alias in SKILLS.get(skill, [skill]))]
    candidate_terms = {skill.casefold() for skill in candidate_skills}
    missing = [skill for skill in job_skills if skill.casefold() not in candidate_terms]
    result.update(score=min(100, round(100 * len(matched) / max(1, len(job_skills)))),
                  matched_skills=matched[:30], missing_skills=missing[:20])
    return result


def current_resume(user):
    return user.resumes.order_by('-created').first()


def active_jobs():
    return Job.objects.filter(active=True, last_seen__gte=timezone.now() - timedelta(days=3)).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))


def refresh_matches(user, resume=None, internships_only=False):
    preferences, _ = Preferences.objects.get_or_create(user=user)
    if not search_ready(preferences):
        Match.objects.filter(user=user).delete()
        Preferences.objects.filter(pk=preferences.pk, updated=preferences.updated).update(matching_policy_version=POLICY_VERSION)
        return 0
    count = 0
    # Finish each SELECT before writing: a streaming SQLite cursor can hold a
    # read lock while the collector is waiting to commit its own write.
    cursor = None
    while True:
        page = active_jobs().order_by('pk')
        if internships_only:
            page = page.filter(title__iregex=INTERN)
        if cursor is not None:
            page = page.filter(pk__gt=cursor)
        batch = list(page[:200])
        if not batch:
            break
        matches = [Match(user=user, job=job, resume=None,
                         **evaluate(job, None, preferences, eligibility_only=True)) for job in batch]
        with transaction.atomic():
            # Do not let an older questionnaire overwrite a newer edit.
            if not Preferences.objects.filter(pk=preferences.pk, updated=preferences.updated).exists():
                return count
            Match.objects.bulk_create(matches, batch_size=50, update_conflicts=True,
                unique_fields=['user', 'job'], update_fields=['resume', 'score', 'eligible',
                    'matched_skills', 'missing_skills', 'reasons', 'is_field_internship', 'policy_version', 'updated'])
        count += len(batch)
        cursor = batch[-1].pk
    if not internships_only:
        Preferences.objects.filter(pk=preferences.pk, updated=preferences.updated).update(matching_policy_version=POLICY_VERSION)
    return count


def basic_guidance(job, resume, preferences):
    match = evaluate(job, resume, preferences)
    suggestions = []
    if match['matched_skills']:
        names = ', '.join(match['matched_skills'][:6])
        suggestions.append({'section': 'Summary & skills', 'change': f'Prioritize the relevant skills already supported by your resume: {names}.', 'evidence': ''})
    suggestions.append({'section': 'Experience', 'change': 'Move your most relevant project or role higher. Describe what you built, your contribution, and a result you can substantiate.', 'evidence': ''})
    suggestions.append({'section': 'Formatting', 'change': 'Use clear section headings, searchable text, and consistent dates. Keep the role title and required qualifications easy to locate.', 'evidence': ''})
    gaps = [{'skill': skill, 'advice': 'Not found in your resume. Add it only if you actually have this skill; otherwise treat it as a learning or eligibility gap.'}
            for skill in match['missing_skills'][:8]]
    prefix = '' if job.description_complete else 'Only partial job-description context is available. '
    return {'fit_summary': prefix + f"{len(match['matched_skills'])} matching skills found. Review the gaps and the full posting before applying.",
            'suggestions': suggestions, 'gaps': gaps, 'match': match,
            'disclaimer': 'These are suggestions, not a hiring prediction. Never invent skills, employment, or results.'}
