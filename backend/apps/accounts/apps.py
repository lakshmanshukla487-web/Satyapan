from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    verbose_name = "Accounts and bearer-token authentication"

    def ready(self):
        from apps.accounts import auth  # noqa: F401  (registers the OpenAPI auth scheme)
