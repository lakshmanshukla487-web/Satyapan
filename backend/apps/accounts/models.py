from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Customers run verifications; officers review them; developers test the detection models offline (developer test lab).
    Only customers can self-register: officer and developer accounts are created by an administrator (management commands)."""
    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        OFFICER = "officer", "Officer"
        DEVELOPER = "developer", "Developer"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER, db_index=True)
    # Bumped on sign-out: every token issued with an older value stops working (server-side revocation, OWASP A07).
    token_epoch = models.PositiveIntegerField(default=0)

    @property
    def is_officer(self) -> bool:
        return self.role == self.Role.OFFICER

    @property
    def is_developer(self) -> bool:
        return self.role == self.Role.DEVELOPER
