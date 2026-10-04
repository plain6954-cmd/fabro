from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0034_patterndesignimage_approval_workflow'),
    ]

    operations = [
        migrations.AddField(
            model_name='yearrange',
            name='drive',
            field=models.CharField(blank=True, default='', max_length=10, verbose_name='Drive'),
        ),
    ]
