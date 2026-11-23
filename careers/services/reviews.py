"""Per-resume, content-addressed advice and comparison cache."""
from careers.models import Analysis, Preferences
from .compatibility import report, signature
from .matching import basic_guidance


def analysis_for(user, job, resume):
    preferences, _ = Preferences.objects.get_or_create(user=user)
    current = signature(job, resume)
    row, created = Analysis.objects.get_or_create(user=user, job=job, resume=resume,
        job_hash=job.content_hash, defaults={'result':basic_guidance(job,resume,preferences),
                                          'input_signature':current,'compatibility':report(job,resume)})
    if row.input_signature != current:
        preserve_ai=not row.input_signature and row.method=='ai'
        if not preserve_ai:row.result=basic_guidance(job,resume,preferences)
        row.compatibility=report(job,resume)
        row.input_signature=current
        if not preserve_ai:
            row.method='rules';row.provider='';row.model='';row.notice=''
        row.save()
    return row
