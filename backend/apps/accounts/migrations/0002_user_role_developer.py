# Adds the "developer" role (developer model test lab). Only the field's choices change: the column (varchar(10)) and every
# existing value stay as they are, so existing customer and officer accounts are untouched.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(choices=[('customer', 'Customer'), ('officer', 'Officer'), ('developer', 'Developer')], db_index=True, default='customer', max_length=10),
        ),
    ]
