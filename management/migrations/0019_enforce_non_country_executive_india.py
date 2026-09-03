from django.db import migrations


def enforce_india_for_non_country_executives(apps, schema_editor):
    MasterSetting = apps.get_model('management', 'MasterSetting')
    UserProfile = apps.get_model('management', 'UserProfile')
    india, _ = MasterSetting.objects.get_or_create(category='Country', name='India')
    UserProfile.objects.exclude(role='country_executive').update(country=india)


class Migration(migrations.Migration):
    dependencies = [('management', '0018_direct_complaint_media_uploads')]

    operations = [migrations.RunPython(enforce_india_for_non_country_executives, migrations.RunPython.noop)]
