from django.db import migrations


def preserve(apps, schema_editor):
    Preferences = apps.get_model('careers', 'Preferences')
    Preferences.objects.filter(include_internships=False).update(opportunity_type='jobs')
    Preferences.objects.filter(field_of_study='').update(search_scope='roles')


class Migration(migrations.Migration):
    dependencies = [('careers', '0006_preferences_include_unknown_work_arrangement_and_more')]
    operations = [migrations.RunPython(preserve, migrations.RunPython.noop)]
