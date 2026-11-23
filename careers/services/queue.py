from datetime import timedelta
from django.db import IntegrityError, transaction
from django.db.models import Case, When, Value, IntegerField
from django.utils import timezone
from careers.models import Task
import logging

logger = logging.getLogger(__name__)


def enqueue(kind, user=None, payload=None, key=None):
    # Null active_key allows completed tasks to retain history without blocking retries.
    if key:
        existing = Task.objects.filter(active_key=key).first()
        if existing:
            return existing
    try:
        with transaction.atomic():
            return Task.objects.create(kind=kind, user=user, payload=payload or {}, active_key=key)
    except IntegrityError:
        return Task.objects.get(active_key=key)


INTERACTIVE_KINDS = ('analysis','tailor','interpret','match')


def claim(kinds=None):
    # The compare-and-update claim works with SQLite and PostgreSQL.
    stale = timezone.now() - timedelta(minutes=30)
    Task.objects.filter(status='running', started__lt=stale).update(
        status='failed', active_key=None, finished=timezone.now(), message='Worker stopped. Please retry.')
    candidates=Task.objects.filter(status='queued')
    if kinds is not None:
        candidates=candidates.filter(kind__in=kinds).order_by('-created')
    else:
        candidates=candidates.annotate(lane=Case(When(kind__in=INTERACTIVE_KINDS,then=Value(0)),default=Value(1),output_field=IntegerField())).order_by('lane','created')
    for task in candidates[:20]:
        if Task.objects.filter(pk=task.pk, status='queued').update(status='running', started=timezone.now()):
            task.refresh_from_db()
            return task
    return None


def execute(task):
    try:
        if task.kind == 'match':
            from .matching import refresh_matches
            count = refresh_matches(task.user)
            message = f'Updated experience eligibility and field-internship matches across {count} postings.'
        elif task.kind == 'collect':
            from .collection import collect_inventory
            result = collect_inventory(task.user, force_search=task.payload.get('force_search', False))
            message = f"Checked {result['sources']} sources; observed {result['jobs']} postings."
            if result['errors']:
                message += f" {len(result['errors'])} sources unavailable; existing jobs retained."
        elif task.kind == 'tailor':
            from careers.models import Resume, Job
            from .tailoring import tailor
            by_id={str(master.pk):master for master in Resume.objects.filter(user=task.user,pk__in=task.payload['masters'])}
            masters=[by_id[identifier] for identifier in task.payload['masters'] if identifier in by_id]
            if len(masters)!=len(task.payload['masters']):raise ValueError('Master resume unavailable')
            tailor(task.user,Job.objects.get(pk=task.payload['job']),masters,True)
            message='Your source-backed tailored draft is ready.'
        elif task.kind == 'interpret':
            from careers.models import Job
            from .interpretation import interpret
            interpret(task.user,Job.objects.get(pk=task.payload['job']),True)
            message='Selected-job interpretation ready; unclear requirements remain marked.'
        elif task.kind == 'analysis':
            from careers.models import Analysis, Resume, Job, Preferences
            from .ai import review, AIUnavailable
            from .matching import basic_guidance
            resume = Resume.objects.get(pk=task.payload['resume'], user=task.user)
            job = Job.objects.get(pk=task.payload['job'])
            preferences = Preferences.objects.get(user=task.user)
            from .reviews import analysis_for
            analysis=analysis_for(task.user,job,resume)
            if analysis.method == 'ai':
                message = 'Loaded your cached resume review.'
            else:
                try:
                    result, provider, model = review(task.user, resume, job, preferences)
                except AIUnavailable as error:
                    analysis.notice = str(error)[:300]
                    analysis.save(update_fields=['notice'])
                    Task.objects.filter(pk=task.pk).update(status='failed',active_key=None,finished=timezone.now(),message=str(error)[:300])
                    return False
                else:
                    analysis.result, analysis.method = result, 'ai'
                    analysis.provider, analysis.model, analysis.notice = provider, model, ''
                    analysis.save()
                    message = 'Your job-specific resume review is ready.'
        else:
            raise ValueError('Unknown task kind')
    except Exception as error:
        logger.error('Background task failed: kind=%s error_type=%s', task.kind, type(error).__name__)
        # Never put resume content, API responses or credentials into logs/UI errors.
        Task.objects.filter(pk=task.pk).update(status='failed', active_key=None, finished=timezone.now(),
                                              message='This task could not complete. Your data is saved; please retry.')
        return False
    Task.objects.filter(pk=task.pk).update(status='done', active_key=None, finished=timezone.now(), message=message[:300])
    return True
