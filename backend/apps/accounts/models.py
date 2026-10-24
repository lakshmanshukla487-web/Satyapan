from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Customers run verifications; officers review them. Officers are never self-registered."""
    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        OFFICER = "officer", "Officer"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER, db_index=True)
    # Bumped on sign-out: every token issued with an older value stops working (server-side revocation, OWASP A07).
    token_epoch = models.PositiveIntegerField(default=0)

    @property
    def is_officer(self) -> bool:
        return self.role == self.Role.OFFICER
