import hashlib
import json
import time
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction, IntegrityError, OperationalError
from django.db.models import Q, Exists, OuterRef, F
from django.http import HttpResponse, JsonResponse, Http404
from urllib.parse import urlencode
from uuid import UUID
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import RegisterForm, ResumeForm, PreferencesForm, TailoringForm, split_values
from .models import Preferences, Resume, Job, Match, JobState, Analysis, Task, Source, BudgetBucket, TailoredResume, ParseCache
from .services import ai
from .services.matching import current_resume, refresh_matches, basic_guidance, active_jobs, evaluate, search_ready
from .services.resumes import extract_upload
from .services.queue import enqueue
from .services.opportunities import experience_details, field_internship
from .services.matching import POLICY_VERSION


def limited(request, scope, limit, seconds=900):
    value = str(request.user.pk) if request.user.is_authenticated else request.META.get('REMOTE_ADDR', '')
    digest = hashlib.sha256((settings.SECRET_KEY + value).encode()).hexdigest()[:24]
    key = f'rate:{scope}:{digest}:{int(time.time()) // seconds}'
    bucket, _ = BudgetBucket.objects.get_or_create(key=key)
    return not BudgetBucket.objects.filter(pk=bucket.pk, used__lt=limit).update(used=F('used') + 1)


class PlatformLoginView(LoginView):
    template_name = 'registration/login.html'
    def post(self, request, *args, **kwargs):
        if limited(request, 'login', 30):
            return HttpResponse('Too many login attempts. Try again in 15 minutes.', status=429)
        return super().post(request, *args, **kwargs)


def home(request):
    if request.user.is_authenticated:
        return redirect('jobs')
    return render(request, 'careers/home.html')


def register(request):
    if request.user.is_authenticated: return redirect('jobs')
    if request.method == 'POST' and limited(request, 'register', 10):
        return HttpResponse('Please wait before creating another account.', status=429)
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        # Password hashing does not need to hold SQLite's single writer slot.
        user = form.save(commit=False)
        try:
            with transaction.atomic():
                user.save()
                Preferences.objects.create(user=user)
        except IntegrityError:
            form.add_error('username', 'This username was just taken. Choose another username or sign in.')
        except OperationalError as error:
            if 'locked' not in str(error).lower():
                raise
            form.add_error(None, 'The database is busy with another update. Please wait a few seconds, then submit again.')
        else:
            login(request, user)
            return redirect('profile')
    return render(request, 'registration/register.html', {'form': form})


@login_required
def resume_view(request):
    preferences, _ = Preferences.objects.get_or_create(user=request.user)
    form = ResumeForm(request.POST or None, request.FILES or None)
    if request.method == 'POST':
        if limited(request, 'upload', 12): return HttpResponse('Upload limit reached. Please try later.', status=429)
        if form.is_valid():
            try:
                text, checksum, profile = extract_upload(form.cleaned_data['resume'])
            except ValidationError as error:
                form.add_error('resume', error)
            else:
                filename = form.cleaned_data['resume'].name.replace('\\', '/').split('/')[-1][:180]
                # One active version keeps profile/seen history while old resume text is removable.
                resume, _ = Resume.objects.get_or_create(user=request.user, checksum=checksum,
                    defaults={'filename': filename, 'text': text, 'profile': profile, 'document_date':form.cleaned_data.get('document_date')})
                if form.cleaned_data.get('document_date') and form.cleaned_data['document_date'] != resume.document_date:
                    TailoredResume.objects.filter(user=request.user).delete()
                    resume.document_date = form.cleaned_data['document_date']
                resume.created = timezone.now()
                resume.profile=profile
                resume.save(update_fields=['created','document_date','profile'])
                # Resume extraction is reference data for advice only. It must
                # never change the user's questionnaire or search results.
                preferences.skills = profile['core_skills']
                preferences.save(update_fields=['skills'])
                messages.success(request, 'Resume saved for job-specific advice. Your search answers are unchanged.')
                return_to = request.POST.get('return_to', '')
                if return_to and url_has_allowed_host_and_scheme(return_to, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                    return redirect(return_to)
                if not search_ready(preferences):
                    return redirect('profile')
                return redirect('jobs')
    return render(request, 'careers/resume.html', {'form': form, 'resume': current_resume(request.user), 'masters':request.user.resumes.all(), 'preferences': preferences, 'return_to': request.POST.get('return_to') or request.GET.get('return_to', '')})


@login_required
def profile_view(request):
    preferences, _ = Preferences.objects.get_or_create(user=request.user)
    form = PreferencesForm(request.POST or None, instance=preferences)
    if request.method == 'POST' and form.is_valid():
        form.save()
        refresh_matches(request.user)
        enqueue('collect', request.user, key=f'collect:{request.user.pk}')
        messages.success(request, 'Search answers saved. Available results have been refreshed and discovery is queued.')
        return redirect('jobs')
    return render(request, 'careers/profile.html', {'form': form, 'resume': current_resume(request.user),
                                                   'usage': ai.usage(request.user)})


@login_required
def jobs(request):
    resume = current_resume(request.user)
    preferences, _ = Preferences.objects.get_or_create(user=request.user)
    if search_ready(preferences) and preferences.matching_policy_version != POLICY_VERSION:
        enqueue('match', request.user, key=f'match:{request.user.pk}')
    states = JobState.objects.filter(user=request.user, job=OuterRef('job_id'))
    qs = Match.objects.filter(user=request.user, eligible=True, policy_version=POLICY_VERSION,
        job__in=active_jobs()).select_related('job').prefetch_related('job__sightings__source')
    if not settings.DEMO_MODE:
        qs = qs.filter(job__is_demo=False)
    qs = qs.annotate(is_seen=Exists(states.filter(seen_at__isnull=False)),
                     is_saved=Exists(states.filter(saved=True)), is_applied=Exists(states.filter(applied=True)))
    query = request.GET.get('q', '').strip()[:100]
    if query: qs = qs.filter(Q(job__title__icontains=query) | Q(job__company__icontains=query) | Q(job__description__icontains=query))
    tab = request.GET.get('tab', 'matches')
    if tab == 'saved': qs = qs.filter(is_saved=True)
    if tab == 'seen': qs = qs.filter(is_seen=True)
    if tab == 'internships': qs = qs.filter(is_field_internship=True)
    if tab == 'entry': qs = qs.filter(is_field_internship=False)
    if request.GET.get('unseen') == '1': qs = qs.filter(is_seen=False)
    if request.GET.get('remote') == '1': qs = qs.filter(Q(job__remote=True) | Q(job__location__icontains='remote'))
    if request.GET.get('sort') == 'recent': qs = qs.order_by('-job__posted_at', '-score')
    paginator = Paginator(qs, 12)
    page = paginator.get_page(request.GET.get('page'))
    for item in page.object_list:
        item.experience = experience_details(item.job)
    parameters = request.GET.copy()
    parameters.pop('page', None)
    inventory = active_jobs()
    if not settings.DEMO_MODE:
        inventory = inventory.filter(is_demo=False)
    latest_collection = Task.objects.filter(user=request.user, kind='collect').order_by('-created').first()
    context = {'page': page, 'resume': resume, 'preferences': preferences, 'query': query, 'tab': tab,
               'total': qs.count(), 'saved_count': JobState.objects.filter(user=request.user, saved=True).count(),
               'seen_count': JobState.objects.filter(user=request.user, seen_at__isnull=False).count(),
               'source_count': Source.objects.exclude(kind='search').count(), 'query_string': parameters.urlencode(),
               'inventory_count': inventory.count(), 'latest_collection': latest_collection, 'search_ready': search_ready(preferences),
               'tasks': Task.objects.filter(user=request.user).order_by('-created')[:3],
               'pending_tasks': Task.objects.filter(user=request.user, status__in=['queued', 'running']).exists()}
    return render(request, 'careers/jobs.html', context)


def _job_and_resume(user, job_id, resume_id=None):
    job = get_object_or_404(Job.objects.prefetch_related('sightings__source'), pk=job_id)
    if resume_id:
        try: parsed_id=UUID(str(resume_id))
        except ValueError: raise Http404('Resume not found')
        resume=get_object_or_404(Resume,user=user,pk=parsed_id)
    else:resume = current_resume(user)
    return job, resume


def _analysis(user, job, resume):
    from .services.reviews import analysis_for
    return analysis_for(user,job,resume)


def _detail_response(job,resume,explicit=False):
    url=reverse('job-detail',kwargs={'job_id':job.pk})
    if explicit and resume:url+='?'+urlencode({'resume':str(resume.pk)})
    return redirect(url)


@login_required
@require_POST
def open_job(request, job_id):
    job, resume = _job_and_resume(request.user, job_id, request.POST.get('resume') or request.GET.get('resume'))
    preferences, _ = Preferences.objects.get_or_create(user=request.user)
    state, _ = JobState.objects.get_or_create(user=request.user, job=job)
    if state.seen_at is None:
        state.seen_at = timezone.now()
        state.save(update_fields=['seen_at'])
    analysis = _analysis(request.user, job, resume) if resume else None
    if analysis and preferences.ai_consent and ai.configured_providers() and analysis.method != 'ai' and not analysis.notice:
        enqueue('analysis', request.user, {'job': str(job.pk), 'resume': str(resume.pk)},
                key=f'analysis:{request.user.pk}:{resume.pk}:{job.pk}:{analysis.input_signature[:12]}')
    return _detail_response(job,resume,bool(request.POST.get('resume')))


@login_required
def job_detail(request, job_id):
    job, resume = _job_and_resume(request.user, job_id, request.POST.get('resume') or request.GET.get('resume'))
    preferences, _ = Preferences.objects.get_or_create(user=request.user)
    analysis = _analysis(request.user, job, resume) if resume else None
    state = JobState.objects.filter(user=request.user, job=job).first()
    preferences = request.user.preferences
    from .services.interpretation import selected_interpretation
    parsed=selected_interpretation(request.user,job)
    relevant=Task.objects.filter(user=request.user,kind__in=['analysis','tailor','interpret'],status__in=['queued','running'],payload__job=str(job.pk))
    relevant=relevant.filter(~Q(kind='analysis')|Q(payload__resume=str(resume.pk))) if resume else relevant.exclude(kind='analysis')
    pending=relevant.exists()
    review_task=Task.objects.filter(user=request.user,kind='analysis',payload__job=str(job.pk),payload__resume=str(resume.pk) if resume else '').order_by('-created').first()
    analysis_pending=bool(review_task and review_task.status in ['queued','running'])
    return render(request, 'careers/detail.html', {'job': job, 'resume': resume, 'analysis': analysis,
        'compatibility':analysis.compatibility if analysis else None, 'resume_options':request.user.resumes.all(),
        'review_task':review_task,'analysis_pending':analysis_pending,
        'poll_url':reverse('task-status')+'?'+urlencode({'job':str(job.pk),'resume':str(resume.pk) if resume else ''}),
        'state': state, 'match': evaluate(job, resume, preferences), 'pending_tasks': pending,
        'usage': ai.usage(request.user), 'preferences': preferences, 'ai_available':bool(ai.configured_providers()),
        'parsed_job':parsed.result, 'tailoring_form':TailoringForm(user=request.user,initial={'masters':[resume.pk]} if resume else None), 'tailored_drafts':TailoredResume.objects.filter(user=request.user,job=job).order_by('-created')[:4],
        'source_sightings': job.sightings.select_related('source').all()})


@login_required
@require_POST
def request_review(request, job_id):
    job,resume=_job_and_resume(request.user,job_id,request.POST.get('resume'))
    if not resume:return redirect('resume')
    if not request.user.preferences.ai_consent:
        messages.info(request,'Enable hosted AI in Search preferences before requesting a review.')
        return redirect('profile')
    analysis=_analysis(request.user,job,resume)
    if analysis.method=='ai':
        messages.success(request,'Loaded the cached AI review for this exact resume and job.')
        return _detail_response(job,resume,bool(request.POST.get('resume')))
    if not ai.configured_providers():
        analysis.notice='No hosted AI provider is configured on this installation. Your compatibility breakdown and factual draft remain available.'
        analysis.save(update_fields=['notice'])
        return _detail_response(job,resume,bool(request.POST.get('resume')))
    if limited(request,'review',10):return HttpResponse('Please wait before requesting another review.',status=429)
    analysis.notice='';analysis.save(update_fields=['notice'])
    enqueue('analysis',request.user,{'job':str(job.pk),'resume':str(resume.pk)},
        key=f'analysis:{request.user.pk}:{resume.pk}:{job.pk}:{analysis.input_signature[:12]}')
    messages.success(request,'AI review queued for '+resume.filename+'. Collection runs separately; you can keep browsing.')
    return _detail_response(job,resume,bool(request.POST.get('resume')))


@login_required
@require_POST
def toggle_state(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    state, _ = JobState.objects.get_or_create(user=request.user, job=job)
    action = request.POST.get('action')
    if action == 'save': state.saved = not state.saved
    elif action == 'applied': state.applied = not state.applied
    state.save()
    if request.POST.get('return') == 'detail': return redirect('job-detail', job_id=job.pk)
    return redirect('jobs')


@login_required
@require_POST
def refresh_jobs(request):
    preferences, _ = Preferences.objects.get_or_create(user=request.user)
    if not search_ready(preferences): return redirect('profile')
    if limited(request, 'discovery', 3, 3600):
        messages.info(request, 'Discovery was requested recently. You can still browse and filter your existing matches.')
    else:
        enqueue('collect', request.user, payload={'force_search': True}, key=f'collect:{request.user.pk}')
        messages.success(request, 'Discovery queued. New matches will appear when the background worker finishes.')
    return redirect('jobs')


@login_required
def task_status(request):
    tasks=Task.objects.filter(user=request.user)
    if request.GET.get('job'):
        tasks=tasks.filter(payload__job=request.GET['job'])
        if request.GET.get('resume'):
            tasks=tasks.filter(~Q(kind='analysis')|Q(payload__resume=request.GET['resume']))
    pending_count=tasks.filter(status__in=['queued','running']).count()
    return JsonResponse({'pending_count':pending_count,'tasks':[{'id':str(task.pk),'status':task.status,
        'message':task.message,'kind':task.kind} for task in tasks.order_by('-created')[:8]]})


@login_required
def sources_view(request):
    from .services.source_registry import availability, search_usage
    from discovery_core.search import configured_search_providers
    config_path = settings.BASE_DIR / 'discovery.json'
    config = json.loads(config_path.read_text(encoding='utf-8-sig')) if config_path.exists() else {}
    providers = configured_search_providers()
    return render(request, 'careers/sources.html', {'sources': Source.objects.exclude(kind='search').order_by('kind', 'key'),
        'search_enabled': bool(providers), 'search_providers': ', '.join(p.title() for p in providers),
        'india_careers': json.loads((settings.BASE_DIR / 'india_careers.json').read_text()), 'api_availability': availability(config), 'search_usage': search_usage()})


@login_required
def export_data(request):
    resumes = list(request.user.resumes.values('filename', 'text', 'profile', 'created'))
    states = list(JobState.objects.filter(user=request.user).values('job_id', 'seen_at', 'saved', 'applied'))
    response = JsonResponse({'resumes': resumes, 'job_history': states}, json_dumps_params={'indent': 2})
    response['Content-Disposition'] = 'attachment; filename="JobSearch-my-data.json"'
    return response


@login_required
@require_POST
def delete_resumes(request):
    TailoredResume.objects.filter(user=request.user).delete()
    ParseCache.objects.filter(user=request.user).delete()
    request.user.resumes.all().delete()
    preferences = request.user.preferences
    preferences.skills = []
    preferences.save(update_fields=['skills'])
    refresh_matches(request.user)
    Task.objects.filter(user=request.user, kind__in=['analysis','tailor','interpret'], status='queued').delete()
    messages.success(request, 'Your resume text and reviews were deleted. Questionnaire-based opportunities and your job history remain available.')
    return redirect('resume')


def health(request):
    return JsonResponse({'status': 'ok', 'application': 'JobSearch'})


@login_required
@require_POST
def create_tailored(request,job_id):
    job=get_object_or_404(Job,pk=job_id)
    form=TailoringForm(request.POST,user=request.user)
    if not form.is_valid():
        messages.error(request,'Choose one to five of your own master resumes (at most 120,000 characters combined).')
        return redirect('job-detail',job_id=job.pk)
    from .services.tailoring import tailor
    masters=form.cleaned_data['masters']
    draft=tailor(request.user,job,masters,False)
    use_ai=form.cleaned_data['use_ai'] or request.POST.get('mode')=='ai'
    if use_ai:
        if not (request.user.preferences.parser_ai_consent or request.user.preferences.ai_consent):
            messages.info(request,'Enable optional parser/selection AI in the questionnaire first. A source-preserving draft is ready.')
        else:
            enqueue('tailor',request.user,{'job':str(job.pk),'masters':[str(master.pk) for master in masters]},key=f'tailor:{draft.key}')
    return redirect('tailored-detail',draft_id=draft.pk)


@login_required
def tailored_detail(request,draft_id):
    draft=get_object_or_404(TailoredResume,user=request.user,pk=draft_id)
    if request.user.resumes.filter(pk__in=draft.master_ids).count()!=len(draft.master_ids):
        draft.delete()
        return redirect('resume')
    newer=TailoredResume.objects.filter(user=request.user,job=draft.job,master_ids=draft.master_ids,created__gt=draft.created).order_by('-created').first()
    if newer:
        url=reverse('tailored-detail',kwargs={'draft_id':newer.pk})
        if request.GET.get('format'):url+='?'+urlencode({'format':request.GET['format']})
        return redirect(url)
    if request.GET.get('format')=='json':
        response=JsonResponse(draft.result,json_dumps_params={'indent':2})
        response['Content-Disposition']='attachment; filename="JobSearch-tailored-resume.json"'
        return response
    if request.GET.get('format')=='pdf':
        from .services.pdf_resume import render_pdf
        response=HttpResponse(render_pdf(draft),content_type='application/pdf')
        response['Content-Disposition']='attachment; filename="JobSearch-tailored-resume.pdf"'
        return response
    pending=Task.objects.filter(user=request.user,kind='tailor',status__in=['queued','running'],payload__job=str(draft.job_id)).exists()
    return render(request,'careers/tailored.html',{'draft':draft,'sources':draft.sources['items'],'masters':draft.sources['masters'], 'pending_tasks':pending,'poll_url':reverse('task-status')+'?'+urlencode({'job':str(draft.job_id)})})


@login_required
@require_POST
def interpret_job(request,job_id):
    job=get_object_or_404(Job,pk=job_id)
    if request.user.preferences.parser_ai_consent or request.user.preferences.ai_consent:
        enqueue('interpret',request.user,{'job':str(job.pk)},key=f'interpret:{request.user.pk}:{job.pk}:{job.content_hash[:12]}')
        messages.success(request,'Optional interpretation queued. Unstated requirements remain unknown unless supported by the posting.')
    else:messages.info(request,'Enable optional parser AI in your questionnaire to use this feature.')
    return redirect('job-detail',job_id=job.pk)
