# Generated by Django 5.1.1 on 2024-09-29 15:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='role',
            field=models.CharField(choices=[('customer', 'Customer'), ('barista', 'Barista')], default='customer', max_length=10),
        ),
    ]
