from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0015_complaint_specific_type_catalogs'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='preferred_language',
            field=models.CharField(
                choices=[
                    ('en', 'English'),
                    ('ar', 'العربية'),
                    ('hi', 'हिन्दी'),
                ],
                default='en',
                max_length=5,
            ),
        ),
    ]
