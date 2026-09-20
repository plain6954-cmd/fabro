from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0031_yearrange_br'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='yearrange',
            unique_together=set(),
        ),
    ]
