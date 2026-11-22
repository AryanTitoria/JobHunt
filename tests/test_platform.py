import hashlib
import io
import json
import os
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from careers.models import Preferences, Resume, Job, JobState, Analysis, Match, Source, Task, BudgetBucket, ProviderHealth, AIEvent
from careers.services.ai import AIUnavailable, reserve, review, validate_review, usage
from careers.services.collection import load_demo_inventory, ingest
from careers.services.matching import refresh_matches, evaluate
from careers.services.queue import enqueue, claim, execute
from careers.services.resumes import extract_upload, profile_from_text, redacted_text
from discovery_core.fetch import Job as Posting
from discovery_core.sources import SourceResult

TEXT = '''Alex Sample
Software Engineer with 2 years of experience.
Skills: Python, Django, SQL, PostgreSQL, Docker, Git, JavaScript
Built Python APIs using Django and PostgreSQL for an internal product catalog.
Added automated tests and used Git for code reviews and release coordination.
Bachelor of Technology, Example University, 2024.
'''


@override_settings(DEMO_MODE=True, ALLOWED_HOSTS=['testserver'])
class PlatformTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user('alice', password='Test-password-427!')
        cls.bob = get_user_model().objects.create_user('bob', password='Test-password-428!')
        for user in [cls.alice, cls.bob]:
            Preferences.objects.create(user=user, titles=['Backend Engineer', 'Software Engineer'], locations=['India'],
                skills=['Python', 'Django', 'SQL', 'PostgreSQL', 'Docker', 'Git'], years_experience=2)
            Resume.objects.create(user=user, filename='resume.txt', text=TEXT.strip(), checksum=hashlib.sha256(TEXT.strip().encode()).hexdigest(),
                                  profile=profile_from_text(TEXT))
        load_demo_inventory()
        refresh_matches(cls.alice)
        refresh_matches(cls.bob)

    def setUp(self):
        self.client.force_login(self.alice)
        self.job = Job.objects.get(company='Northstar', title='Backend Engineer')

    def test_main_authenticated_screens_render(self):
        for name in ['jobs', 'resume', 'profile', 'sources']:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_public_screens_render(self):
        client = Client()
        for path in ['/', '/login/', '/signup/', '/health/']:
            self.assertEqual(client.get(path).status_code, 200)

    def test_new_user_can_register_upload_and_discover(self):
        client = Client()
        response = client.post('/signup/', {'username': 'NewCareer', 'email': '',
            'password1': 'Fresh-start-5728!', 'password2': 'Fresh-start-5728!'})
        self.assertRedirects(response, '/profile/')
        response=client.post('/profile/', {'career_stage':'experienced','years_experience':2,
            'field_of_study':'Computer Science','search_scope':'roles','titles_text':'Software Engineer, Backend Engineer',
            'opportunity_type':'both','work_arrangement':'any','include_unknown_work_arrangement':'on',
            'allow_remote':'on','locations_text':'India'})
        self.assertRedirects(response, '/jobs/')
        user = get_user_model().objects.get(username='newcareer')
        response = client.post('/resume/', {'resume': SimpleUploadedFile('resume.txt', TEXT.encode()),
                                          'titles': 'Software Engineer, Backend Engineer', 'locations': 'India'})
        self.assertRedirects(response, '/jobs/')
        task = claim()
        self.assertTrue(execute(task))
        response = client.get('/jobs/')
        self.assertGreater(response.context['total'], 0)
        match = response.context['page'][0]
        client.post(reverse('open-job', args=[match.job.pk]))
        self.assertTrue(JobState.objects.filter(user=user, job=match.job, seen_at__isnull=False).exists())

    def test_signout_requires_post(self):
        self.assertEqual(self.client.get('/logout/').status_code, 405)
        self.assertEqual(self.client.post('/logout/').status_code, 302)

    def test_authentication_required(self):
        client = Client()
        for path in ['/jobs/', '/profile/', '/resume/', '/api/tasks/', '/account/export/']:
            self.assertEqual(client.get(path).status_code, 302)

    def test_selecting_job_marks_only_current_user_seen(self):
        response = self.client.post(reverse('open-job', args=[self.job.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(JobState.objects.get(user=self.alice, job=self.job).seen_at)
        self.assertFalse(JobState.objects.filter(user=self.bob, job=self.job).exists())

    def test_reading_detail_does_not_mutate_seen_state(self):
        response = self.client.get(reverse('job-detail', args=[self.job.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(JobState.objects.filter(user=self.alice, job=self.job).exists())

    def test_seen_filter_does_not_hide_job_for_another_user(self):
        self.client.post(reverse('open-job', args=[self.job.pk]))
        response = self.client.get('/jobs/?unseen=1')
        self.assertNotIn(self.job.pk, [m.job_id for m in response.context['page']])
        self.client.force_login(self.bob)
        response = self.client.get('/jobs/?unseen=1')
        self.assertIn(self.job.pk, [m.job_id for m in response.context['page']])

    def test_saved_job_is_private(self):
        self.client.post(reverse('toggle-state', args=[self.job.pk]), {'action': 'save'})
        self.assertEqual(self.client.get('/jobs/?tab=saved').context['total'], 1)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get('/jobs/?tab=saved').context['total'], 0)

    def test_user_cannot_see_another_users_analysis(self):
        resume = self.alice.resumes.first()
        Analysis.objects.create(user=self.alice, resume=resume, job=self.job, job_hash=self.job.content_hash,
                                result={'fit_summary': 'PRIVATE ALICE REVIEW', 'suggestions': [], 'gaps': []})
        self.client.force_login(self.bob)
        response = self.client.get(reverse('job-detail', args=[self.job.pk]))
        self.assertNotContains(response, 'PRIVATE ALICE REVIEW')

    def test_task_api_is_private(self):
        Task.objects.create(user=self.bob, kind='analysis', message='BOB PRIVATE TASK')
        self.assertNotContains(self.client.get('/api/tasks/'), 'BOB PRIVATE TASK')

    def test_export_only_contains_current_users_data(self):
        bob_resume = self.bob.resumes.first()
        bob_resume.text = 'BOB PRIVATE RESUME'
        bob_resume.save()
        response = self.client.get('/account/export/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'BOB PRIVATE RESUME')
        self.assertIn('attachment', response['Content-Disposition'])

    def test_resume_upload_extracts_reference_without_changing_search(self):
        response = self.client.post('/resume/', {'resume': SimpleUploadedFile('new.txt', (TEXT + '\nNew project').encode()),
                                               'titles': 'Backend Engineer', 'locations': 'India'})
        self.assertRedirects(response, '/jobs/')
        self.assertFalse(Task.objects.filter(user=self.alice, kind='collect', status='queued').exists())
        self.assertIn('Python', self.alice.resumes.first().profile['core_skills'])

    def test_reupload_same_resume_reuses_version(self):
        count = self.alice.resumes.count()
        response = self.client.post('/resume/', {'resume': SimpleUploadedFile('same.txt', TEXT.encode())})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.alice.resumes.count(), count)

    def test_delete_resumes_only_deletes_owner_text_and_reviews(self):
        self.client.post(reverse('open-job', args=[self.job.pk]))
        self.client.post('/account/delete-resumes/')
        self.assertFalse(self.alice.resumes.exists())
        self.assertTrue(self.bob.resumes.exists())
        self.assertTrue(JobState.objects.filter(user=self.alice, job=self.job).exists())
        self.assertFalse(Analysis.objects.filter(user=self.alice).exists())

    def test_csrf_protects_state_changes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alice)
        response = client.post(reverse('open-job', args=[self.job.pk]))
        self.assertEqual(response.status_code, 403)

    def test_private_responses_are_not_cacheable(self):
        response = self.client.get('/jobs/')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn("frame-ancestors 'none'", response['Content-Security-Policy'])

    def test_posting_text_is_escaped(self):
        self.job.description = '<script>alert("xss")</script>'
        self.job.save()
        response = self.client.get(reverse('job-detail', args=[self.job.pk]))
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert')

    def test_model_is_not_called_without_consent(self):
        with patch('careers.services.ai._request') as request:
            with self.assertRaises(AIUnavailable):
                review(self.alice, self.alice.resumes.first(), self.job, self.alice.preferences)
            request.assert_not_called()

    def test_cloud_review_cache_prevents_repeat_calls(self):
        preferences = self.alice.preferences
        preferences.ai_consent = True
        preferences.save()
        result = {'fit_summary': 'A useful fit', 'suggestions': [{'section': 'Experience', 'change': 'Prioritize this API work.',
                   'evidence': 'Built Python APIs using Django and PostgreSQL for an internal product catalog.'}], 'gaps': []}
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test'}), patch('careers.services.ai._request', return_value=result) as request:
            self.client.post(reverse('open-job', args=[self.job.pk]))
            task = claim()
            self.assertTrue(execute(task))
            self.client.post(reverse('open-job', args=[self.job.pk]))
            self.client.post(reverse('request-review', args=[self.job.pk]))
            self.assertEqual(request.call_count, 1)
            self.assertFalse(Task.objects.filter(status='queued').exists())

    def test_profile_preferences_are_validated(self):
        response = self.client.post('/profile/', {'years_experience': '61', 'career_stage': 'experienced', 'search_scope':'roles','titles_text':'Engineer','opportunity_type':'both','work_arrangement':'any'})
        self.assertContains(response, 'Enter experience from 0 to 60 years.')

    def test_expired_or_stale_jobs_do_not_appear(self):
        self.job.expires_at = timezone.now() - timedelta(days=1)
        self.job.save()
        response = self.client.get('/jobs/')
        self.assertNotIn(self.job.pk, [m.job_id for m in response.context['page']])

    def test_location_restriction_is_not_remote_worldwide(self):
        job = Job.objects.get(location='Remote (United States)')
        result = evaluate(job, self.alice.resumes.first(), self.alice.preferences)
        self.assertFalse(result['eligible'])

    def test_profile_change_refreshes_matching(self):
        response = self.client.post('/profile/', {'titles_text': 'Financial Analyst', 'locations_text': 'India',
            'search_scope':'roles','opportunity_type':'both','work_arrangement':'any','include_unknown_work_arrangement':'on', 'years_experience': '2', 'career_stage': 'experienced'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Match.objects.filter(user=self.alice, job__title='Financial Analyst', eligible=True).exists())

    @override_settings(DEMO_MODE=False)
    def test_fictional_jobs_are_excluded_in_live_mode(self):
        self.assertEqual(self.client.get('/jobs/').context['total'], 0)


class ResumeExtractionTests(TestCase):
    def test_txt_extraction(self):
        text, checksum, profile = extract_upload(SimpleUploadedFile('resume.txt', TEXT.encode()))
        self.assertEqual(text, TEXT.strip())
        self.assertIn('Django', profile['core_skills'])
        self.assertEqual(len(checksum), 64)

    def test_docx_paragraphs_and_tables(self):
        from docx import Document
        doc = Document()
        doc.add_paragraph(TEXT)
        table = doc.add_table(rows=1, cols=1)
        table.cell(0, 0).text = 'Skills: Data Analysis, Excel'
        stream = io.BytesIO()
        doc.save(stream)
        text, _, profile = extract_upload(SimpleUploadedFile('resume.docx', stream.getvalue()))
        self.assertIn('Data Analysis', text)
        self.assertIn('Excel', profile['core_skills'])

    def test_fake_pdf_is_rejected(self):
        with self.assertRaises(ValidationError):
            extract_upload(SimpleUploadedFile('resume.pdf', TEXT.encode()))

    def test_blank_scanned_pdf_is_rejected(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        stream = io.BytesIO()
        writer.write(stream)
        with self.assertRaisesMessage(ValidationError, 'Not enough text'):
            extract_upload(SimpleUploadedFile('resume.pdf', stream.getvalue()))

    def test_unsupported_type_is_rejected(self):
        with self.assertRaises(ValidationError):
            extract_upload(SimpleUploadedFile('resume.exe', TEXT.encode()))

    @override_settings(MAX_RESUME_BYTES=100)
    def test_upload_size_is_limited(self):
        with self.assertRaises(ValidationError):
            extract_upload(SimpleUploadedFile('resume.txt', TEXT.encode()))

    def test_contact_redaction(self):
        text = redacted_text('Email alex@example.com phone +91 98765 43210 https://example.com/alex')
        self.assertNotIn('alex@example.com', text)
        self.assertNotIn('98765', text)
        self.assertNotIn('https://', text)

    def test_skills_support_non_technical_backgrounds(self):
        profile = profile_from_text('Nursing and patient care. Skills: Ward Management, Communication')
        self.assertIn('Nursing', profile['core_skills'])
        self.assertIn('Ward Management', profile['core_skills'])
        self.assertIn('Registered Nurse', profile['target_titles'])

    def test_target_roles_are_inferred_from_resume(self):
        self.assertIn('Software Engineer', profile_from_text(TEXT)['target_titles'])


class AIAndQueueTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('test-user')

    @override_settings(AI_DAILY_USER_LIMIT=1, AI_DAILY_GLOBAL_LIMIT=5, AI_DAILY_TOKEN_BUDGET=1000)
    def test_user_budget_is_atomic_and_limited(self):
        reserve(self.user, 'gemini', 100)
        with self.assertRaises(AIUnavailable): reserve(self.user, 'gemini', 100)
        self.assertEqual(usage(self.user)['used'], 1)
        self.assertEqual(BudgetBucket.objects.get(key__startswith='global:').used, 1)

    @override_settings(AI_DAILY_USER_LIMIT=8, AI_DAILY_GLOBAL_LIMIT=1, AI_DAILY_TOKEN_BUDGET=1000)
    def test_global_limit_rolls_back_user_reservation(self):
        reserve(self.user, 'gemini', 100)
        other = get_user_model().objects.create_user('other-user')
        with self.assertRaises(AIUnavailable): reserve(other, 'groq', 100)
        self.assertEqual(usage(other)['used'], 0)

    def test_ungrounded_model_output_is_rejected(self):
        with self.assertRaises(AIUnavailable):
            validate_review({'fit_summary': 'fit', 'suggestions': [{'change': 'Invent a project', 'evidence': 'Not in resume'}]}, TEXT)

    def test_invented_numbers_are_removed_from_suggested_wording(self):
        result = validate_review({'fit_summary': 'fit', 'suggestions': [{'section': 'Experience', 'change': 'Make it clear',
            'evidence': 'Built Python APIs using Django and PostgreSQL for an internal product catalog.',
            'suggested_text': 'Built 1000 APIs and improved revenue by 90%.'}]}, TEXT)
        self.assertEqual(result['suggestions'][0]['suggested_text'], '')

    def test_task_deduplication_and_claim(self):
        first = enqueue('collect', self.user, key='same')
        second = enqueue('collect', self.user, key='same')
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(claim().pk, first.pk)
        self.assertIsNone(claim())

    def test_stale_task_is_recoverable(self):
        task = Task.objects.create(user=self.user, kind='collect', status='running', active_key='stale',
                                   started=timezone.now() - timedelta(hours=1))
        claim()
        task.refresh_from_db()
        self.assertEqual(task.status, 'failed')
        self.assertIsNone(task.active_key)

    @override_settings(AI_PROVIDERS=['gemini', 'groq'])
    def test_provider_fallback_requires_explicit_consent(self):
        preferences = Preferences.objects.create(user=self.user, ai_consent=True, fallback_consent=False)
        resume = Resume.objects.create(user=self.user, filename='resume.txt', text=TEXT, checksum='x', profile={})
        job = Job.objects.create(title='Engineer', company='Acme', description='Python APIs', url='https://example.org/1',
                                 url_hash='x', content_hash='x', provider='test')
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test', 'GROQ_API_KEY': 'test'}), \
             patch('careers.services.ai._request', side_effect=AIUnavailable('quota')) as request:
            with self.assertRaises(AIUnavailable): review(self.user, resume, job, preferences)
            self.assertEqual(request.call_count, 1)
        ProviderHealth.objects.all().delete()
        preferences.fallback_consent = True
        good = {'fit_summary': 'Fit', 'suggestions': [{'section': 'Experience', 'change': 'Move this higher.',
                'evidence': 'Built Python APIs using Django and PostgreSQL for an internal product catalog.'}]}
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test', 'GROQ_API_KEY': 'test'}), \
             patch('careers.services.ai._request', side_effect=[AIUnavailable('quota'), good]) as request:
            result, provider, model = review(self.user, resume, job, preferences)
            self.assertEqual(provider, 'groq')
            self.assertEqual(request.call_count, 2)

    def test_rate_limited_provider_enters_cooldown(self):
        from careers.services.ai import _request
        from types import SimpleNamespace
        response = SimpleNamespace(status_code=429, headers={'Retry-After': '3600'})
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test'}), patch('careers.services.ai.requests.post', return_value=response):
            with self.assertRaises(AIUnavailable): _request('gemini', 'test-model', 'test')
        self.assertGreater(ProviderHealth.objects.get(name='gemini').cooldown_until, timezone.now() + timedelta(minutes=55))


class IngestionTests(TestCase):
    def setUp(self):
        self.direct = Source.objects.create(key='greenhouse:acme', kind='ats')
        self.feed = Source.objects.create(key='feed:example', kind='feed')
        self.posting = Posting('ats:1', 'greenhouse', 'Acme', 'Engineer', 'India',
            'https://example.org/jobs/1', 'Build Python APIs with Django and PostgreSQL. ' * 8)

    def test_cross_source_deduplication(self):
        ingest(self.direct, SourceResult(self.direct.key, [self.posting], authoritative=True))
        copy = Posting(**self.posting.to_dict())
        copy.job_id, copy.ats = 'copy', 'feed'
        copy.url += '?utm_source=other'
        ingest(self.feed, SourceResult(self.feed.key, [copy]))
        self.assertEqual(Job.objects.count(), 1)
        self.assertEqual(Job.objects.first().sightings.count(), 2)

    def test_failure_does_not_close_jobs(self):
        ingest(self.direct, SourceResult(self.direct.key, [self.posting], authoritative=True))
        ingest(self.direct, SourceResult(self.direct.key, success=False, error='HTTP 503'))
        self.assertTrue(Job.objects.get().active)

    def test_stale_feed_cannot_revive_removed_ats_job(self):
        ingest(self.direct, SourceResult(self.direct.key, [self.posting], authoritative=True))
        copy = Posting(**self.posting.to_dict())
        copy.job_id, copy.ats = 'copy', 'feed'
        ingest(self.feed, SourceResult(self.feed.key, [copy]))
        ingest(self.direct, SourceResult(self.direct.key, [], authoritative=True))
        ingest(self.feed, SourceResult(self.feed.key, [copy]))
        self.assertFalse(Job.objects.get().active)
