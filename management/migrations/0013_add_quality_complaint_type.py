from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0012_expand_workflow_status_length'),
    ]

    operations = [
        migrations.AlterField(
            model_name='complaint',
            name='complaint_type',
            field=models.CharField(
                choices=[
                    ('pattern', 'Pattern Complaint'),
                    ('production', 'Production Complaint'),
                    ('quality', 'Quality Complaint'),
                    ('line', 'Line Complaint'),
                ],
                db_index=True,
                default='pattern',
                max_length=20,
            ),
        ),
    ]
