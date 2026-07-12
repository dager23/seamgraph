"""Django settings module for testing."""

SECRET_KEY = "django-test-secret"
DEBUG = True
ALLOWED_HOSTS = ["*"]
STRIPE_API_KEY = "sk_test_xxx"
DATABASE_URL = "postgresql://localhost:5432/shop"
CELERY_BROKER_URL = "redis://localhost:6379/0"

INSTALLED_APPS = [
    "shop",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": ["templates"],
        "APP_DIRS": True,
    },
]
