"""File-backed regression: upload a resume while discovery writes 300 jobs."""
import hashlib
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'platform_config.settings')
import django
django.setup()

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connections, close_old_connections
from django.test import Client, override_settings
from careers.models import Job, Resume, Preferences, Source, Match
from careers.services.collection import ingest
from careers.services import matching
from discovery_core.fetch import Job as Posting
from discovery_core.sources import SourceResult


def main():
    call_command('migrate', verbosity=0)
    user = get_user_model().objects.create_user('concurrent-upload')
    Preferences.objects.create(user=user, skills=['Python', 'Django', 'SQL'], locations=['India'],field_of_study='Computer Science')
    Job.objects.bulk_create([Job(url=f'https://example.org/seed/{i}', url_hash=hashlib.sha256(f'seed:{i}'.encode()).hexdigest(),
        content_hash='seed', title='Software Engineer', company='Seed', location='India',
        description='Python Django SQL services', provider='test') for i in range(600)])
    source = Source.objects.create(key='regression:source', kind='feed')
    postings = [Posting(f'test:{i}', 'test', f'Company {i}', 'Software Engineer', 'India',
        f'https://example.org/discovered/{i}', f'Unique team {i}: Python Django SQL services') for i in range(300)]
    client = Client()
    client.force_login(user)
    started = threading.Event()
    errors = []
    original = matching.evaluate
    def slow_evaluate(*args, **kwargs):
        started.set()
        time.sleep(.001)
        return original(*args, **kwargs)
    def collect():
        close_old_connections()
        try:
            if not started.wait(10):
                raise RuntimeError('upload did not start matching')
            ingest(Source.objects.get(pk=source.pk), SourceResult(source.key, postings))
        except Exception as error:
            errors.append(error)
        finally:
            connections.close_all()
    worker = threading.Thread(target=collect)
    with override_settings(ALLOWED_HOSTS=['testserver'], DEMO_MODE=False), patch.object(matching, 'evaluate', slow_evaluate):
        worker.start()
        try:
            text = 'Software Engineer\nSkills: Python, Django, SQL\nBuilt reliable Python APIs with Django and SQL for an internal service.\n'
            response = client.post('/resume/', {'resume': SimpleUploadedFile('resume.txt', text.encode()), 'locations': 'India'})
            assert response.status_code == 302, response.status_code
            response = client.post('/profile/', {'career_stage':'graduate','years_experience':0,'field_of_study':'Computer Science',
                'search_scope':'field','opportunity_type':'both','work_arrangement':'any','include_unknown_work_arrangement':'on',
                'include_unknown_experience':'on','locations_text':'India'})
            assert response.status_code == 302, response.status_code
        finally:
            worker.join(timeout=30)
        assert not worker.is_alive(), 'collector did not finish'
        assert not errors, repr(errors)
        # Finish matching jobs that arrived behind an already-visited UUID page.
        matching.refresh_matches(user)
    assert Job.objects.count() == 900
    assert Match.objects.filter(user=user).count() == 900
    assert Resume.objects.filter(user=user).count() == 1
    print('PASS: concurrent resume upload + 300 job writes; 900 matches; no lock errors')
    connections.close_all()


if __name__ == '__main__':
    main()
