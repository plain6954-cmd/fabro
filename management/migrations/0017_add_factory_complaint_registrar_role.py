from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0016_userprofile_preferred_language'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userprofile',
            name='role',
            field=models.CharField(
                choices=[
                    ('country_executive', 'Country Executive'),
                    ('factory_viewer', 'Factory Viewer'),
                    ('factory_executive', 'Factory Executive'),
                    ('factory_complaint_registrar', 'Factory Complaint Registrar'),
                    ('approver', 'Approver'),
                    ('admin', 'Admin'),
                ],
                default='factory_viewer',
                max_length=30,
            ),
        ),
    ]
