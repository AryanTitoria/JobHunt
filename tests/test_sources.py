import os
from types import SimpleNamespace
from unittest.mock import patch
import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone

from careers.models import BudgetBucket, Source, Job
from careers.services.collection import ingest
from careers.services.source_registry import reserve_search, reserve_job_api, availability
from discovery_core.discovery import discover
from discovery_core.search import search_urls, configured_search_providers
from discovery_core.extra_sources import JobicySource, RemoteOKSource, HimalayasSource, AdzunaSource, USAJobsSource
from discovery_core.sources import collect
from discovery_core.http import HTTPClient, FetchError


class JSONClient:
    def __init__(self, bodies):
        self.bodies, self.calls = iter(bodies), []
    def json(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = next(self.bodies)
        if isinstance(value, Exception): raise value
        return value


def jobicy_row(**overrides):
    row = {'id': 1, 'url': 'https://jobicy.com/jobs/one?u=source', 'jobTitle': 'Python Engineer',
           'companyName': 'Acme', 'jobGeo': 'Anywhere', 'jobDescription': '<p>Python and Django APIs</p>',
           'pubDate': '2026-11-18T00:00:00Z'}
    row.update(overrides)
    return row


class PublicConnectorTests(SimpleTestCase):
    def test_jobicy_paginates_and_retains_source_link(self):
        client = JSONClient([{'jobs': [jobicy_row()], 'nextCursor': 'cursor-2'},
                             {'jobs': [jobicy_row(id=2)], 'nextCursor': None}])
        result = collect(JobicySource(2), client)
        self.assertTrue(result.success)
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual(client.calls[1][1]['params']['cursor'], 'cursor-2')
        self.assertEqual(result.jobs[0].application_url, 'https://jobicy.com/jobs/one?u=source')
        self.assertFalse(result.authoritative)

    def test_invalid_jobicy_response_is_not_empty_success(self):
        self.assertFalse(collect(JobicySource(), JSONClient([{'error': 'unavailable'}])).success)

    def test_partial_page_failure_is_contained(self):
        result = collect(JobicySource(2), JSONClient([{'jobs': [jobicy_row()], 'nextCursor': '2'}, FetchError('HTTP 503')]))
        self.assertFalse(result.success)
        self.assertEqual(result.jobs, [])

    def test_remoteok_skips_legal_metadata_and_preserves_source(self):
        result = collect(RemoteOKSource(), JSONClient([[{'legal': 'credit source'},
            {'id': '1', 'position': 'Engineer', 'company': 'Acme', 'location': 'Worldwide',
             'url': 'https://remoteok.com/remote-jobs/one', 'description': '<p>Python</p>'}]]))
        self.assertTrue(result.success)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0].ats, 'Remote OK')
        self.assertEqual(result.jobs[0].description, 'Python')

    def test_remoteok_unknown_location_does_not_claim_worldwide(self):
        result = collect(RemoteOKSource(), JSONClient([[{'id': '1', 'position': 'Engineer', 'company': 'Acme',
            'url': 'https://remoteok.com/remote-jobs/one', 'description': 'Python'}]]))
        self.assertNotIn('Worldwide', result.jobs[0].location)

    def test_himalayas_retains_original_application_link_and_expiry(self):
        client = JSONClient([{'jobs': [{'guid': '/companies/acme/jobs/one', 'title': 'Engineer',
            'companyName': 'Acme', 'description': '<p>Python APIs</p>', 'pubDate': 1794950000,
            'expiryDate': 1795950000, 'locationRestrictions': ['India'], 'timezoneRestrictions': [5.5],
            'applicationLink': 'https://example.org/apply?id=42&utm_source=himalayas'}], 'nextCursor': None}])
        result = collect(HimalayasSource(), client)
        self.assertTrue(result.success)
        self.assertEqual(result.jobs[0].url, 'https://himalayas.app/companies/acme/jobs/one')
        self.assertEqual(result.jobs[0].application_url, 'https://example.org/apply?id=42&utm_source=himalayas')
        self.assertIn('India', result.jobs[0].location)
        self.assertIsNotNone(result.jobs[0].valid_through)

    def test_himalayas_cursor_pagination_is_bounded(self):
        client = JSONClient([{'jobs': [], 'nextCursor': 'next'}, {'jobs': [], 'nextCursor': None}])
        collect(HimalayasSource(2), client)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[1][1]['params']['cursor'], 'next')

    def test_unsafe_application_link_rejects_source(self):
        row = jobicy_row(url='javascript:alert(1)')
        self.assertFalse(collect(JobicySource(), JSONClient([{'jobs': [row]}])).success)

    @patch.dict(os.environ, {'ADZUNA_APP_ID': 'test-id', 'ADZUNA_APP_KEY': 'test-key'})
    def test_adzuna_search_marks_snippet_and_keeps_redirect_tracking(self):
        client = JSONClient([{'results': [{'id': '1', 'title': 'Engineer', 'company': {'display_name': 'Acme'},
            'location': {'display_name': 'Bengaluru, India'}, 'description': 'Python snippet...',
            'redirect_url': 'https://www.adzuna.in/land/1?utm_source=partner&v=abc', 'created': '2026-11-18T00:00:00Z'}]}])
        result = collect(AdzunaSource('in', 'Python', 'Bengaluru'), client)
        self.assertTrue(result.success)
        self.assertFalse(result.jobs[0].description_complete)
        self.assertIn('utm_source=partner', result.jobs[0].application_url)
        self.assertEqual(client.calls[0][1]['params']['where'], 'Bengaluru')

    @patch.dict(os.environ, {'USAJOBS_API_KEY': 'test-key', 'USAJOBS_USER_AGENT': 'test@example.org'})
    def test_usajobs_maps_hiring_requirements_and_expiry(self):
        client = JSONClient([{'SearchResult': {'SearchResultItems': [{'MatchedObjectId': '1', 'MatchedObjectDescriptor': {
            'PositionTitle': 'Engineer', 'PositionURI': 'https://www.usajobs.gov/job/1',
            'PositionLocationDisplay': 'Washington, DC', 'OrganizationName': 'Agency',
            'QualificationSummary': 'Python skills required.', 'ApplicationCloseDate': '2026-12-30',
            'UserArea': {'Details': {'Requirements': 'Check citizenship and hiring-path requirements.'}}}}]}}])
        result = collect(USAJobsSource('Engineer'), client)
        self.assertTrue(result.success)
        self.assertIn('citizenship', result.jobs[0].description)
        self.assertEqual(client.calls[0][1]['headers']['Authorization-Key'], 'test-key')
        self.assertFalse(result.jobs[0].description_complete)


class SearchProviderTests(SimpleTestCase):
    @patch.dict(os.environ, {'SEARCH_PROVIDERS': 'tavily', 'TAVILY_API_KEY': 'test-key'})
    def test_tavily_is_basic_without_generated_answers(self):
        class Client:
            def post_json(self, url, **kwargs):
                self.args = url, kwargs
                return {'results': [{'url': 'https://jobs.lever.co/acme/one'}]}
        client = Client()
        self.assertEqual(search_urls(client, 'tavily', 'Python jobs'), ['https://jobs.lever.co/acme/one'])
        body = client.args[1]['body']
        self.assertEqual(body['search_depth'], 'basic')
        self.assertFalse(body['auto_parameters'])
        self.assertFalse(body['include_answer'])
        self.assertNotIn('test-key', str(body))

    @patch.dict(os.environ, {'SEARCH_PROVIDERS': 'tavily', 'TAVILY_API_KEY': 'test-key'})
    def test_search_results_only_discover_boards_and_urls(self):
        with patch('discovery_core.search.search_urls', return_value=['https://jobs.lever.co/acme/one', 'https://example.org/jobs/1']):
            boards, pages, errors, cursor = discover(None, {}, {'queries': ['Python jobs'], 'max_queries': 1})
        self.assertEqual(boards[0].slug, 'acme')
        self.assertEqual(pages, ['https://example.org/jobs/1'])
        self.assertEqual(cursor, 1)

    @patch.dict(os.environ, {'SEARCH_PROVIDERS': 'tavily,brave', 'TAVILY_API_KEY': 't', 'BRAVE_SEARCH_API_KEY': 'b'})
    def test_multiple_providers_share_the_call_budget(self):
        with patch('discovery_core.search.search_urls', return_value=[]) as search:
            discover(None, {}, {'queries': ['one', 'two', 'three', 'four'], 'max_queries': 2})
        self.assertEqual(search.call_count, 2)
        self.assertEqual([c.args[1] for c in search.call_args_list], ['tavily', 'brave'])

    @patch.dict(os.environ, {'SEARCH_PROVIDERS': 'tavily', 'TAVILY_API_KEY': 't'})
    def test_exhausted_allowance_never_calls_provider(self):
        with patch('discovery_core.search.search_urls') as search:
            _, _, errors, _ = discover(None, {}, {'queries': ['one'], 'reserve_search': lambda p: False})
        search.assert_not_called()
        self.assertIn('allowance', errors[0])

    @patch.dict(os.environ, {'SEARCH_PROVIDERS': 'tavily', 'TAVILY_API_KEY': 't'})
    def test_search_error_is_safe_and_seeds_still_work(self):
        with patch('discovery_core.search.search_urls', side_effect=FetchError('HTTP 429')):
            boards, _, errors, _ = discover(None, {}, {'queries': ['one'], 'seed_urls': ['https://jobs.lever.co/acme']})
        self.assertEqual(boards[0].slug, 'acme')
        self.assertIn('429', errors[0])

    @patch.dict(os.environ, {'SEARCH_PROVIDERS': 'tavily,brave', 'TAVILY_API_KEY': '', 'BRAVE_SEARCH_API_KEY': ''})
    def test_no_keys_is_a_notice_not_an_exception(self):
        self.assertEqual(configured_search_providers(), [])
        _, _, errors, _ = discover(None, {}, {})
        self.assertIn('public job APIs still work', errors[0])


class SourceIntegrationTests(TestCase):
    @override_settings(ALLOWED_HOSTS=['testserver'], DEMO_MODE=False)
    def test_full_live_collection_populates_all_five_feeds_and_dashboard(self):
        from careers.models import Preferences, Resume, Match
        from careers.services.collection import collect_inventory
        from discovery_core.fetch import Job as Posting
        from discovery_core.sources import SourceResult
        user = get_user_model().objects.create_user('full-collector')
        Preferences.objects.create(user=user, skills=['Python', 'Django', 'SQL'], titles=['Software Engineer'], locations=['India'])
        Resume.objects.create(user=user, filename='sample.txt', checksum='sample', text='Sample', profile={'core_skills': ['Python']})
        visited = []
        def fake_collect(connector, client):
            visited.append(connector.key)
            return SourceResult(connector.key, [Posting(connector.key, connector.key, connector.key,
                'Software Engineer', 'India', 'https://example.org/' + connector.key.replace(':', '-'),
                'Python Django SQL services. Experience: 0–3 years.')])
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'discovery.json').write_text(json.dumps({'titles': ['Software Engineer'],
                'locations': ['India'], 'remotive': True, 'arbeitnow': True, 'jobicy': True,
                'remoteok': True, 'himalayas': True}))
            with override_settings(BASE_DIR=Path(directory)), patch('careers.services.collection.HTTPClient'), \
                 patch('careers.services.collection.discover', return_value=([], [], [], 0)), \
                 patch('careers.services.collection.collect', side_effect=fake_collect):
                result = collect_inventory(user)
        self.assertEqual(set(visited), {'feed:remotive','feed:arbeitnow','feed:jobicy','feed:remoteok','feed:himalayas'})
        self.assertEqual(result['sources'], 5)
        self.assertEqual(Match.objects.filter(user=user, eligible=True, score__gte=30).count(), 5)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/jobs/').context['total'], 5)

    def test_metadata_accepts_provider_name_config(self):
        from careers.services.source_registry import metadata
        self.assertEqual(metadata('Jobicy', 'https://jobicy.com', name='jobicy'),
            {'attribution_name': 'Jobicy', 'attribution_url': 'https://jobicy.com', 'name': 'jobicy'})

    @override_settings(TAVILY_MONTHLY_LIMIT=2)
    def test_monthly_attempt_cap_is_shared_and_enforced(self):
        self.assertTrue(reserve_search('tavily'))
        self.assertTrue(reserve_search('tavily'))
        self.assertFalse(reserve_search('tavily'))
        self.assertEqual(BudgetBucket.objects.get(key__startswith='web:tavily:').used, 2)

    @override_settings(JOB_API_DAILY_LIMIT=1)
    def test_registered_job_api_has_a_daily_attempt_cap(self):
        self.assertTrue(reserve_job_api('adzuna'))
        self.assertFalse(reserve_job_api('adzuna'))
        self.assertTrue(reserve_job_api('usajobs'))

    @patch.dict(os.environ, {'ADZUNA_APP_ID': 'test', 'ADZUNA_APP_KEY': 'test'})
    def test_exhausted_job_api_budget_does_not_make_a_request(self):
        client = JSONClient([])
        client.reserve_job_api = lambda provider: False
        result = collect(AdzunaSource('in', 'Python'), client)
        self.assertFalse(result.success)
        self.assertEqual(client.calls, [])

    def test_ingest_retains_original_application_and_attribution(self):
        source = Source.objects.create(key='partner', kind='feed', config={'attribution_name': 'Himalayas',
                                                                        'attribution_url': 'https://himalayas.app'})
        from discovery_core.fetch import Job as Posting
        from discovery_core.sources import SourceResult
        posting = Posting('one', 'Himalayas', 'Acme', 'Engineer', 'India', 'https://himalayas.app/companies/acme/jobs/1',
                           'Python APIs', application_url='https://example.org/apply?utm_source=himalayas', description_complete=False)
        ingest(source, SourceResult(source.key, [posting]))
        job = Job.objects.get()
        self.assertEqual(job.application_url, posting.application_url)
        self.assertFalse(job.description_complete)
        self.assertEqual(job.attributions, [{'name': 'Himalayas', 'url': 'https://himalayas.app'}])

    def test_source_catalog_does_not_claim_optional_apis_are_active(self):
        rows = availability({'adzuna': {'enabled': False}, 'usajobs': {'enabled': False}})
        self.assertIn('Optional', next(row for row in rows if row['name'] == 'Adzuna')['state'])
        self.assertEqual(len(rows), 7)

    @override_settings(ALLOWED_HOSTS=['testserver'])
    def test_source_screen_explains_tavily_and_optional_keys(self):
        user = get_user_model().objects.create_user('source-viewer')
        self.client.force_login(user)
        response = self.client.get('/sources/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tavily')
        self.assertContains(response, 'Himalayas')
        self.assertContains(response, 'USAJOBS')
