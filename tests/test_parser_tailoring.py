from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from careers.models import Resume, Job, Preferences, TailoredResume, ParseCache
from careers.services.opportunities import experience_details
from careers.services.job_parser import parse_job, remote_details
from careers.services.structured import structure_resume
from careers.services.resumes import extract_skills
from careers.services.tailoring import assemble, validate_draft, tailor
from careers.services.matching import search_evaluate
from careers.services.interpretation import interpret

TEXT = """Summary
Assisted the team with Python reporting.
Skills
Python, JS, ReactJS
Experience
Company: Acme
Title: Intern
Dates: Jan 2023 - June 2023
- Assisted with Python scripts and reduced manual work by 10%.
Projects
Project: Campus Portal
- Built a ReactJS portal with JS and Python.
Education
Degree: Bachelor of Technology in Computer Science
Institution: Example University
Dates: 2024 - 2027
Certifications
Certification: Python Basics
"""


class ParserAccuracyTests(SimpleTestCase):
    def exp(self, text, title='Software Engineer'):
        return experience_details(SimpleNamespace(title=title, description=text))

    def test_preferred_not_required(self):
        result = self.exp('Required qualifications:\n1-2 years experience.\nPreferred qualifications:\n5 years professional experience.')
        self.assertEqual(result['minimum'], 1)
        self.assertTrue(result['categories']['preferred'])

    def test_education_internship_and_projects_are_separate(self):
        result = self.exp('1 year of university education or equivalent experience.\n1 year internship experience.\n2 years experience through personal projects.', 'Software Intern')
        self.assertEqual(result['minimum'], 0)
        for key in ['education', 'internships', 'projects']:
            self.assertTrue(result['categories'][key])

    def test_non_internship_professional_requirement(self):
        self.assertEqual(self.exp('2 years of non-internship professional experience required.')['minimum'], 2)

    def test_months_and_fractional_years(self):
        self.assertEqual(self.exp('Minimum 6 months of professional experience required.')['minimum'], .5)
        self.assertEqual(self.exp('1.5 years experience required.')['minimum'], 1.5)

    def test_mixed_degree_duration_does_not_hide_real_experience_requirement(self):
        result = self.exp('A 4-year bachelor degree and 2 years professional experience required.')
        self.assertEqual(result['minimum'], 2)
        self.assertTrue(result['categories']['education'])

    def test_conflicting_ranges_and_unstated_years_are_unknown(self):
        result = self.exp('Experience: 0-2 years.\n5 years professional experience required.')
        self.assertTrue(result['unknown'])
        self.assertTrue(result['conflict'])
        self.assertIsNone(self.exp('Build useful software.')['minimum'])

    def test_country_restriction_overrides_worldwide_label(self):
        result = remote_details('Intern', 'Remote (Worldwide)', 'Remote candidates must reside in the United States.', True)
        self.assertFalse(result['worldwide'])
        self.assertIn('united states', result['countries'])

    def test_home_work_hybrid_and_unknown_country(self):
        self.assertEqual(remote_details('Developer', 'India', 'This role is fully remote.')['mode'], 'remote')
        self.assertEqual(remote_details('Developer', 'Hybrid - India', '', True)['mode'], 'hybrid')
        self.assertTrue(remote_details('Developer', 'Remote', '', True)['note'])

    def test_true_synonyms_not_related_skills(self):
        skills = extract_skills('Skills: JS, ReactJS, TypeScript')
        self.assertIn('JavaScript', skills)
        self.assertIn('React', skills)
        self.assertNotIn('Go', extract_skills('I go to university for the rest of the year.'))
        self.assertNotIn('AWS', extract_skills('Node.js developer'))

    def test_structured_sources_are_verbatim_and_stable(self):
        parsed = structure_resume(TEXT)
        for key in ['Education', 'Projects', 'Experience']:
            self.assertTrue(parsed['sections'][key])
        for source in parsed['sources'].values():
            self.assertIn(source['text'], TEXT)
        self.assertEqual(parsed['sources'], structure_resume(TEXT)['sources'])
        self.assertTrue(structure_resume('Unstructured paragraphs without headings.')['warnings'])

    def test_jd_required_preferred_and_qualifications(self):
        result = parse_job('Developer', 'India', 'Required qualifications:\nPython and a bachelor degree in computer science.\nPreferred qualifications:\nReactJS experience.')
        self.assertIn('Python', result['required_skills'])
        self.assertIn('React', result['preferred_skills'])
        self.assertTrue(result['qualifications'])


@override_settings(DEMO_MODE=False, ALLOWED_HOSTS=['testserver'])
class TailoringTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('master-owner')
        self.other = get_user_model().objects.create_user('other-owner')
        Preferences.objects.create(user=self.user, field_of_study='Computer Science', education_major='Computer Science', degree_name='B.Tech', locations=['India'])
        self.master = Resume.objects.create(user=self.user, text=TEXT, filename='M1.txt', checksum='m1')
        self.job = Job.objects.create(title='Software Intern', company='Example', location='India', description='Required qualifications:\nPython, JavaScript and AWS.\nPreferred qualifications:\nReact.', url='https://example.org/one', url_hash='one', content_hash='one')
        self.client.force_login(self.user)

    def second(self, text, document_date=None):
        return Resume.objects.create(user=self.user, text=text, filename='M2.txt', checksum='m2', document_date=document_date)

    def test_candidate_facts_cited_and_missing_aws_not_added(self):
        result, sources, _ = assemble([self.master], self.job)
        validate_draft(result, sources)
        self.assertTrue(result['resume']['experience'])
        self.assertIn('AWS', [gap['requirement'] for gap in result['skill_gaps']])
        self.assertNotIn('AWS', [skill['name'] for skill in result['resume']['skills']])
        self.assertTrue(all(change['original'] == change['new'] for change in result['changes_log']))
        self.assertFalse(any(bullet['text'].startswith(('Company:', 'Title:', 'Dates:')) for item in result['resume']['experience'] for bullet in item['bullets']))
        self.assertTrue(result['resume']['education'])

    def test_upgrades_numbers_and_certifications_rejected(self):
        result, sources, _ = assemble([self.master], self.job)
        for invented in ['Led 50 engineers.', 'Improved revenue by 90%.', 'AWS Certified Architect']:
            bad = deepcopy(result)
            bad['resume']['experience'][0]['bullets'][0]['text'] = invented
            with self.assertRaises(ValueError):
                validate_draft(bad, sources)

    def test_missing_and_foreign_citations_rejected(self):
        result, sources, _ = assemble([self.master], self.job)
        bad = deepcopy(result)
        bad['resume']['skills'][0]['source_ids'] = ['M99:invented']
        with self.assertRaises(ValueError):
            validate_draft(bad, sources)
        del bad['resume']['skills'][0]['source_ids']
        with self.assertRaises(ValueError):
            validate_draft(bad, sources)

    def test_undated_conflicting_metrics_omitted(self):
        result, _, _ = assemble([self.master, self.second(TEXT.replace('10%', '30%'))], self.job)
        self.assertTrue(result['conflicts'])
        self.assertFalse(result['resume']['experience'])

    def test_only_unambiguous_document_date_resolves_conflict(self):
        self.master.document_date = date(2025, 1, 1)
        self.master.save()
        other = self.second(TEXT.replace('10%', '30%'), date(2026, 1, 1))
        result, _, _ = assemble([self.master, other], self.job)
        bullets = str(result['resume']['experience'])
        self.assertIn('30%', bullets)
        self.assertNotIn('10%', bullets)

    def test_conflicting_title_same_employer_and_dates_omitted(self):
        result, _, _ = assemble([self.master, self.second(TEXT.replace('Title: Intern', 'Title: Team Lead'))], self.job)
        self.assertTrue(result['conflicts'])
        self.assertFalse(result['resume']['experience'])

    def test_different_projects_never_merge(self):
        result, _, _ = assemble([self.master, self.second(TEXT.replace('Campus Portal', 'Library Tool'))], self.job)
        self.assertEqual(len(result['resume']['projects']), 2)

    def test_ai_cache_and_untrusted_ids(self):
        self.user.preferences.parser_ai_consent = True
        self.user.preferences.save()
        with patch('careers.services.tailoring.bounded_json', return_value={'order': ['M99:invented'], 'resume': 'Led NASA'}) as api:
            first = tailor(self.user, self.job, [self.master], True)
            second = tailor(self.user, self.job, [self.master], True)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(api.call_count, 1)
        self.assertTrue(first.notice)
        self.assertNotIn('NASA', str(first.result))

    def test_foreign_resume_rejected_and_download_private(self):
        foreign = Resume.objects.create(user=self.other, text=TEXT, filename='private.txt', checksum='foreign')
        with self.assertRaises(ValueError):
            tailor(self.user, self.job, [foreign])
        row = tailor(self.user, self.job, [self.master])
        path = reverse('tailored-detail', args=[row.pk])
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertIn('jd_analysis', self.client.get(path+'?format=json').json())
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_deleting_resume_also_deletes_draft_sources_and_caches(self):
        tailor(self.user, self.job, [self.master])
        interpret(self.user, self.job)
        self.client.post('/account/delete-resumes/')
        self.assertFalse(TailoredResume.objects.filter(user=self.user).exists())
        self.assertFalse(ParseCache.objects.filter(user=self.user).exists())

    def test_interpretation_cache_rejects_invented_evidence(self):
        self.user.preferences.parser_ai_consent = True
        self.user.preferences.save()
        with patch('careers.services.interpretation.bounded_json', return_value={'experience_evidence': '5 invented years', 'work_evidence': ''}) as api:
            first = interpret(self.user, self.job, True)
            second = interpret(self.user, self.job, True)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(api.call_count, 1)
        self.assertIn('unsupported', first.result['notice'])

    def test_combined_education_and_roles_is_union(self):
        pref = self.user.preferences
        pref.search_scope = 'combined'
        pref.titles = ['Graphic Designer']
        self.assertTrue(search_evaluate(self.job, pref)['eligible'])
        design = SimpleNamespace(title='Junior Graphic Designer', location='India', description='Experience: 0-2 years.', remote=False)
        self.assertTrue(search_evaluate(design, pref)['eligible'])

    def test_education_only_and_role_only_are_independent(self):
        pref = self.user.preferences
        pref.search_scope = 'education'
        pref.titles = []
        self.assertTrue(search_evaluate(self.job, pref)['eligible'])
        pref.search_scope = 'roles'
        pref.titles = ['Graphic Designer']
        self.assertFalse(search_evaluate(self.job, pref)['eligible'])

    def test_brand_and_questionnaire_depth(self):
        self.assertEqual(self.client.get('/health/').json()['application'], 'JobSearch')
        response = self.client.get('/profile/')
        self.assertContains(response, 'name="education_major"')
        self.assertContains(response, 'name="preferred_categories"')
        self.assertContains(response, 'Combined search includes either path.')

    def test_internship_evidence_never_becomes_professional_experience(self):
        self.job.description = 'Required qualifications:\n2 years professional Python experience.'
        result, _, _ = assemble([self.master], self.job)
        python = next(row for row in result['jd_analysis']['requirement_mapping'] if row['requirement'] == 'Python')
        self.assertEqual(python['status'], 'partial')
        self.assertNotIn('2 years', str(result['resume']))

    def test_platform_exposure_not_upgraded_to_architecture_experience(self):
        self.master.text = TEXT.replace('Python, JS, ReactJS', 'Python, JS, ReactJS, AWS S3')
        self.job.description = 'Required qualifications:\nAWS architecture experience required.'
        result, _, _ = assemble([self.master], self.job)
        aws = next(row for row in result['jd_analysis']['requirement_mapping'] if row['requirement'] == 'AWS')
        self.assertEqual(aws['status'], 'partial')
        self.assertNotIn('architecture', str(result['resume']))

    def test_ambiguous_or_equal_master_dates_do_not_settle_conflicts(self):
        self.master.document_date = date(2026, 1, 1)
        self.master.save()
        other = self.second(TEXT.replace('10%', '30%'), date(2026, 1, 1))
        result, _, _ = assemble([self.master, other], self.job)
        self.assertFalse(result['resume']['experience'])

    def test_job_text_changes_invalidate_cache_even_with_same_content_hash(self):
        first = tailor(self.user, self.job, [self.master])
        self.job.description += '\nSQL required.'
        second = tailor(self.user, self.job, [self.master])
        self.assertNotEqual(first.pk, second.pk)

    def test_master_text_changes_invalidate_cache(self):
        first = tailor(self.user, self.job, [self.master])
        self.master.text = TEXT.replace('10%', '12%')
        second = tailor(self.user, self.job, [self.master])
        self.assertNotEqual(first.pk, second.pk)

    def test_six_master_selection_rejected(self):
        masters = [self.master]
        for index in range(5):
            masters.append(Resume.objects.create(user=self.user, filename=f'{index}.txt', checksum=f'extra{index}', text=TEXT))
        response = self.client.post(reverse('create-tailored', args=[self.job.pk]), {'masters': [str(master.pk) for master in masters]})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(TailoredResume.objects.exists())

    def test_excluded_titles_apply_to_education_results(self):
        pref = self.user.preferences
        pref.search_scope = 'education'
        pref.excluded_titles = ['Software Intern']
        self.assertFalse(search_evaluate(self.job, pref)['eligible'])

    def test_remote_country_restriction_applies_to_worldwide_label(self):
        pref = self.user.preferences
        self.job.location = 'Remote (Worldwide)'
        self.job.remote = True
        self.job.description = 'Fully remote. Candidates must reside in the United States. CS internship.'
        self.assertFalse(search_evaluate(self.job, pref)['eligible'])

    def test_new_feature_posts_enforce_csrf(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for name in ['create-tailored', 'interpret-job']:
            self.assertEqual(client.post(reverse(name, args=[self.job.pk])).status_code, 403)

    def test_explicit_non_dictionary_skills_keep_their_exact_evidence(self):
        self.master.text = TEXT.replace('Python, JS, ReactJS', 'Python, JS, ReactJS, Ansys')
        self.job.description = 'Skills: Ansys'
        result, sources, _ = assemble([self.master], self.job)
        self.assertIn('Ansys', [skill['name'] for skill in result['resume']['skills']])
        validate_draft(result, sources)
