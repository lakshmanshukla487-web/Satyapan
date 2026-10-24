import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create an officer account (officers cannot self-register), or reset an existing account's password."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--password", help="Omit to be prompted (recommended: keeps it out of shell history).")

    def handle(self, *args, username, password=None, **opts):
        User = get_user_model()
        username = username.strip().lower()
        if password is None:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Password (again): "):
                raise CommandError("Passwords did not match.")
        user = User.objects.filter(username__iexact=username).first() or User(username=username)
        try:
            validate_password(password, user)
        except ValidationError as e:
            raise CommandError(" ".join(e.messages))
        created = user.pk is None
        user.role, user.is_active = "officer", True
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Officer '{username}' {'created' if created else 'updated'}."))
