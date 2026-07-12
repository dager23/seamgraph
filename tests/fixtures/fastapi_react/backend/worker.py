"""Celery beat schedule + task call for testing."""
from celery import signature

result = signature("app.tasks.send_welcome_email").delay(user_id=42)
