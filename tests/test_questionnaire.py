import hashlib
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from careers.models import Preferences, Resume, Job, Match, Analysis, JobState, Task
from careers.services.matching import refresh_matches, search_evaluate, POLICY_VERSION
from careers.services.search_preferences import search_titles


@override_settings(DEMO_MODE=False, ALLOWED_HOSTS=['testserver'])
class QuestionnaireTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('questionnaire-user')
        self.pref=Preferences.objects.create(user=self.user,field_of_study='Computer Science',search_scope='field',
            titles=['Backend Engineer'], locations=['India'], years_experience=0, minimum_score=100)
        self.client.force_login(self.user)
        self.job=self.posting('Graduate Software Engineer','Rust, Kubernetes. Experience: 0-2 years.')

    def posting(self,title,description='Experience: 0-2 years.',location='Bengaluru, India',remote=False):
        key=hashlib.sha256((title+description+str(Job.objects.count())).encode()).hexdigest()
        return Job.objects.create(title=title,description=description,location=location,remote=remote,
            company='Example',provider='test',url='https://example.org/'+key,url_hash=key,content_hash=key)

    def answers(self,**changes):
        data={'career_stage':'student','years_experience':0,'field_of_study':'Computer Science',
              'search_scope':'field','titles_text':'','opportunity_type':'both','work_arrangement':'any',
              'include_unknown_work_arrangement':'on','allow_remote':'on','locations_text':'India'}
        data.update(changes)
        return data

    def upload(self,text=None,**extra):
        text=text or 'Accountant with 15 years of experience. Skills: Excel, Accounting. Prepared financial statements and managed audit documentation for corporate customers.'
        return self.client.post('/resume/',{'resume':SimpleUploadedFile('reference.txt',text.encode()),**extra})

    def ids(self):
        return set(self.client.get('/jobs/').context['page'].paginator.object_list.values_list('job_id',flat=True))

    def test_jobs_appear_without_resume_or_required_skill_overlap(self):
        refresh_matches(self.user)
        self.assertIn(self.job.pk,self.ids())
        match=Match.objects.get(user=self.user,job=self.job)
        self.assertIsNone(match.resume_id)
        self.assertEqual(match.matched_skills,[])

    def test_resume_change_leaves_results_and_answers_unchanged(self):
        refresh_matches(self.user)
        before=self.ids()
        self.upload(titles='Accountant',locations='United States')
        self.pref.refresh_from_db()
        self.assertEqual(self.pref.field_of_study,'Computer Science')
        self.assertEqual(self.pref.years_experience,0)
        self.assertEqual(self.pref.locations,['India'])
        self.assertEqual(self.pref.titles,['Backend Engineer'])
        self.assertEqual(self.ids(),before)
        self.upload('Senior Marketing Manager with 20 years of experience. Skills: Digital Marketing, SEO. Ran advertising campaigns and supported customer acquisition.')
        self.assertEqual(self.ids(),before)
        self.assertFalse(Task.objects.filter(kind='collect').exists())

    def test_resume_does_not_qualify_user_for_senior_job(self):
        senior=self.posting('Senior Software Engineer','Minimum 5 years of professional experience required.')
        self.upload()
        refresh_matches(self.user)
        self.assertNotIn(senior.pk,self.ids())

    def test_all_field_roles_are_shown_without_resume_keywords(self):
        jobs=[self.posting(t) for t in ['Frontend Developer','Data Analyst','QA Engineer']]
        refresh_matches(self.user)
        self.assertTrue({j.pk for j in jobs}.issubset(self.ids()))

    def test_unrelated_field_is_excluded_even_if_resume_mentions_it(self):
        unrelated=self.posting('Financial Analyst','Accounting, Excel. Experience: 0-2 years.')
        self.upload()
        refresh_matches(self.user)
        self.assertNotIn(unrelated.pk,self.ids())

    def test_targeted_roles_narrow_field_results(self):
        backend=self.posting('Junior Backend Developer')
        frontend=self.posting('Frontend Engineer')
        self.pref.search_scope='roles';self.pref.save()
        refresh_matches(self.user)
        self.assertIn(backend.pk,self.ids())
        self.assertNotIn(frontend.pk,self.ids())

    def test_jobs_only_excludes_internships(self):
        intern=self.posting('Software Intern')
        self.pref.opportunity_type='jobs';self.pref.save()
        refresh_matches(self.user)
        self.assertIn(self.job.pk,self.ids())
        self.assertNotIn(intern.pk,self.ids())

    def test_internships_only_excludes_jobs(self):
        intern=self.posting('Software Intern')
        self.pref.opportunity_type='internships';self.pref.save()
        refresh_matches(self.user)
        self.assertIn(intern.pk,self.ids())
        self.assertNotIn(self.job.pk,self.ids())

    def test_remote_only_checks_geography_and_never_assumes_unknown_remote(self):
        world=self.posting('Software Intern','Computer science internship.', 'Remote (Worldwide)',True)
        us=self.posting('Software Intern','Computer science internship.', 'Remote (United States)',True)
        self.pref.work_arrangement='remote';self.pref.save()
        refresh_matches(self.user)
        self.assertIn(world.pk,self.ids())
        self.assertNotIn(us.pk,self.ids())
        self.assertNotIn(self.job.pk,self.ids())

    def test_hybrid_and_onsite_are_distinct(self):
        hybrid=self.posting('Software Engineer','Experience: 0-2 years.','Bengaluru, India (Hybrid)')
        onsite=self.posting('Software Engineer','Experience: 0-2 years.','Bengaluru, India (On-site)')
        self.pref.work_arrangement='hybrid';self.pref.include_unknown_work_arrangement=False;self.pref.save()
        refresh_matches(self.user)
        self.assertIn(hybrid.pk,self.ids())
        self.assertNotIn(onsite.pk,self.ids())
        self.assertNotIn(self.job.pk,self.ids())

    def test_reference_comparison_runs_after_selection(self):
        self.upload('Software student. Skills: Python, Git. Built a university project with Python and Git, documented the code and collaborated with classmates on testing.')
        refresh_matches(self.user)
        self.assertFalse(Analysis.objects.filter(user=self.user).exists())
        response=self.client.post(reverse('open-job',args=[self.job.pk]))
        self.assertEqual(response.status_code,302)
        analysis=Analysis.objects.get(user=self.user,job=self.job)
        self.assertIn('Rust', [gap['skill'] for gap in analysis.result['gaps']])
        self.assertTrue(JobState.objects.get(user=self.user,job=self.job).seen_at)

    def test_open_without_reference_shows_upload_then_returns_to_selected_job(self):
        response=self.client.post(reverse('open-job',args=[self.job.pk]))
        self.assertEqual(self.client.get(response.url).status_code,200)
        self.assertFalse(Analysis.objects.filter(user=self.user).exists())
        target=reverse('job-detail',args=[self.job.pk])
        response=self.upload(return_to=target)
        self.assertEqual(response.url,target)
        self.client.get(target)
        self.assertTrue(Analysis.objects.filter(user=self.user,job=self.job).exists())

    def test_upload_does_not_allow_external_return_redirect(self):
        response=self.upload(return_to='https://evil.example.org/')
        self.assertEqual(response.url,'/jobs/')

    def test_deleting_reference_preserves_questionnaire_results(self):
        self.upload();refresh_matches(self.user)
        before=self.ids()
        self.client.post('/account/delete-resumes/')
        self.assertEqual(self.ids(),before)
        self.assertFalse(Resume.objects.filter(user=self.user).exists())

    def test_result_pagination_exposes_every_eligible_collected_posting(self):
        for i in range(26): self.posting('Graduate Software Engineer - Team '+str(i))
        refresh_matches(self.user)
        found=set()
        for page in range(1,4):
            response=self.client.get('/jobs/',{'page':page})
            self.assertEqual(response.context['total'],27)
            found.update(match.job_id for match in response.context['page'])
        self.assertEqual(len(found),27)

    def test_resume_skill_extraction_is_never_called_by_discovery_matching(self):
        self.upload()
        with patch('careers.services.matching.extract_skills',side_effect=AssertionError('resume scoring during discovery')):
            refresh_matches(self.user)
        self.assertIn(self.job.pk,self.ids())

    def test_questionnaire_validation_requires_search_direction(self):
        response=self.client.post('/profile/',self.answers(field_of_study=''))
        self.assertContains(response,'Enter the field you want to search.')
        response=self.client.post('/profile/',self.answers(search_scope='roles',titles_text=''))
        self.assertContains(response,'Enter at least one target role.')

    def test_questionnaire_saves_choices_and_queues_discovery(self):
        response=self.client.post('/profile/',self.answers(work_arrangement='remote',opportunity_type='internships'))
        self.assertEqual(response.url,'/jobs/')
        self.pref.refresh_from_db()
        self.assertTrue(self.pref.allow_remote)
        self.assertEqual(self.pref.work_arrangement,'remote')
        self.assertEqual(self.pref.opportunity_type,'internships')
        self.assertTrue(Task.objects.filter(user=self.user,kind='collect').exists())

    def test_field_search_terms_ignore_stale_resume_inferred_roles(self):
        self.pref.titles=['Accountant']
        self.assertIn('software engineer',search_titles(self.pref))
        self.assertNotIn('Accountant',search_titles(self.pref))

    def test_cards_have_no_resume_score_and_form_has_no_resume_score_threshold(self):
        refresh_matches(self.user)
        response=self.client.get('/jobs/')
        self.assertNotContains(response,'skills match')
        response=self.client.get('/profile/')
        self.assertNotContains(response,'name="minimum_score"')
        self.assertNotContains(response,'name="skills_text"')
        self.assertContains(response,'Build a search that understands you.')
