from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0030_patterneditlog_pattern_serial_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='yearrange',
            name='br',
            field=models.CharField(blank=True, default='', max_length=20, verbose_name='BR'),
        ),
    ]
