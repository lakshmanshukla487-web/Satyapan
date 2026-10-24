from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

DEMO = [("officer", "officer", "officer-pass-123"), ("customer", "customer", "customer-pass-123")]


class Command(BaseCommand):
    help = "Create demo accounts with publicly known passwords. Development only (APP_ENV=development)."

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("Refusing to create demo accounts outside APP_ENV=development.")
        User = get_user_model()
        for username, role, password in DEMO:
            u, _ = User.objects.get_or_create(username=username, defaults={"role": role})
            u.role, u.is_active = role, True
            u.set_password(password)
            u.save()
            self.stdout.write(f"  {role:<9} {username} / {password}")
        self.stdout.write(self.style.SUCCESS("Demo accounts ready. Never use these in production."))
