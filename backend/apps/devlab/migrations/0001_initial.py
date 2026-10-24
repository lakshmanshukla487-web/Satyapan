# Developer model test lab tables (isolated from the verification tables: no relation to a session).
import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DevTestJob',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(blank=True, default='', max_length=120)),
                ('source', models.CharField(default='upload', max_length=10)),
                ('dataset', models.CharField(blank=True, default='', max_length=80)),
                ('status', models.CharField(db_index=True, default='draft', max_length=12)),
                ('options', models.JSONField(blank=True, default=dict)),
                ('total_items', models.PositiveIntegerField(default=0)),
                ('total_bytes', models.BigIntegerField(default=0)),
                ('cancel_requested', models.BooleanField(default=False)),
                ('error', models.CharField(blank=True, default='', max_length=300)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('heartbeat_at', models.DateTimeField(blank=True, null=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='devlab_jobs', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='DevTestItem',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('index', models.PositiveIntegerField(default=0)),
                ('filename', models.CharField(max_length=255)),
                ('media_type', models.CharField(max_length=8)),
                ('file_format', models.CharField(blank=True, default='', max_length=10)),
                ('size_bytes', models.BigIntegerField(default=0)),
                ('label', models.CharField(blank=True, default='', max_length=8)),
                ('stored_path', models.CharField(blank=True, default='', max_length=500)),
                ('owns_file', models.BooleanField(default=True)),
                ('status', models.CharField(db_index=True, default='queued', max_length=12)),
                ('detector', models.CharField(blank=True, default='', max_length=40)),
                ('model_id', models.CharField(blank=True, default='', max_length=200)),
                ('model_version', models.CharField(blank=True, default='', max_length=80)),
                ('score', models.FloatField(blank=True, null=True)),
                ('score_kind', models.CharField(blank=True, default='', max_length=40)),
                ('threshold', models.FloatField(blank=True, null=True)),
                ('prediction', models.CharField(blank=True, default='', max_length=8)),
                ('model_label', models.CharField(blank=True, default='', max_length=60)),
                ('duration_ms', models.FloatField(blank=True, null=True)),
                ('frames_analyzed', models.PositiveIntegerField(blank=True, null=True)),
                ('segments_analyzed', models.PositiveIntegerField(blank=True, null=True)),
                ('warnings', models.JSONField(blank=True, default=list)),
                ('error_code', models.CharField(blank=True, default='', max_length=60)),
                ('details', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='devlab.devtestjob')),
            ],
            options={
                'ordering': ['index'],
                'indexes': [models.Index(fields=['job', 'index'], name='devlab_item_job_idx')],
            },
        ),
    ]
