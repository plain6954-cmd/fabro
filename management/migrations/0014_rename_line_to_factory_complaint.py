from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0013_add_quality_complaint_type'),
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
                    ('line', 'Factory Complaint'),
                ],
                db_index=True,
                default='pattern',
                max_length=20,
            ),
        ),
    ]
