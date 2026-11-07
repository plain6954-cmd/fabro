from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('management', '0052_picked_color_photos')]

    operations = [
        migrations.AddField(
            model_name='pickedcolorselection', name='category',
            field=models.CharField(max_length=20, choices=[('interior_match', 'Interior Match'),
                ('fabro_color', 'Fabro Color')], default='interior_match'),
        ),
        migrations.AddConstraint(
            model_name='pickedcolorselection',
            constraint=models.CheckConstraint(condition=models.Q(category__in=['interior_match', 'fabro_color']),
                                              name='picked_color_category_valid'),
        ),
    ]
