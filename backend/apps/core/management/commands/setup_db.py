"""One command that leaves the database ready: creates missing migration files, applies them, and verifies that every
table and column the code expects really exists.

    python manage.py setup_db            # normal use; start.sh / start.ps1 / Docker call this
    python manage.py setup_db --check    # only verify, change nothing (exit code 1 when the schema is wrong)

Why it exists: the project ships without migration files (they are generated on first run), and an old satyapan.db from
an earlier version has different tables. Either one made the first sign-up fail with HTTP 500. In development with
SQLite, a wrong database is backed up (satyapan.db.bak-<time>) and rebuilt automatically. With any other database
it only reports the problem; it never deletes data it was not asked to.
"""
import shutil
import time
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def project_apps():
    return [c for c in apps.get_app_configs() if c.name.startswith("apps.") and list(c.get_models())]


def schema_problems() -> list[str]:
    problems = []
    try:
        with connection.cursor() as cur:
            tables = set(connection.introspection.table_names(cur))
            for cfg in project_apps():
                for model in cfg.get_models():
                    t = model._meta.db_table
                    if t not in tables:
                        problems.append(f"missing table {t}")
                        continue
                    have = {c.name for c in connection.introspection.get_table_description(cur, t)}
                    for f in model._meta.concrete_fields:
                        if f.column not in have:
                            problems.append(f"missing column {t}.{f.column}")
    except Exception as e:  # noqa: BLE001
        problems.append(f"cannot inspect the database: {type(e).__name__}: {e}")
    return problems


class Command(BaseCommand):
    help = "Create migration files, apply them and verify the schema (see module docstring)."

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true", help="Only verify the schema; change nothing.")
        parser.add_argument("--no-reset", action="store_true", help="Never rebuild a wrong development SQLite database.")

    # -- helpers -----------------------------------------------------------------------------------------------------
    def _ensure_packages(self):
        for cfg in project_apps():
            mig = Path(cfg.path) / "migrations"
            mig.mkdir(exist_ok=True)
            (mig / "__init__.py").touch(exist_ok=True)

    def _build(self) -> bool:
        """makemigrations + migrate. True when both succeeded."""
        self._ensure_packages()
        labels = [c.label for c in project_apps()]
        try:
            call_command("makemigrations", *labels, interactive=False, verbosity=1)
            call_command("migrate", interactive=False, verbosity=1)
            return True
        except (Exception, SystemExit) as e:  # noqa: BLE001  (makemigrations exits with a code when it needs an answer)
            self.stderr.write(self.style.WARNING(f"database setup step failed: {type(e).__name__}: {e}"))
            return False

    def _can_reset(self) -> bool:
        return settings.DEBUG and connection.vendor == "sqlite" and connection.settings_dict["NAME"] not in ("", ":memory:")

    def _reset_dev_sqlite(self):
        connection.close()
        db = Path(connection.settings_dict["NAME"])
        if db.exists():
            bak = db.with_name(f"{db.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(db, bak)
            db.unlink()
            self.stdout.write(self.style.WARNING(f"The old development database did not match this version. Backed it up to {bak.name} and rebuilt it."))
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for cfg in project_apps():  # generated files from an older version may not fit the current models either: set aside, not deleted
            for f in (Path(cfg.path) / "migrations").glob("0*.py"):
                f.rename(f.with_name(f"{f.name}.bak-{stamp}"))

    # -- main --------------------------------------------------------------------------------------------------------
    def handle(self, *args, **opts):
        if opts["check"]:
            problems = schema_problems()
            if problems:
                for p in problems:
                    self.stderr.write("  - " + p)
                raise CommandError("The database does not match the code. Run: python manage.py setup_db")
            self.stdout.write(self.style.SUCCESS("Database schema OK."))
            return
        ok = self._build()
        problems = schema_problems() if ok else ["setup step failed"]
        if problems and self._can_reset() and not opts["no_reset"]:
            self.stdout.write(f"Schema problems: {problems[:5]}")
            self._reset_dev_sqlite()
            ok = self._build()
            problems = schema_problems() if ok else ["setup step failed after rebuilding"]
        if problems:
            for p in problems:
                self.stderr.write("  - " + p)
            raise CommandError("The database could not be prepared. See the messages above"
                               + ("" if self._can_reset() else " (automatic rebuild only happens for a development SQLite file)."))
        self.stdout.write(self.style.SUCCESS("Database ready."))
