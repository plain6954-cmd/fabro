from django.db import migrations, models
import django.db.models.deletion


TYPE_CATEGORIES = {
    'pattern': 'Pattern Complaint Type',
    'production': 'Production Complaint Type',
    'quality': 'Quality Complaint Type',
    'line': 'Factory Complaint Type',
}


def split_legacy_types(apps, schema_editor):
    MasterSetting = apps.get_model('management', 'MasterSetting')
    Complaint = apps.get_model('management', 'Complaint')

    for legacy_type in list(MasterSetting.objects.filter(category='Type').order_by('pk')):
        legacy_type.category = TYPE_CATEGORIES['pattern']
        legacy_type.save(update_fields=['category'])
        scoped_types = {'pattern': legacy_type}
        for complaint_type, category in TYPE_CATEGORIES.items():
            if complaint_type == 'pattern':
                continue
            scoped_types[complaint_type], _ = MasterSetting.objects.get_or_create(
                category=category,
                name=legacy_type.name,
            )

        for complaint_type, scoped_type in scoped_types.items():
            Complaint.objects.filter(
                case_sub_category=legacy_type,
                complaint_type=complaint_type,
            ).update(case_sub_category=scoped_type)


def merge_scoped_types(apps, schema_editor):
    MasterSetting = apps.get_model('management', 'MasterSetting')
    Complaint = apps.get_model('management', 'Complaint')
    scoped_categories = list(TYPE_CATEGORIES.values())
    names = MasterSetting.objects.filter(
        category__in=scoped_categories,
    ).values_list('name', flat=True).distinct()

    for name in names:
        settings = list(MasterSetting.objects.filter(
            category__in=scoped_categories,
            name=name,
        ).order_by('pk'))
        if not settings:
            continue
        preferred = next(
            (item for item in settings if item.category == TYPE_CATEGORIES['pattern']),
            settings[0],
        )
        Complaint.objects.filter(case_sub_category__in=settings).update(
            case_sub_category=preferred,
        )
        MasterSetting.objects.filter(
            pk__in=[item.pk for item in settings if item.pk != preferred.pk]
        ).delete()
        preferred.category = 'Type'
        preferred.save(update_fields=['category'])


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0014_rename_line_to_factory_complaint'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mastersetting',
            name='category',
            field=models.CharField(
                choices=[
                    ('Channel', 'Channel'),
                    ('Country', 'Country'),
                    ('Reported By', 'Reported By'),
                    ('Pattern Complaint Type', 'Pattern Complaint Types'),
                    ('Production Complaint Type', 'Production Complaint Types'),
                    ('Quality Complaint Type', 'Quality Complaint Types'),
                    ('Factory Complaint Type', 'Factory Complaint Types'),
                    ('Series', 'Series'),
                    ('Material', 'Material'),
                    ('Region', 'Region'),
                ],
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name='mastersetting',
            name='name',
            field=models.CharField(max_length=100),
        ),
        migrations.RunPython(split_legacy_types, merge_scoped_types),
        migrations.AlterField(
            model_name='complaint',
            name='case_sub_category',
            field=models.ForeignKey(
                limit_choices_to={
                    'category__in': [
                        'Pattern Complaint Type',
                        'Production Complaint Type',
                        'Quality Complaint Type',
                        'Factory Complaint Type',
                    ]
                },
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='complaints_as_case_sub_category',
                to='management.mastersetting',
            ),
        ),
    ]
