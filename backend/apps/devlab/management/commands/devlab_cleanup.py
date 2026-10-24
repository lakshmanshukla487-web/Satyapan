from django.core.management.base import BaseCommand

from apps.devlab import runner, services


class Command(BaseCommand):
    help = "Delete expired developer test jobs, their temporary files and orphaned folders; close jobs whose worker died."

    def handle(self, *args, **opts):
        runner.recover_stale()
        out = services.maybe_cleanup(force=True)
        self.stdout.write(self.style.SUCCESS(f"Removed {out.get('jobs_removed', 0)} job(s) and {out.get('orphan_folders_removed', 0)} orphaned folder(s)."))
