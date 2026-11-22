from django.db import migrations
import re


def fill_fields(apps, schema_editor):
    Preferences = apps.get_model('careers', 'Preferences')
    Resume = apps.get_model('careers', 'Resume')
    for preference in Preferences.objects.all().iterator():
        resume = Resume.objects.filter(user_id=preference.user_id).order_by('-created').first()
        text = resume.text if resume else ''
        if not preference.field_of_study and re.search(r'computer science|computer engineering|information technology|software engineering|\bcse\b', text, re.I):
            preference.field_of_study = 'Computer Science'
        preference.career_stage = 'experienced' if preference.years_experience else ('student' if re.search(r'final.year|student|currently pursuing', text, re.I) else 'graduate')
        preference.save(update_fields=['field_of_study', 'career_stage'])


class Migration(migrations.Migration):
    dependencies = [('careers', '0004_match_policy_version_and_more')]
    operations = [migrations.RunPython(fill_fields, migrations.RunPython.noop)]
