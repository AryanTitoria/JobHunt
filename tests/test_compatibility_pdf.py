from copy import deepcopy
from io import BytesIO
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader
from careers.models import Preferences, Resume, Job, Analysis, Task, TailoredResume
from careers.services.compatibility import report
from careers.services.reviews import analysis_for
from careers.services.queue import enqueue, claim, execute, INTERACTIVE_KINDS
from careers.services.tailoring import tailor, _apply_composition, assemble, validate_draft
from careers.services.evidence import grounded_rephrase
from careers.services.pdf_resume import render_pdf
from careers.services.ai import AIUnavailable

STRONG = """Jane Rao
jane@example.com | https://example.com/jane
Summary
Software engineer with 4 years of professional experience.
Skills
Python, Django, SQL, Docker, JavaScript
Experience
Company: Example Systems
Title: Software Engineer
Dates: Jan 2021 - Jan 2025
- Built Python APIs with Django and SQL.
- Automated reporting and reduced manual work by 10%.
Projects
Project: Campus Portal
- Built a Django and SQL portal with Python.
Education
Degree: Bachelor of Technology in Computer Science
Institution: Example University
Dates: 2017 - 2021
"""
WEAK = """Jane Rao
Summary
Accounting graduate seeking finance opportunities.
Skills
Excel, Accounting
Education
Degree: Bachelor of Commerce
Institution: Example College
Dates: 2022 - 2025
"""
JD = """Required qualifications:
Python, Django and SQL.
At least 3 years of professional experience.
A bachelor degree in computer science.
Responsibilities:
Build Python APIs and automate reporting.
Preferred qualifications:
Docker and AWS.
"""


@override_settings(DEMO_MODE=False, ALLOWED_HOSTS=['testserver'])
class CompatibilityTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('comparison-owner')
        self.pref=Preferences.objects.create(user=self.user,field_of_study='Computer Science',
            skills=['Python','Django','SQL','AWS'],locations=['India'])
        self.strong=Resume.objects.create(user=self.user,filename='Engineering.txt',text=STRONG,checksum='strong')
        self.weak=Resume.objects.create(user=self.user,filename='Accounting.txt',text=WEAK,checksum='weak')
        self.job=Job.objects.create(title='Backend Engineer',company='Example',location='India',
            description=JD,url='https://example.org/backend',url_hash='backend',content_hash='jd')
        self.client.force_login(self.user)

    def test_different_resumes_do_not_share_global_preferences_skills(self):
        good,bad=report(self.job,self.strong),report(self.job,self.weak)
        self.assertGreater(good['score'],bad['score']+25)
        self.assertIn('Python',good['matched_skills'])
        self.assertIn('Python',bad['missing_skills'])

    def test_identical_content_has_identical_score_despite_filename(self):
        copy=Resume.objects.create(user=self.user,filename='Renamed.pdf',text=STRONG,checksum='copy')
        self.assertEqual(report(self.job,self.strong)['score'],report(self.job,copy)['score'])

    def test_comparison_does_not_depend_on_questionnaire(self):
        before=report(self.job,self.strong)
        self.pref.years_experience=60;self.pref.skills=[];self.pref.save()
        self.assertEqual(before,report(self.job,self.strong))

    def test_required_skills_have_more_weight_than_preferred_skills(self):
        self.job.description='Required qualifications:\nPython.\nPreferred qualifications:\nDocker.'
        self.strong.text='Skills\nPython'
        self.weak.text='Skills\nDocker'
        self.assertGreater(report(self.job,self.strong)['score'],report(self.job,self.weak)['score'])

    def test_evidence_depth_distinguishes_skill_lists(self):
        self.weak.text='Skills\nPython, Django, SQL, Docker, JavaScript'
        full,listed=report(self.job,self.strong),report(self.job,self.weak)
        self.assertGreater(full['score'],listed['score'])
        evidence=next(c for c in full['components'] if c['key']=='evidence')
        self.assertTrue(evidence['evidence'])

    def test_no_jd_requirements_does_not_create_artificial_high_score(self):
        self.job.title='Engineer';self.job.description='Join our friendly team.'
        self.assertIsNone(report(self.job,self.strong)['score'])

    def test_partial_description_is_labelled(self):
        self.job.description_complete=False
        self.assertTrue(report(self.job,self.strong)['partial_description'])
        self.assertEqual(report(self.job,self.strong)['confidence'],'partial')

    def test_negative_skill_statement_is_not_evidence(self):
        self.weak.text='Skills\nNot familiar with Python. Never used Django.'
        data=report(self.job,self.weak)
        self.assertNotIn('Python',data['matched_skills'])
        self.assertNotIn('Django',data['matched_skills'])

    def test_contact_alias_is_not_skill_evidence(self):
        self.job.description='Required qualifications:\nJavaScript.'
        self.weak.text='Jane Rao\njs@example.com\nEducation\nBachelor of Commerce'
        self.assertNotIn('JavaScript',report(self.job,self.weak)['matched_skills'])

    def test_dated_employment_overlap_counted_once(self):
        self.strong.text=STRONG.replace('Software engineer with 4 years of professional experience.','Experienced engineer.')
        self.assertEqual(report(self.job,self.strong)['professional_years'],4)

    def test_year_only_dates_have_conservative_lower_bound(self):
        self.strong.text=STRONG.replace('Software engineer with 4 years of professional experience.','Experienced engineer.').replace('Jan 2021 - Jan 2025','2021 - 2025')
        self.assertEqual(report(self.job,self.strong)['professional_years'],3)

    def test_internship_dates_do_not_become_professional_years(self):
        self.strong.text=STRONG.replace('Software engineer with 4 years of professional experience.','Student.').replace('Title: Software Engineer','Title: Intern')
        self.assertIsNone(report(self.job,self.strong)['professional_years'])

    def test_resume_switching_selects_actual_owner_resume(self):
        url=reverse('job-detail',args=[self.job.pk])
        good=self.client.get(url,{'resume':str(self.strong.pk)})
        bad=self.client.get(url,{'resume':str(self.weak.pk)})
        self.assertGreater(good.context['compatibility']['score'],bad.context['compatibility']['score'])
        self.assertEqual(good.context['resume'].pk,self.strong.pk)
        self.assertContains(good,'Engineering.txt')

    def test_foreign_resume_selection_returns_404(self):
        other=get_user_model().objects.create_user('outsider')
        private=Resume.objects.create(user=other,filename='private',text=STRONG,checksum='foreign')
        self.assertEqual(self.client.get(reverse('job-detail',args=[self.job.pk]),{'resume':str(private.pk)}).status_code,404)

    def test_advice_cache_invalidated_on_actual_content_change(self):
        row=analysis_for(self.user,self.job,self.strong);signature=row.input_signature
        self.strong.text=WEAK;self.strong.save()
        row=analysis_for(self.user,self.job,self.strong)
        self.assertNotEqual(signature,row.input_signature)
        self.assertEqual(row.compatibility['resume_id'],str(self.strong.pk))

    def test_legacy_ai_review_preserved_while_score_recomputed(self):
        Analysis.objects.create(user=self.user,resume=self.strong,job=self.job,job_hash=self.job.content_hash,method='ai',result={'fit_summary':'Cached grounded review'})
        row=analysis_for(self.user,self.job,self.strong)
        self.assertEqual(row.method,'ai')
        self.assertTrue(row.compatibility)


@override_settings(DEMO_MODE=False, ALLOWED_HOSTS=['testserver'])
class InteractiveWorkerTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('ai-owner')
        self.pref=Preferences.objects.create(user=self.user,field_of_study='Computer Science',ai_consent=True)
        self.resume=Resume.objects.create(user=self.user,text=STRONG,filename='Engineer.txt',checksum='s')
        self.job=Job.objects.create(title='Backend Engineer',company='Example',location='India',description=JD,url='https://example.org/ai',url_hash='ai',content_hash='ai')
        self.client.force_login(self.user)

    def test_interactive_lane_never_claims_collection(self):
        enqueue('collect',self.user)
        review=enqueue('analysis',self.user,{'job':str(self.job.pk),'resume':str(self.resume.pk)})
        self.assertEqual(claim(kinds=INTERACTIVE_KINDS).pk,review.pk)
        self.assertIsNone(claim(kinds=INTERACTIVE_KINDS))
        self.assertEqual(claim(kinds=('collect',)).kind,'collect')

    def test_default_worker_prioritizes_review(self):
        enqueue('collect',self.user)
        review=enqueue('analysis',self.user)
        self.assertEqual(claim().pk,review.pk)

    def test_repeated_review_requests_are_deduplicated(self):
        with patch('careers.services.ai.configured_providers',return_value=['gemini']):
            for _ in range(3):self.client.post(reverse('request-review',args=[self.job.pk]),{'resume':str(self.resume.pk)})
        self.assertEqual(Task.objects.filter(kind='analysis',status='queued').count(),1)

    def test_provider_failure_is_failed_task_with_visible_notice(self):
        task=enqueue('analysis',self.user,{'job':str(self.job.pk),'resume':str(self.resume.pk)})
        with patch('careers.services.ai.review',side_effect=AIUnavailable('gemini: provider quota reached')):
            self.assertFalse(execute(task))
        task.refresh_from_db()
        self.assertEqual(task.status,'failed')
        self.assertIn('quota',Analysis.objects.get(user=self.user).notice)

    def test_review_executes_with_selected_resume_not_latest(self):
        older=self.resume
        Resume.objects.create(user=self.user,text=WEAK,filename='NewAccounting.txt',checksum='new')
        task=enqueue('analysis',self.user,{'job':str(self.job.pk),'resume':str(older.pk)})
        with patch('careers.services.ai.review',return_value=({'fit_summary':'Grounded','suggestions':[],'gaps':[]},'gemini','test')) as api:
            self.assertTrue(execute(task))
        self.assertEqual(api.call_args.args[1].pk,older.pk)

    def test_polling_scope_ignores_unrelated_collection(self):
        enqueue('collect',self.user)
        data=self.client.get('/api/tasks/',{'job':str(self.job.pk),'resume':str(self.resume.pk)}).json()
        self.assertEqual(data['pending_count'],0)
        self.assertEqual(self.client.get('/api/tasks/').json()['pending_count'],1)

    def test_pending_count_not_limited_to_recent_rows(self):
        enqueue('analysis',self.user,{'job':str(self.job.pk),'resume':str(self.resume.pk)})
        for _ in range(10):Task.objects.create(user=self.user,kind='analysis',status='done')
        self.assertEqual(self.client.get('/api/tasks/').json()['pending_count'],1)

    def test_missing_provider_gives_immediate_feedback_without_hanging_queue(self):
        with patch('careers.services.ai.configured_providers',return_value=[]):
            response=self.client.post(reverse('request-review',args=[self.job.pk]),{'resume':str(self.resume.pk)})
        self.assertEqual(response.status_code,302)
        self.assertFalse(Task.objects.filter(kind='analysis').exists())
        self.assertIn('No hosted AI provider',Analysis.objects.get(user=self.user).notice)


@override_settings(DEMO_MODE=False, ALLOWED_HOSTS=['testserver'])
class GroundedPdfTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('pdf-owner')
        Preferences.objects.create(user=self.user,field_of_study='Computer Science',ai_consent=True)
        self.master=Resume.objects.create(user=self.user,text=STRONG,filename='Master.txt',checksum='pdf')
        self.job=Job.objects.create(title='Software Intern',company='Example',location='India',description='Required qualifications:\nPython and Django.',url='https://example.org/pdf',url_hash='pdf',content_hash='pdf')
        self.client.force_login(self.user)

    def test_pdf_is_valid_text_selectable_and_contains_only_candidate_content(self):
        draft=tailor(self.user,self.job,[self.master])
        blob=render_pdf(draft)
        self.assertTrue(blob.startswith(b'%PDF'))
        reader=PdfReader(BytesIO(blob))
        text=' '.join(page.extract_text() for page in reader.pages)
        self.assertIn('Jane Rao',text)
        self.assertIn('jane@example.com',text)
        self.assertIn('10%',text)
        self.assertNotIn('M1:Experience',text)
        self.assertNotIn('match_score_internal',text)
        self.assertLessEqual(len(reader.pages),2)

    def test_download_pdf_is_private(self):
        row=tailor(self.user,self.job,[self.master])
        url=reverse('tailored-detail',args=[row.pk])+'?format=pdf'
        response=self.client.get(url)
        self.assertEqual(response['Content-Type'],'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        other=get_user_model().objects.create_user('pdf-outsider')
        self.client.force_login(other)
        self.assertEqual(self.client.get(url).status_code,404)

    def test_unsupported_fact_cannot_be_exported(self):
        row=tailor(self.user,self.job,[self.master])
        row.result['resume']['experience'][0]['bullets'][0]['text']='Led a team of 500 engineers.'
        with self.assertRaises(ValueError):render_pdf(row)

    def test_unclear_qualification_does_not_claim_a_master_conflict(self):
        self.job.description=JD
        result,_,_=assemble([self.master],self.job)
        qualifications=[r for r in result['jd_analysis']['requirement_mapping'] if 'bachelor degree' in r['requirement']]
        self.assertTrue(qualifications)
        self.assertEqual(qualifications[0]['status'],'partial')
        self.assertFalse(any('conflicts across masters' in g['note'] for g in result['skill_gaps']))

    def test_preview_does_not_render_identity_as_an_extra_section(self):
        row=tailor(self.user,self.job,[self.master])
        response=self.client.get(reverse('tailored-detail',args=[row.pk]))
        self.assertContains(response,'Jane Rao')
        self.assertNotContains(response,'<h2>Identity</h2>')

    def test_controlled_rephrasing_keeps_scope(self):
        self.assertTrue(grounded_rephrase('Supported Python reporting.','Assisted with Python reporting.'))
        for text in ['Led Python reporting.','Expert in Python reporting.','Assisted with AWS architecture.']:
            self.assertFalse(grounded_rephrase(text,'Assisted with Python reporting.'))
        self.assertFalse(grounded_rephrase('Reduced latency by 10%.','Reduced errors by 10%.'))

    def test_ai_composition_applies_grounded_wording_and_rejects_invention(self):
        self.master.text=STRONG.replace('Software engineer with 4 years of professional experience.','Assisted with Python reporting.')
        result,sources,_=assemble([self.master],self.job)
        summary=result['resume']['summary']
        proposal={'rewrites':[{'source_ids':summary['source_ids'],'text':'Supported Python reporting.'}]}
        accepted,rejected=_apply_composition(result,sources,proposal)
        self.assertEqual((accepted,rejected),(1,0))
        self.assertEqual(result['resume']['summary']['text'],'Supported Python reporting.')
        validate_draft(result,sources)

    def test_ai_failure_keeps_pdf_ready_and_records_attempt_state(self):
        with patch('careers.services.tailoring.bounded_json',side_effect=AIUnavailable('provider quota reached')):
            row=tailor(self.user,self.job,[self.master],True)
        self.assertEqual(row.ai_state,'failed')
        self.assertTrue(render_pdf(row).startswith(b'%PDF'))

    def test_failed_ai_can_retry_after_cooldown(self):
        with patch('careers.services.tailoring.bounded_json',side_effect=AIUnavailable('provider quota reached')):
            row=tailor(self.user,self.job,[self.master],True)
        row.ai_last_attempt=timezone.now()-__import__('datetime').timedelta(minutes=3);row.save()
        with patch('careers.services.tailoring.bounded_json',return_value={'order':[],'rewrites':[],'_provider':'gemini','_model':'test'}) as api:
            retried=tailor(self.user,self.job,[self.master],True)
        self.assertEqual(retried.pk,row.pk)
        self.assertEqual(retried.ai_state,'succeeded')
        self.assertEqual(api.call_count,1)

    def test_review_consent_can_authorize_explicit_ai_generation(self):
        response=self.client.post(reverse('create-tailored',args=[self.job.pk]),{'masters':[str(self.master.pk)],'mode':'ai'})
        self.assertEqual(response.status_code,302)
        self.assertTrue(Task.objects.filter(kind='tailor',status='queued').exists())
