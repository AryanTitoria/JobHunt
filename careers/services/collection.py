"""JobHunt's public connectors adapted to a shared, multi-user inventory."""
import hashlib
import json
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Exists, OuterRef
from django.utils import timezone

from careers.models import Job, Source, Sighting, Preferences
from discovery_core.discovery import Board, board_from_url, discover
from discovery_core.http import HTTPClient
from discovery_core.identity import canonical_url, fingerprint, content_hash
from discovery_core.prefilter import _parse_date
from discovery_core.sources import ATSSource, ArbeitnowSource, RemotiveSource, PageSource, RSSSource, collect, SourceResult
from discovery_core.extra_sources import JobicySource, RemoteOKSource, HimalayasSource, AdzunaSource, USAJobsSource
from discovery_core.search import configured_search_providers
from .source_registry import bounded, metadata, reserve_search, reserve_job_api, PUBLIC_SOURCES
import os
import re


def register_board(board):
    return Source.objects.get_or_create(key=board.key, defaults={'kind': 'ats', 'config': board.to_dict()})[0]


def register_page(url, depth=0):
    url = canonical_url(url)
    key = 'page:' + hashlib.sha256(url.encode()).hexdigest()
    return Source.objects.get_or_create(key=key, defaults={'kind': 'page', 'config': {'url': url, 'depth': depth}})[0]


def ingest(source, result, demo=False):
    stamp = timezone.now()
    source.last_checked = stamp
    source.next_check = stamp + timedelta(hours=6)
    source.error = (result.error or '')[:250]
    source.count = len(result.jobs)
    if not result.success:
        source.save()
        return 0
    created = 0
    # Commit each posting promptly. Never hold a writer lock for an entire
    # board while the upload view is trying to persist a user's matches.
    for item in result.jobs:
        with transaction.atomic():
            url = canonical_url(item.url)
            url_hash = hashlib.sha256(url.encode()).hexdigest()
            fp = fingerprint(item) or ''
            external_id = item.job_id if len(item.job_id.encode('utf-8')) <= 500 else 'sha256:' + hashlib.sha256(item.job_id.encode()).hexdigest()
            sighting = Sighting.objects.filter(source=source, external_id=external_id).select_related('job').first()
            job = sighting.job if sighting else Job.objects.filter(Q(url_hash=url_hash) | Q(url=url)).first()
            if job is None and fp:
                job = Job.objects.filter(fingerprint=fp).order_by('first_seen').first()
            data = {'url': url, 'url_hash': url_hash, 'fingerprint': fp, 'content_hash': content_hash(item),
                    'title': item.title[:300], 'company': item.company[:200], 'location': item.location[:300],
                    'description': item.description[:80000], 'provider': item.ats[:60],
                    'description_complete': item.description_complete,
                    'application_url': item.application_url or item.url,
                    'salary': str(item.salary or '')[:300], 'posted_at': _parse_date(item.posted_at),
                    'expires_at': _parse_date(item.valid_through), 'remote': item.remote,
                    'last_seen': stamp, 'active': True, 'is_demo': demo}
            if job is None:
                job = Job.objects.create(**data)
                created += 1
            elif item.ats in {'greenhouse', 'lever', 'ashby'} or job.provider not in {'greenhouse', 'lever', 'ashby'}:
                # Keep the canonical identity while updating preferred source details.
                for name, value in data.items():
                    if name not in {'url_hash'}:
                        setattr(job, name, value)
                job.save()
            else:
                job.last_seen, job.active = stamp, True
                job.save(update_fields=['last_seen', 'active'])
            Sighting.objects.update_or_create(source=source, external_id=external_id,
                                              defaults={'job': job, 'last_seen': stamp, 'active': True})
    # Only reconcile absence after every posting in a valid snapshot was saved.
    # A partially processed/failed snapshot must never close unseen jobs.
    with transaction.atomic():
        if result.authoritative:
            Sighting.objects.filter(source=source).exclude(last_seen=stamp).update(active=False)
            any_active = Sighting.objects.filter(job_id=OuterRef('pk'), active=True)
            touched = Sighting.objects.filter(source=source).values('job_id')
            Job.objects.filter(pk__in=touched).update(active=Exists(any_active))
        # Direct ATS closure outranks stale syndication, using bounded SQL rather
        # than thousands of SELECT/UPDATE pairs inside the writer transaction.
        direct = Sighting.objects.filter(job_id=OuterRef('pk'), source__kind='ats')
        Job.objects.filter(Exists(direct)).update(active=Exists(direct.filter(active=True)))
        source.last_success = stamp
        source.save()
    return created


def due(source):
    return source.next_check is None or source.next_check <= timezone.now()


def _fetch(source, connector, client):
    # A short lease stops overlapping workers from hammering the same endpoint.
    stamp = timezone.now()
    updated = Source.objects.filter(pk=source.pk).filter(
        Q(locked_until__isnull=True) | Q(locked_until__lt=stamp)).update(locked_until=stamp + timedelta(minutes=15))
    if not updated:
        return None
    try:
        result = collect(connector, client)
        ingest(source, result)
        for board in result.boards:
            register_board(board)
        for url in result.pages:
            register_page(url, depth=1)
        return result
    finally:
        Source.objects.filter(pk=source.pk).update(locked_until=None)


def collect_inventory(user=None, force_search=False):
    from .matching import refresh_matches
    if settings.DEMO_MODE:
        load_demo_inventory()
        if user: refresh_matches(user)
        return {'sources': 1, 'jobs': Job.objects.filter(is_demo=True).count(), 'errors': []}
    config_path = settings.BASE_DIR / 'discovery.json'
    config = json.loads(config_path.read_text(encoding='utf-8-sig')) if config_path.exists() else {}
    preferences = Preferences.objects.filter(user=user).first() if user else None
    from .search_preferences import search_titles
    titles = search_titles(preferences) if preferences else config.get('titles', ['software engineer'])
    locations = preferences.locations if preferences else config.get('locations', ['India'])
    career_options = {'years_experience': preferences.years_experience if preferences else 0,
                      'field_of_study': preferences.field_of_study if preferences else '',
                      'include_internships': preferences.include_internships if preferences else True,
                      'allow_remote': preferences.allow_remote if preferences else True,
                      'opportunity_type': preferences.opportunity_type if preferences else 'both',
                      'work_arrangement': preferences.work_arrangement if preferences else 'any',
                      'search_scope': preferences.search_scope if preferences else 'field',
                      'education_major': preferences.education_major if preferences else '',
                      'degree_name': preferences.degree_name if preferences else '',
                      'employment_types': preferences.employment_types if preferences else [],
                      'targeted_titles': preferences.titles if preferences else []}
    directory_path = settings.BASE_DIR / 'india_careers.json'
    directory = json.loads(directory_path.read_text()) if directory_path.exists() else []
    india = any(re.search(r'india|bengal|bangalore|hyderabad|pune|mumbai|delhi|noida|chennai|kolkata|gurugram|gurgaon', loc, re.I) for loc in locations)
    if india and config.get('india_career_sites', True):
        for company in directory:
            board = board_from_url(company['url'])
            register_board(board) if board else register_page(company['url'])
        from urllib.parse import urlsplit
        career_options['career_domains'] = [urlsplit(row['url']).hostname for row in directory]
    search_key = hashlib.sha256(json.dumps([titles, locations, career_options, configured_search_providers()]).encode()).hexdigest()
    state, _ = Source.objects.get_or_create(key='search:' + search_key, defaults={'kind': 'search', 'config': {}})
    report = {'sources': 0, 'jobs': 0, 'errors': []}
    client = HTTPClient(timeout=15, retries=1, delay=1, max_bytes=12_000_000)
    client.reserve_job_api = reserve_job_api
    try:
        # Public ATS boards run before broad web search and generic pages.
        # Publish field internships promptly even if a later source is slow.
        board_path = settings.BASE_DIR / 'india_ats_boards.json'
        if india and config.get('india_career_sites', True) and board_path.exists():
            for row in json.loads(board_path.read_text(encoding='utf-8')):
                board = Board(**row)
                source = register_board(board)
                if due(source):
                    result = _fetch(source, ATSSource(board), client)
                    if result:
                        report['sources'] += 1
                        report['jobs'] += len(result.jobs)
                        if not result.success:
                            report['errors'].append(result.error)
            if user:
                refresh_matches(user, internships_only=True)
        if due(state) or force_search:
            dc = {'titles': titles, 'location': ', '.join(locations), 'max_queries': settings.DISCOVERY_MAX_QUERIES,
                  'max_pages': settings.DISCOVERY_MAX_PAGES, 'seed_urls': config.get('seed_urls', []),
                  'reserve_search': reserve_search, **career_options}
            boards, pages, warnings, cursor = discover(client, {}, dc, state.config.get('cursor', 0))
            for board in boards: register_board(board)
            for url in pages: register_page(url)
            state.config = {'cursor': cursor}
            state.last_checked = timezone.now()
            # Do not hide a corrected key or transient error for a whole day.
            state.next_check = timezone.now() + timedelta(hours=1 if any(w.startswith('search:') for w in warnings) else 24)
            state.error = '; '.join(warnings)[:250]
            state.save()
            report['errors'].extend(warnings)
        for url in config.get('seed_urls', []):
            board = board_from_url(url)
            register_board(board) if board else register_page(url)
        connectors = [('remotive', RemotiveSource()),
                      ('arbeitnow', ArbeitnowSource(bounded(config, 'arbeitnow_pages', 2))),
                      ('jobicy', JobicySource(bounded(config, 'jobicy_pages', 2))),
                      ('remoteok', RemoteOKSource()),
                      ('himalayas', HimalayasSource(bounded(config, 'himalayas_pages', 3)))]
        labels = {key: (label, url) for key, label, url, description in PUBLIC_SOURCES}
        for name, connector in connectors:
            if not config.get(name, True): continue
            label, homepage = labels[name]
            source, _ = Source.objects.get_or_create(key=connector.key,
                defaults={'kind': 'feed', 'config': metadata(label, homepage, name=name)})
            if source.config.get('attribution_name') != label:
                source.config.update(metadata(label, homepage, name=name))
                source.save(update_fields=['config'])
            if due(source):
                result = _fetch(source, connector, client)
                if result:
                    report['sources'] += 1
                    report['jobs'] += len(result.jobs)
                    if not result.success: report['errors'].append(result.error)
        # Query-specific source keys prevent one user's search/cooldown replacing
        # another's. Returned public listings still join the shared inventory.
        keyed = []
        adzuna = config.get('adzuna', {})
        if adzuna.get('enabled', False) and os.getenv('ADZUNA_APP_ID') and os.getenv('ADZUNA_APP_KEY'):
            country = str(adzuna.get('country', 'in')).lower()
            if not re.fullmatch('[a-z]{2}', country): raise ValueError('Adzuna country must be a two-letter code')
            for title in titles[:bounded(adzuna, 'max_queries', 2, 5)]:
                location = locations[0] if locations else ''
                digest = hashlib.sha256(json.dumps([country, title, location]).encode()).hexdigest()[:24]
                key = f'adzuna:{country}:{digest}'
                homepage = {'in': 'https://www.adzuna.in', 'gb': 'https://www.adzuna.co.uk',
                            'us': 'https://www.adzuna.com'}.get(country, 'https://www.adzuna.com')
                connector = AdzunaSource(country, title, location, bounded(adzuna, 'max_pages', 1, 3), key)
                keyed.append((key, connector, metadata('Adzuna', homepage, country=country)))
        usa = config.get('usajobs', {})
        if usa.get('enabled', False) and os.getenv('USAJOBS_API_KEY') and os.getenv('USAJOBS_USER_AGENT'):
            for title in titles[:bounded(usa, 'max_queries', 2, 5)]:
                key = 'usajobs:' + hashlib.sha256(title.encode()).hexdigest()[:24]
                keyed.append((key, USAJobsSource(title, bounded(usa, 'max_pages', 1, 3), key),
                              metadata('USAJOBS', 'https://www.usajobs.gov')))
        for key, connector, details in keyed:
            source, _ = Source.objects.get_or_create(key=key, defaults={'kind': 'job_api', 'config': details})
            if due(source):
                result = _fetch(source, connector, client)
                if result:
                    report['sources'] += 1
                    report['jobs'] += len(result.jobs)
                    if not result.success: report['errors'].append(result.error)
        for row in config.get('rss', []):
            connector = RSSSource(row['url'], row.get('name', 'RSS'))
            source, _ = Source.objects.get_or_create(key='rss:' + hashlib.sha256(row['url'].encode()).hexdigest(),
                                                   defaults={'kind': 'rss', 'config': row})
        limits = [('rss', 10), ('page', settings.DISCOVERY_MAX_PAGES), ('ats', settings.DISCOVERY_MAX_BOARDS)]
        for kind, limit in limits:
            sources = Source.objects.filter(kind=kind).filter(Q(next_check__isnull=True) | Q(next_check__lte=timezone.now())).order_by('last_checked')[:limit]
            for source in sources:
                if kind == 'ats': connector = ATSSource(Board(**source.config))
                elif kind == 'page': connector = PageSource(source.config['url'], depth=source.config.get('depth', 0))
                else: connector = RSSSource(source.config['url'], source.config.get('name', 'RSS'))
                result = _fetch(source, connector, client)
                if result:
                    report['sources'] += 1
                    report['jobs'] += len(result.jobs)
                    if not result.success: report['errors'].append(result.error)
        if user:
            refresh_matches(user)
    finally:
        client.close()
    return report


def load_demo_inventory():
    from discovery_core.fetch import Job as Posting
    stamp = timezone.now().isoformat()
    examples = [
        ('Backend Engineer', 'Northstar', 'Bengaluru, India', 'Python, Django, SQL, PostgreSQL, Docker', 'Build reliable APIs and services for a growing product team.'),
        ('Software Engineer', 'Orbit Labs', 'Remote (Worldwide)', 'Python, JavaScript, Git, REST APIs', 'Work across product services and developer tools.'),
        ('Data Engineer', 'Fieldwork', 'Hyderabad, India', 'Python, SQL, Kafka, AWS, PostgreSQL', 'Design clean data pipelines and collaborate with analytics teams.'),
        ('Frontend Engineer', 'Forma', 'Remote (India)', 'React, TypeScript, HTML, CSS, Figma', 'Build accessible interfaces for complex workflows.'),
        ('Machine Learning Engineer', 'Lumen', 'Pune, India', 'Python, Machine Learning, PyTorch, Pandas, SQL', 'Turn experiments into maintainable services.'),
        ('Platform Engineer', 'Atlas', 'Bengaluru, India', 'Go, Docker, Kubernetes, Terraform, AWS, Linux', 'Improve the platform used by engineering teams.'),
        ('Junior Software Developer', 'Clearpath', 'Noida, India', 'Python, Java, SQL, Git, Testing', 'Pair with experienced engineers and ship well-tested features.'),
        ('Marketing Analyst', 'Juniper', 'Mumbai, India', 'Excel, Data Analysis, SEO, Digital Marketing', 'Use data to understand and improve marketing performance.'),
        ('Financial Analyst', 'Ledger', 'Delhi, India', 'Accounting, Excel, Financial Analysis, Auditing', 'Prepare clear financial reporting and support planning.'),
        ('Registered Nurse', 'Carewell', 'Chennai, India', 'Nursing, Patient Care, Communication', 'Support safe, patient-centered clinical care.'),
        ('UX Designer', 'Forma', 'Remote (Worldwide)', 'UX Design, Figma, UI Design, Communication', 'Research user needs and design clear product experiences.'),
        ('Senior Backend Engineer', 'Northstar', 'Remote (United States)', 'Python, Kubernetes, AWS, PostgreSQL', 'Lead service architecture; 7 years of experience required.'),
    ]
    postings = []
    for i, (title, company, location, skills, description) in enumerate(examples):
        postings.append(Posting(job_id=f'demo:{i}', ats='Demo data', company=company, title=title,
            location=location, url=f'https://example.com/JobSearch-demo/{i}',
            description=f'{description}\n\nWhat you will work on\n{description}\n\nSkills: {skills}\n\n'
                        'Experience: 0–3 years of professional experience.\nWe value clear communication, practical problem solving, and work you can explain. '
                        'This is fictional demonstration data, not an active vacancy.',
            posted_at=stamp, remote='Remote' in location))
    source, _ = Source.objects.get_or_create(key='demo:inventory', defaults={'kind': 'demo'})
    return ingest(source, SourceResult(source.key, postings, authoritative=True), demo=True)
