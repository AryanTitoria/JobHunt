from types import SimpleNamespace
from unittest.mock import Mock
from django.test import TestCase, SimpleTestCase, override_settings
from django.contrib.auth import get_user_model
from careers.models import Preferences, Job, Match, JobState, Resume, Task
from careers.services.opportunities import experience_details, experience_eligibility, field_internship, infer_field
from careers.services.matching import evaluate, refresh_matches
from discovery_core.discovery import Board, board_from_url, search_queries
from discovery_core.sources import ATSSource, PageSource, collect


class ExperienceTests(SimpleTestCase):
    def check(self, title, description, expected, years=0, unknown=False):
        job = SimpleNamespace(title=title, description=description)
        pref = SimpleNamespace(years_experience=years, include_unknown_experience=unknown)
        self.assertEqual(experience_eligibility(job, pref)[0], expected, (title, description))

    def test_zero_years_accepts_entry_titles(self):
        for title in ['Junior Developer', 'Graduate Trainee', 'Fresher Software Engineer', 'SDE I', 'Software Intern']:
            with self.subTest(title=title): self.check(title, 'Build software.', True)

    def test_zero_years_rejects_seniority(self):
        for title in ['Senior Developer', 'Staff Engineer', 'Engineering Manager', 'SDE II', 'Software Engineer III']:
            with self.subTest(title=title): self.check(title, 'Experience: 0-2 years.', False)

    def test_stated_required_minimum_is_a_gate(self):
        for description in ['Minimum 1 year experience.', '3+ years of professional experience required.', 'Experience: 1 to 3 years.', 'At least two years experience.']:
            with self.subTest(description=description): self.check('Software Developer', description, False)

    def test_inclusive_experience_range(self):
        for years, expected in [(0, True),(2, True),(3,False)]:
            self.check('Software Developer', 'Experience: 0-2 years.', expected, years=years)

    def test_preferred_experience_does_not_block_fresher(self):
        self.check('Graduate Software Engineer', 'Two years experience preferred.', True)

    def test_unknown_is_explicit_opt_in(self):
        self.check('Software Engineer', 'Build software.', False)
        self.check('Software Engineer', 'Build software.', True, unknown=True)

    def test_senior_title_does_not_invent_a_stated_experience_requirement(self):
        self.check('Senior Developer', 'Build software.', False, years=5)
        self.check('Senior Developer', 'Build software.', True, years=5, unknown=True)
        self.assertIsNone(experience_details(SimpleNamespace(title='Senior Developer',description='Build software.'))['minimum'])

    def test_university_education_is_not_work_experience(self):
        self.check('Software Engineer Intern', 'At least 1 year of university education, or equivalent work experience.', True)

    def test_preferred_section_does_not_become_required_experience(self):
        self.check('Software Engineer Intern', 'Minimum requirements\nProgramming experience.\nPreferred qualifications\nAt least 2 years of experience.', True)

    def test_required_section_after_preferred_is_enforced(self):
        self.check('Software Engineer Intern', 'Preferred qualifications\n1 year experience.\nMinimum requirements\n3 years professional experience.', False)

    def test_company_age_and_degree_are_not_experience(self):
        self.check('Graduate Engineer', 'Our company has 20 years experience. A four-year degree is required.', True)

    def test_cs_field_and_irrelevant_internship(self):
        self.assertEqual(infer_field('B.Tech in Computer Science'), 'Computer Science')
        self.assertTrue(field_internship(SimpleNamespace(title='Backend Intern',description='Rust, systems programming.'),'Computer Science'))
        self.assertFalse(field_internship(SimpleNamespace(title='Marketing Intern',description='Computer science students may apply.'),'Computer Science'))


@override_settings(DEMO_MODE=False, ALLOWED_HOSTS=['testserver'])
class FieldInternshipTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('student')
        self.pref=Preferences.objects.create(user=self.user, field_of_study='Computer Science',career_stage='student',
            years_experience=0, locations=['India'], titles=['Software Engineer'], skills=['Python'], minimum_score=99)
        self.job=Job.objects.create(title='Backend Intern',company='Example',location='Bengaluru, India',
            description='Rust programming internship. Students welcome.',url='https://example.org/intern',url_hash='intern',content_hash='intern')
        self.client.force_login(self.user)

    def test_no_resume_and_no_skill_overlap_still_show_internship(self):
        refresh_matches(self.user)
        response=self.client.get('/jobs/?tab=internships')
        self.assertEqual(response.context['total'],1)
        self.assertContains(response,'search answers')
        self.assertTrue(Match.objects.get(user=self.user,job=self.job).eligible)

    def test_open_marks_seen_without_resume_and_detail_renders(self):
        # Resolve through named URLs to keep route changes explicit.
        from django.urls import reverse
        response=self.client.post(reverse('open-job',args=[self.job.pk]))
        self.assertEqual(response.status_code,302)
        self.assertTrue(JobState.objects.get(user=self.user,job=self.job).seen_at)
        self.assertEqual(self.client.get(response.url).status_code,200)

    def test_internships_remain_filtered_by_location(self):
        self.job.location='Berlin, Germany'
        self.assertFalse(evaluate(self.job,None,self.pref)['eligible'])

    def test_internship_with_required_experience_is_excluded(self):
        self.job.description='Minimum 2 years of professional experience required.'
        self.assertFalse(evaluate(self.job,None,self.pref)['eligible'])

    def test_remote_internship_worldwide_is_included(self):
        self.job.location='Remote (Worldwide)'
        self.job.remote=True
        self.assertTrue(evaluate(self.job,None,self.pref)['eligible'])

    def test_remote_us_only_is_excluded(self):
        self.job.location='Remote (United States)'
        self.job.remote=True
        self.assertFalse(evaluate(self.job,None,self.pref)['eligible'])

    def test_city_only_india_remote_is_included(self):
        self.job.location='Bengaluru'
        self.job.remote=True
        self.assertTrue(evaluate(self.job,None,self.pref)['eligible'])

    def test_remote_disabled_excludes_remote_internships(self):
        self.job.location='Remote (Worldwide)'
        self.job.remote=True
        self.pref.allow_remote=False
        self.assertFalse(evaluate(self.job,None,self.pref)['eligible'])

    def test_remote_internship_filter_renders(self):
        self.job.remote=True
        self.job.save()
        refresh_matches(self.user)
        response=self.client.get('/jobs/?tab=internships&remote=1')
        self.assertEqual(response.context['total'],1)
        self.assertContains(response,'Remote internships')

    def test_quick_rejection_skips_skill_extraction(self):
        from unittest.mock import patch
        self.job.location='Berlin, Germany'
        with patch('careers.services.matching.extract_skills') as extract:
            result=evaluate(self.job,None,self.pref,eligibility_only=True)
        self.assertFalse(result['eligible'])
        extract.assert_not_called()

    def test_disabled_internships_are_excluded(self):
        self.pref.include_internships=False
        self.assertFalse(evaluate(self.job,None,self.pref)['eligible'])

    def test_profile_save_controls_experience_and_field(self):
        response=self.client.post('/profile/',{'career_stage':'student','field_of_study':'Computer Science',
            'years_experience':0,'search_scope':'field','opportunity_type':'both','work_arrangement':'any','include_unknown_work_arrangement':'on','locations_text':'India'})
        self.assertEqual(response.status_code,302)
        self.pref.refresh_from_db()
        self.assertEqual(self.pref.years_experience,0)
        self.assertTrue(Match.objects.get(user=self.user,job=self.job).eligible)

    def test_resume_upload_preserves_confirmed_professional_experience(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.pref.years_experience=0
        self.pref.save()
        text=b"Final year Computer Science student. Python Django SQL Git. Two university projects. Software Engineer with 2 years of experience in personal projects."
        response=self.client.post('/resume/', {'resume':SimpleUploadedFile('resume.txt',text)})
        self.assertEqual(response.status_code,302)
        self.pref.refresh_from_db()
        self.assertEqual(self.pref.years_experience,0)
        self.assertEqual(self.pref.career_stage,'student')

    def test_direct_internships_published_before_later_discovery_failure(self):
        import tempfile, json
        from pathlib import Path
        from unittest.mock import patch
        from careers.services.collection import collect_inventory
        from discovery_core.fetch import Job as Posting
        from discovery_core.sources import SourceResult
        from discovery_core.http import FetchError
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'india_ats_boards.json').write_text(json.dumps([{'ats':'lever','slug':'example','name':'Example'}]))
            def result(connector, client):
                return SourceResult(connector.key,[Posting('remote1','lever','Example','Software Engineer Intern','Bengaluru',
                    'https://example.org/remote-intern','Computer Science students welcome.',remote=True)])
            with override_settings(BASE_DIR=Path(directory)), patch('careers.services.collection.HTTPClient'), \
                 patch('careers.services.collection.collect',side_effect=result), \
                 patch('careers.services.collection.discover',side_effect=FetchError('temporary search failure')):
                with self.assertRaises(FetchError): collect_inventory(self.user)
        self.assertTrue(Match.objects.filter(user=self.user,eligible=True,is_field_internship=True,job__remote=True).exists())

    def test_old_policy_is_hidden_and_background_refresh_queued(self):
        Match.objects.create(user=self.user,job=self.job,eligible=True,score=100)
        response=self.client.get('/jobs/')
        self.assertEqual(response.context['total'],0)
        task=Task.objects.get(user=self.user,kind='match')
        from careers.services.queue import execute
        self.assertTrue(execute(task))
        self.assertEqual(self.client.get('/jobs/').context['total'],1)


class CareerSourcesTests(SimpleTestCase):
    def test_new_board_urls_recognized(self):
        self.assertEqual(board_from_url('https://careers.smartrecruiters.com/Freshworks').ats,'smartrecruiters')
        self.assertEqual(board_from_url('https://example.recruitee.com/o/software-intern').slug,'example')

    def test_search_includes_field_internships_independently_of_target_roles(self):
        queries=search_queries({}, {'titles':['Python Developer'],'location':'India','years_experience':0,'field_of_study':'Computer Science'})
        self.assertIn('fresher', queries[0])
        self.assertIn('Computer Science',queries[1])
        self.assertIn('internship',queries[1])
        self.assertNotIn('Python',queries[1])

    def test_lever_remote_workplace_type_is_preserved(self):
        from discovery_core.fetch import parse_lever
        job=parse_lever('example','Example',[{'id':'1','text':'Software Intern','categories':{'location':'Bengaluru'},
            'hostedUrl':'https://jobs.lever.co/example/1','descriptionPlain':'CS internship','workplaceType':'remote'}])[0]
        self.assertTrue(job.remote)

    def test_ashby_remote_flag_is_preserved(self):
        from discovery_core.fetch import parse_ashby
        job=parse_ashby('example','Example',{'jobs':[{'id':'1','title':'Software Intern','location':'India',
            'jobUrl':'https://jobs.ashbyhq.com/example/1','descriptionPlain':'CS internship','isRemote':True}]})[0]
        self.assertTrue(job.remote)

    def test_public_recruitee_jobs(self):
        client=Mock()
        client.json.return_value={'offers':[{'id':1,'title':'Software Intern','careers_url':'https://example.recruitee.com/o/one',
            'description':'Computer Science internship','location':'India'}]}
        result=collect(ATSSource(Board('recruitee','example')),client)
        self.assertTrue(result.success)
        self.assertTrue(result.authoritative)
        self.assertEqual(len(result.jobs),1)

    def test_smartrecruiters_bounded_snapshot_does_not_close_other_jobs(self):
        client=Mock()
        client.json.side_effect=[{'content':[{'id':'1','name':'Software Intern'}]},
            {'name':'Software Intern','postingUrl':'https://jobs.smartrecruiters.com/Example/1',
             'location':{'city':'Bengaluru','country':'India'},'jobAd':{'sections':{'jobDescription':{'text':'Computer science internship.'}}}}]
        result=collect(ATSSource(Board('smartrecruiters','Example')),client)
        self.assertTrue(result.success)
        self.assertFalse(result.authoritative)
        self.assertEqual(len(result.jobs),1)

    def test_career_links_are_bounded_same_host_one_hop(self):
        client=Mock()
        client.page.return_value='<a href="/careers/internships">Students</a><a href="https://other.org/jobs">External</a>'
        result=collect(PageSource('https://example.org/careers'),client)
        self.assertEqual(result.pages,['https://example.org/careers/internships'])
        self.assertEqual(collect(PageSource('https://example.org/careers',depth=1),client).pages,[])

    def test_unreadable_career_site_reports_no_extraction(self):
        client=Mock()
        client.page.return_value='<p>JavaScript required</p>'
        self.assertFalse(collect(PageSource('https://example.org/careers'),client).success)
