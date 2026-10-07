from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('management', '0039_vehicledrivelink')]

    operations = [
        migrations.AddField(
            model_name='patterndesignimage',
            name='client_upload_key',
            field=models.CharField(blank=True, editable=False, max_length=120, null=True, unique=True),
        ),
    ]
