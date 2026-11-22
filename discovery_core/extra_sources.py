"""Documented public job feeds and optional registered job-search APIs."""
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from urllib.parse import urljoin

from .fetch import Job, strip_html
from .http import FetchError
from .sources import SourceResult


def iso_epoch(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return value or None


def salary(row, low, high, currency, period):
    values = [str(row.get(k)) for k in (low, high) if row.get(k) is not None]
    return ' '.join(filter(None, [str(row.get(currency) or ''), ' – '.join(values), str(row.get(period) or '')]))


@dataclass
class JobicySource:
    max_pages: int = 2
    key = 'feed:jobicy'

    def fetch(self, client):
        jobs, cursor = [], None
        for _ in range(self.max_pages):
            params = {'count': 100}
            if cursor: params['cursor'] = cursor
            body = client.json('https://jobicy.com/api/jobs', params=params, retries=0)
            if not isinstance(body, dict) or body.get('success') is False or not isinstance(body.get('jobs'), list):
                raise FetchError('unexpected Jobicy payload')
            for item in body['jobs']:
                jobs.append(Job(job_id=f"jobicy:{item['id']}", ats='Jobicy', company=item['companyName'],
                    title=item['jobTitle'], location=f"Remote ({item.get('jobGeo') or 'eligibility not stated'})",
                    url=item['url'], application_url=item['url'], description=strip_html(item.get('jobDescription') or item.get('jobExcerpt')),
                    description_complete=bool(item.get('jobDescription')), posted_at=item.get('pubDate'), remote=True,
                    salary=salary(item, 'salaryMin', 'salaryMax', 'salaryCurrency', 'salaryPeriod')))
            next_cursor = body.get('nextCursor')
            if not next_cursor or next_cursor == cursor: break
            cursor = next_cursor
        return SourceResult(self.key, jobs)


class RemoteOKSource:
    key = 'feed:remoteok'

    def fetch(self, client):
        body = client.json('https://remoteok.com/api', retries=0)
        if not isinstance(body, list):
            raise FetchError('unexpected Remote OK payload')
        jobs = []
        for item in body:
            if not isinstance(item, dict):
                raise FetchError('unexpected Remote OK row')
            if 'legal' in item and 'id' not in item: continue
            if not item.get('id'): continue
            url = item.get('url') or f"https://remoteok.com/remote-jobs/{item['id']}"
            location = item.get('location') or 'eligibility not stated'
            jobs.append(Job(job_id=f"remoteok:{item['id']}", ats='Remote OK', company=item.get('company') or 'Employer not supplied',
                title=item['position'], location=f'Remote ({location})', url=url, application_url=url,
                description=strip_html(item.get('description')), posted_at=item.get('date') or iso_epoch(item.get('epoch')),
                remote=True, salary=salary(item, 'salary_min', 'salary_max', 'salary_currency', 'salary_period')))
        return SourceResult(self.key, jobs)


@dataclass
class HimalayasSource:
    max_pages: int = 3
    key = 'feed:himalayas'

    def fetch(self, client):
        jobs, cursor = [], None
        for _ in range(self.max_pages):
            params = {'limit': 20}
            if cursor: params['cursor'] = cursor
            body = client.json('https://himalayas.app/jobs/api', params=params, retries=0)
            if not isinstance(body, dict) or not isinstance(body.get('jobs'), list):
                raise FetchError('unexpected Himalayas payload')
            for item in body['jobs']:
                countries = item.get('locationRestrictions') or []
                zones = item.get('timezoneRestrictions') or []
                # Empty countries do not override restrictions on eligible time zones.
                region = ', '.join(str(c) for c in countries)
                if not region:
                    region = 'Worldwide' if not zones else 'timezone-restricted; countries not specified'
                if zones:
                    region += '; UTC offsets: ' + ', '.join(map(str, zones))
                guid = str(item['guid'])
                url = urljoin('https://himalayas.app', guid)
                jobs.append(Job(job_id='himalayas:' + guid, ats='Himalayas', company=item['companyName'],
                    title=item['title'], location=f'Remote ({region})', url=url,
                    application_url=item['applicationLink'], description=strip_html(item.get('description') or item.get('excerpt')),
                    description_complete=bool(item.get('description')), posted_at=iso_epoch(item.get('pubDate')),
                    valid_through=iso_epoch(item.get('expiryDate')), remote=True,
                    salary=salary(item, 'minSalary', 'maxSalary', 'currency', 'salaryPeriod')))
            next_cursor = body.get('nextCursor')
            if not next_cursor or next_cursor == cursor: break
            cursor = next_cursor
        return SourceResult(self.key, jobs)


@dataclass
class AdzunaSource:
    country: str
    query: str
    location: str = ''
    max_pages: int = 1
    key: str = 'search:adzuna'

    def fetch(self, client):
        jobs = []
        for page in range(1, self.max_pages + 1):
            reserve = getattr(client, 'reserve_job_api', None)
            if reserve is not None and not reserve('adzuna'):
                raise FetchError('Adzuna daily application allowance reached')
            params = {'app_id': os.environ['ADZUNA_APP_ID'], 'app_key': os.environ['ADZUNA_APP_KEY'],
                      'what': self.query, 'results_per_page': 50, 'content-type': 'application/json', 'sort_by': 'date'}
            if self.location: params['where'] = self.location
            body = client.json(f'https://api.adzuna.com/v1/api/jobs/{self.country}/search/{page}', params=params, retries=0)
            if not isinstance(body, dict) or not isinstance(body.get('results'), list):
                raise FetchError('unexpected Adzuna payload')
            for item in body['results']:
                url = item['redirect_url']
                jobs.append(Job(job_id=f"adzuna:{self.country}:{item['id']}", ats='Adzuna',
                    company=(item.get('company') or {}).get('display_name') or 'Employer not supplied',
                    title=strip_html(item['title']), location=(item.get('location') or {}).get('display_name') or '',
                    url=url, application_url=url, description=strip_html(item.get('description')),
                    description_complete=False, posted_at=item.get('created')))
            if not body['results']: break
        return SourceResult(self.key, jobs)


@dataclass
class USAJobsSource:
    query: str
    max_pages: int = 1
    key: str = 'search:usajobs'

    def fetch(self, client):
        jobs = []
        for page in range(1, self.max_pages + 1):
            reserve = getattr(client, 'reserve_job_api', None)
            if reserve is not None and not reserve('usajobs'):
                raise FetchError('USAJOBS daily application allowance reached')
            body = client.json('https://data.usajobs.gov/api/search',
                params={'Keyword': self.query, 'ResultsPerPage': 100, 'Page': page},
                headers={'Host': 'data.usajobs.gov', 'User-Agent': os.environ['USAJOBS_USER_AGENT'],
                         'Authorization-Key': os.environ['USAJOBS_API_KEY']}, retries=0)
            result = body.get('SearchResult') if isinstance(body, dict) else None
            if not isinstance(result, dict) or not isinstance(result.get('SearchResultItems'), list):
                raise FetchError('unexpected USAJOBS payload')
            for row in result['SearchResultItems']:
                item = row['MatchedObjectDescriptor']
                details = (item.get('UserArea') or {}).get('Details') or {}
                description = '\n\n'.join(str(t) for t in [
                    (item.get('PositionSummary') or {}).get('PositionSummaryText', ''),
                    item.get('QualificationSummary', ''), details.get('MajorDuties', ''),
                    details.get('Requirements', ''), details.get('Education', ''),
                    details.get('WhoMayApply', '')] if t)
                url = item['PositionURI']
                jobs.append(Job(job_id='usajobs:' + str(row['MatchedObjectId']), ats='USAJOBS',
                    company=item.get('OrganizationName') or 'US Federal Government', title=item['PositionTitle'],
                    location=item.get('PositionLocationDisplay') or 'United States', url=url, application_url=url,
                    description=strip_html(description), description_complete=False,
                    posted_at=item.get('PublicationStartDate'), valid_through=item.get('ApplicationCloseDate')))
            if not result['SearchResultItems']: break
        return SourceResult(self.key, jobs)
