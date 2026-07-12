"""Celery tasks for the FastAPI app."""
from celery import shared_task


@shared_task(name="app.tasks.send_welcome_email")
def send_welcome_email(user_id: int):
    pass


@shared_task
def process_upload(file_id: int):
    pass
