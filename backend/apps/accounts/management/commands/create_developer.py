"""Provision a developer account for the model test lab (/developer). Developers cannot self-register.

    python manage.py create_developer alice               # prompts for the password twice (recommended)
    python manage.py create_developer alice --password-stdin < secret.txt
    python manage.py create_developer alice --revoke      # take the developer role away again (account becomes a customer, sign-ins end)

There is no default developer account and no default password. An existing customer or officer account is only converted
when --change-role is given, so a typo cannot silently turn somebody's account into a developer account."""
import getpass
import sys

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db.models import F


class Command(BaseCommand):
    help = "Create (or reset the password of) a developer account for the model test lab. Developers cannot self-register."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--password-stdin", action="store_true", help="Read the password from standard input (for scripts).")
        parser.add_argument("--change-role", action="store_true", help="Allow converting an existing customer or officer account.")
        parser.add_argument("--revoke", action="store_true", help="Remove the developer role (the account becomes a customer).")

    def handle(self, *args, username, password_stdin=False, change_role=False, revoke=False, **opts):
        User = get_user_model()
        username = username.strip().lower()
        if not username:
            raise CommandError("A username is required.")
        user = User.objects.filter(username__iexact=username).first()
        if revoke:
            if user is None or user.role != "developer":
                raise CommandError(f"'{username}' is not a developer account.")
            User.objects.filter(pk=user.pk).update(role="customer", token_epoch=F("token_epoch") + 1)  # every open sign-in ends now
            self.stdout.write(self.style.SUCCESS(f"Developer role removed from '{username}'."))
            return
        if user is not None and user.role != "developer" and not change_role:
            raise CommandError(f"'{username}' already exists as a {user.role} account. Use --change-role to convert it deliberately.")
        if password_stdin:
            password = sys.stdin.readline().rstrip("\n")
        else:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Password (again): "):
                raise CommandError("Passwords did not match.")
        user = user or User(username=username)
        try:
            validate_password(password, user)
        except ValidationError as e:
            raise CommandError(" ".join(e.messages))
        created = user.pk is None
        user.role, user.is_active = "developer", True
        user.set_password(password)  # also invalidates every token issued with the old password
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Developer '{username}' {'created' if created else 'updated'}. Sign in and open /developer."))
