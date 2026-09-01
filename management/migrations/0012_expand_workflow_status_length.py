from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0011_execution_verification_workflow'),
    ]

    operations = [
        migrations.AlterField(
            model_name='complaint',
            name='workflow_status',
            field=models.CharField(
                choices=[
                    ('submitted', 'Submitted'),
                    ('assigned_to_factory', 'Assigned to Factory'),
                    ('factory_review', 'Factory Review'),
                    ('awaiting_approval', 'Awaiting Approval'),
                    ('partially_approved', 'Partially Approved'),
                    ('rework_required', 'Rework Required'),
                    ('approved', 'Approved'),
                    ('action_in_progress', 'Action In Progress'),
                    ('awaiting_execution_verification', 'Awaiting Execution Verification'),
                    ('execution_partially_verified', 'Execution Partially Verified'),
                    ('pending_final_update', 'Pending Final Update'),
                    ('closed', 'Closed'),
                    ('on_hold', 'On Hold'),
                ],
                db_index=True,
                default='submitted',
                max_length=40,
            ),
        ),
    ]
