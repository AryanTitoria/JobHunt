import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class Preferences(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='preferences')
    titles = models.JSONField(default=list)
    locations = models.JSONField(default=list)
    skills = models.JSONField(default=list)
    years_experience = models.PositiveSmallIntegerField(default=0)
    career_stage = models.CharField(max_length=20, default='graduate', choices=[
        ('student', 'Student / final-year student'), ('graduate', 'Fresher / recent graduate'),
        ('experienced', 'Experienced professional')])
    field_of_study = models.CharField(max_length=100, blank=True)
    search_scope = models.CharField(max_length=12, default='field', choices=[('field', 'All roles related to my field'), ('roles', 'Only my selected roles'), ('education', 'Roles related to my education'), ('combined', 'Education or selected roles')])
    opportunity_type = models.CharField(max_length=12, default='both', choices=[('both', 'Jobs and internships'), ('jobs', 'Jobs only'), ('internships', 'Internships only')])
    work_arrangement = models.CharField(max_length=12, default='any', choices=[('any', 'Any arrangement'), ('onsite', 'On-site'), ('hybrid', 'Hybrid'), ('remote', 'Remote only')])
    education_level = models.CharField(max_length=20, blank=True, choices=[('school','School / higher secondary'),('diploma','Diploma'),('bachelor','Bachelor degree'),('master','Master degree'),('doctorate','Doctorate'),('other','Other')])
    degree_name = models.CharField(max_length=100, blank=True)
    education_major = models.CharField(max_length=100, blank=True)
    graduation_year = models.PositiveSmallIntegerField(null=True, blank=True)
    employment_types = models.JSONField(default=list)
    preferred_categories = models.JSONField(default=list)
    excluded_titles = models.JSONField(default=list)
    availability = models.CharField(max_length=30, blank=True, choices=[('immediate','Immediately'),('month','Within one month'),('three_months','Within three months'),('after_graduation','After graduation'),('flexible','Flexible')])
    parser_ai_consent = models.BooleanField(default=False)
    include_unknown_work_arrangement = models.BooleanField(default=True)
    include_internships = models.BooleanField(default=True)
    include_unknown_experience = models.BooleanField(default=False)
    matching_policy_version = models.PositiveSmallIntegerField(default=0)
    allow_remote = models.BooleanField(default=True)
    minimum_score = models.PositiveSmallIntegerField(default=30)
    ai_consent = models.BooleanField(default=False)
    fallback_consent = models.BooleanField(default=False)
    updated = models.DateTimeField(auto_now=True)


class Resume(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='resumes')
    document_date = models.DateField(null=True, blank=True)
    filename = models.CharField(max_length=180)
    text = models.TextField()
    checksum = models.CharField(max_length=64)
    profile = models.JSONField(default=dict)
    created = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.filename + (f' · {self.document_date}' if self.document_date else ' · date not specified')

    class Meta:
        ordering = ['-created']
        constraints = [models.UniqueConstraint(fields=['user', 'checksum'], name='resume_per_user_hash')]


class Source(models.Model):
    key = models.CharField(max_length=500, unique=True)
    kind = models.CharField(max_length=30)
    config = models.JSONField(default=dict)
    last_checked = models.DateTimeField(null=True, blank=True)
    last_success = models.DateTimeField(null=True, blank=True)
    next_check = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=250, blank=True)
    count = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)


class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    url = models.TextField()
    url_hash = models.CharField(max_length=64, unique=True)
    fingerprint = models.CharField(max_length=64, blank=True, db_index=True)
    content_hash = models.CharField(max_length=64)
    title = models.CharField(max_length=300)
    company = models.CharField(max_length=200)
    location = models.CharField(max_length=300, blank=True)
    description = models.TextField()
    description_complete = models.BooleanField(default=True)
    application_url = models.TextField(blank=True)
    provider = models.CharField(max_length=60)
    salary = models.CharField(max_length=300, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    first_seen = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)
    active = models.BooleanField(default=True)
    remote = models.BooleanField(default=False)
    is_demo = models.BooleanField(default=False)

    class Meta:
        ordering = ['-last_seen']
        indexes = [models.Index(fields=['active', 'last_seen'])]

    @property
    def attributions(self):
        seen, items = set(), []
        for sighting in self.sightings.all():
            config = sighting.source.config
            name, url = config.get('attribution_name'), config.get('attribution_url')
            if name and url and (name, url) not in seen:
                seen.add((name, url))
                items.append({'name': name, 'url': url})
        return items


class Sighting(models.Model):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name='sightings')
    external_id = models.CharField(max_length=1200)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='sightings')
    active = models.BooleanField(default=True)
    last_seen = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source', 'external_id'], name='source_external_unique')]


class Match(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    resume = models.ForeignKey(Resume, on_delete=models.CASCADE, null=True, blank=True)
    score = models.PositiveSmallIntegerField(default=0)
    eligible = models.BooleanField(default=True)
    is_field_internship = models.BooleanField(default=False)
    policy_version = models.PositiveSmallIntegerField(default=0)
    matched_skills = models.JSONField(default=list)
    missing_skills = models.JSONField(default=list)
    reasons = models.JSONField(default=list)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'job'], name='match_user_job')]
        ordering = ['-score', '-updated']


class JobState(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    seen_at = models.DateTimeField(null=True, blank=True)
    saved = models.BooleanField(default=False)
    applied = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'job'], name='state_user_job')]


class Analysis(models.Model):
    input_signature = models.CharField(max_length=64, blank=True)
    compatibility = models.JSONField(default=dict)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    resume = models.ForeignKey(Resume, on_delete=models.CASCADE)
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    job_hash = models.CharField(max_length=64)
    result = models.JSONField(default=dict)
    method = models.CharField(max_length=30, default='rules')
    provider = models.CharField(max_length=50, blank=True)
    model = models.CharField(max_length=100, blank=True)
    notice = models.CharField(max_length=300, blank=True)
    created = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'resume', 'job', 'job_hash'], name='analysis_version_unique')]


class Task(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    kind = models.CharField(max_length=30)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=15, default='queued')
    active_key = models.CharField(max_length=200, unique=True, null=True, blank=True)
    created = models.DateTimeField(default=timezone.now)
    started = models.DateTimeField(null=True, blank=True)
    finished = models.DateTimeField(null=True, blank=True)
    message = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['created']


class BudgetBucket(models.Model):
    key = models.CharField(max_length=150, unique=True)
    used = models.PositiveIntegerField(default=0)


class ProviderHealth(models.Model):
    name = models.CharField(max_length=30, unique=True)
    cooldown_until = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=80, blank=True)


class AIEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    provider = models.CharField(max_length=30)
    model = models.CharField(max_length=100)
    outcome = models.CharField(max_length=30)
    reserved_tokens = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(default=timezone.now)


class ParseCache(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    key = models.CharField(max_length=64, unique=True)
    kind = models.CharField(max_length=30)
    result = models.JSONField(default=dict)
    method = models.CharField(max_length=30, default='rules')
    created = models.DateTimeField(auto_now_add=True)


class TailoredResume(models.Model):
    ai_state = models.CharField(max_length=20, default='not_requested')
    ai_last_attempt = models.DateTimeField(null=True, blank=True)
    provider = models.CharField(max_length=50, blank=True)
    model = models.CharField(max_length=100, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    key = models.CharField(max_length=64, unique=True)
    master_ids = models.JSONField(default=list)
    result = models.JSONField(default=dict)
    sources = models.JSONField(default=dict)
    method = models.CharField(max_length=30, default='source selection')
    notice = models.CharField(max_length=300, blank=True)
    created = models.DateTimeField(auto_now_add=True)
