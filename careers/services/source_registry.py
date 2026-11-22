"""Source capabilities, public configuration, and application-side search caps."""
import os
from django.conf import settings
from django.db.models import F
from django.utils import timezone
from careers.models import BudgetBucket, Source
from discovery_core.search import configured_search_providers

PUBLIC_SOURCES = [
    ('remotive', 'Remotive', 'https://remotive.com', 'Remote jobs; public feed delayed about 24 hours.'),
    ('arbeitnow', 'Arbeitnow', 'https://www.arbeitnow.com', 'Mostly European jobs, including remote roles.'),
    ('jobicy', 'Jobicy', 'https://jobicy.com', 'Remote jobs across disciplines; recent seven-day feed.'),
    ('remoteok', 'Remote OK', 'https://remoteok.com', 'Remote vacancies with original source links.'),
    ('himalayas', 'Himalayas', 'https://himalayas.app', 'Remote roles with country, time-zone and expiry metadata.'),
]


def bounded(config, name, default, maximum=10):
    value = config.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f'{name} must be an integer from 1 to {maximum}')
    return value


def metadata(label, url, **config):
    # `name` is a provider config field, so it must not collide with this argument.
    return {'attribution_name': label, 'attribution_url': url, **config}


def web_limits():
    return {'tavily': settings.TAVILY_MONTHLY_LIMIT, 'brave': settings.BRAVE_MONTHLY_LIMIT}


def reserve_search(provider):
    # Counts attempts before requests. No response, URL, key or resume is stored.
    month = timezone.now().strftime('%Y-%m')
    bucket, _ = BudgetBucket.objects.get_or_create(key=f'web:{provider}:{month}')
    limit = web_limits().get(provider, 0)
    return bool(BudgetBucket.objects.filter(pk=bucket.pk, used__lt=limit).update(used=F('used') + 1))


def search_usage():
    month = timezone.now().strftime('%Y-%m')
    configured = configured_search_providers()
    return [{'name': name.title(), 'configured': name in configured, 'limit': limit,
             'used': BudgetBucket.objects.filter(key=f'web:{name}:{month}').values_list('used', flat=True).first() or 0}
            for name, limit in web_limits().items()]


def reserve_job_api(provider):
    day = timezone.now().date().isoformat()
    bucket, _ = BudgetBucket.objects.get_or_create(key=f'jobs:{provider}:{day}')
    return bool(BudgetBucket.objects.filter(pk=bucket.pk, used__lt=settings.JOB_API_DAILY_LIMIT).update(used=F('used') + 1))


def availability(config):
    rows = [{'name': label, 'state': 'Enabled — no key needed' if config.get(key, True) else 'Disabled',
             'description': description} for key, label, url, description in PUBLIC_SOURCES]
    adzuna_keys = bool(os.getenv('ADZUNA_APP_ID') and os.getenv('ADZUNA_APP_KEY'))
    usa_keys = bool(os.getenv('USAJOBS_API_KEY') and os.getenv('USAJOBS_USER_AGENT'))
    rows += [
        {'name': 'Adzuna', 'state': 'Configured' if config.get('adzuna', {}).get('enabled', False) and adzuna_keys else 'Optional — add credentials and enable',
         'description': 'Keyword/location job search. Free evaluation access; account limits and licensing apply. Descriptions are snippets.'},
        {'name': 'USAJOBS', 'state': 'Configured' if config.get('usajobs', {}).get('enabled', False) and usa_keys else 'Optional — add credentials and enable',
         'description': 'US federal vacancies across occupations. Check hiring paths, citizenship and eligibility.'}]
    return rows
