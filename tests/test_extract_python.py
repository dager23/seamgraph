"""Tests for the Python code extractor."""

from __future__ import annotations

from seamgraph.extract.python_code import extract_python, resolve_routes
from seamgraph.models import AnchorKind


class TestEnvReads:
    def test_os_environ_subscript(self) -> None:
        src = 'import os\ndb = os.environ["DATABASE_URL"]\n'
        facts = extract_python("app.py", src)
        envs = [a for a in facts.anchors if a.kind is AnchorKind.ENV_READ]
        assert len(envs) == 1
        assert envs[0].key == "DATABASE_URL"
        assert envs[0].detail == "os.environ[...]"

    def test_os_getenv(self) -> None:
        src = 'import os\nkey = os.getenv("SECRET_KEY")\n'
        facts = extract_python("app.py", src)
        envs = [a for a in facts.anchors if a.kind is AnchorKind.ENV_READ]
        assert len(envs) == 1
        assert envs[0].key == "SECRET_KEY"

    def test_os_environ_get(self) -> None:
        src = 'import os\nurl = os.environ.get("REDIS_URL", "redis://localhost")\n'
        facts = extract_python("app.py", src)
        envs = [a for a in facts.anchors if a.kind is AnchorKind.ENV_READ]
        assert len(envs) == 1
        assert envs[0].key == "REDIS_URL"

    def test_pydantic_settings(self) -> None:
        src = """\
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    secret_key: str
    model_config = SettingsConfigDict(env_prefix="APP_")
"""
        facts = extract_python("config.py", src)
        envs = [a for a in facts.anchors if a.kind is AnchorKind.ENV_READ]
        keys = {a.key for a in envs}
        assert "APP_DATABASE_URL" in keys
        assert "APP_SECRET_KEY" in keys


class TestRoutes:
    def test_fastapi_route_def(self) -> None:
        src = """\
from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
async def health():
    pass
"""
        facts = extract_python("main.py", src)
        assert len(facts.routes) == 1
        assert facts.routes[0].path == "/health"
        assert facts.routes[0].framework == "fastapi"

    def test_fastapi_router_with_prefix(self) -> None:
        src = """\
from fastapi import APIRouter
router = APIRouter(prefix="/api/v1")

@router.get("/users/{user_id}")
async def get_user(user_id: int):
    pass

@router.post("/users")
async def create_user():
    pass
"""
        facts = extract_python("routes.py", src)
        assert len(facts.routes) == 2

    def test_flask_route_def(self) -> None:
        src = """\
from flask import Flask
app = Flask(__name__)

@app.route("/")
def index():
    pass
"""
        facts = extract_python("app.py", src)
        assert len(facts.routes) == 1

    def test_django_path(self) -> None:
        src = """\
from django.urls import path
from . import views
urlpatterns = [
    path("orders/<int:pk>/", views.order_detail, name="order-detail"),
]
"""
        facts = extract_python("urls.py", src)
        assert len(facts.routes) == 1
        urlnames = [a for a in facts.anchors if a.kind is AnchorKind.URLNAME_DEF]
        assert len(urlnames) == 1
        assert urlnames[0].key == "order-detail"

    def test_route_client_call(self) -> None:
        src = """\
class TestAPI:
    def test_health(self):
        r = self.client.get("/health")
"""
        facts = extract_python("test_api.py", src)
        calls = [a for a in facts.anchors if a.kind is AnchorKind.ROUTE_CALL]
        assert len(calls) == 1
        assert "/health" in calls[0].key


class TestTemplates:
    def test_render_template(self) -> None:
        src = """\
from flask import render_template
def index():
    return render_template("index.html", title="Home")
"""
        facts = extract_python("views.py", src)
        refs = [a for a in facts.anchors if a.kind is AnchorKind.TEMPLATE_REF]
        assert len(refs) == 1
        assert refs[0].key == "index.html"

    def test_django_render(self) -> None:
        src = """\
from django.shortcuts import render
def order_list(request):
    return render(request, "shop/order_list.html", {"title": "Orders"})
"""
        facts = extract_python("views.py", src)
        refs = [a for a in facts.anchors if a.kind is AnchorKind.TEMPLATE_REF]
        assert len(refs) == 1
        assert refs[0].key == "shop/order_list.html"


class TestUrlNames:
    def test_reverse(self) -> None:
        src = """\
from django.urls import reverse
url = reverse("order-detail", kwargs={"pk": 1})
"""
        facts = extract_python("views.py", src)
        refs = [a for a in facts.anchors if a.kind is AnchorKind.URLNAME_REF]
        assert len(refs) == 1
        assert refs[0].key == "order-detail"

    def test_url_for(self) -> None:
        src = """\
from flask import url_for
def go():
    return url_for("index")
"""
        facts = extract_python("app.py", src)
        refs = [a for a in facts.anchors if a.kind is AnchorKind.URLNAME_REF]
        assert len(refs) == 1
        assert refs[0].key == "index"


class TestCeleryTasks:
    def test_shared_task_named(self) -> None:
        src = """\
from celery import shared_task

@shared_task(name="app.tasks.send_email")
def send_email(user_id):
    pass
"""
        facts = extract_python("tasks.py", src)
        tasks = [a for a in facts.anchors if a.kind is AnchorKind.TASK_DEF]
        assert len(tasks) == 1
        assert tasks[0].key == "app.tasks.send_email"

    def test_shared_task_auto_named(self) -> None:
        src = """\
from celery import shared_task

@shared_task
def process_upload(file_id):
    pass
"""
        facts = extract_python("tasks.py", src)
        tasks = [a for a in facts.anchors if a.kind is AnchorKind.TASK_DEF]
        assert len(tasks) == 1
        assert tasks[0].raw == "process_upload"
        assert "?auto?" in tasks[0].key

    def test_send_task(self) -> None:
        src = """\
from celery import signature
result = signature("app.tasks.send_email").delay()
"""
        facts = extract_python("worker.py", src)
        calls = [a for a in facts.anchors if a.kind is AnchorKind.TASK_CALL]
        assert len(calls) == 1
        assert calls[0].key == "app.tasks.send_email"


class TestDjangoSettings:
    def test_settings_def(self) -> None:
        src = """\
SECRET_KEY = "django-test"
DEBUG = True
STRIPE_API_KEY = "sk_test_xxx"
x = 5  # not a setting (lowercase)
"""
        facts = extract_python("settings.py", src)
        defs = [a for a in facts.anchors if a.kind is AnchorKind.SETTING_DEF]
        keys = {a.key for a in defs}
        assert "SECRET_KEY" in keys
        assert "DEBUG" in keys
        assert "STRIPE_API_KEY" in keys
        assert "x" not in keys  # lowercase, not a setting

    def test_settings_read(self) -> None:
        src = """\
from django.conf import settings
api_key = settings.STRIPE_API_KEY
"""
        facts = extract_python("views.py", src)
        reads = [a for a in facts.anchors if a.kind is AnchorKind.SETTING_READ]
        assert len(reads) == 1
        assert reads[0].key == "STRIPE_API_KEY"


class TestResolveRoutes:
    def test_fastapi_include_router(self) -> None:
        main_src = """\
from fastapi import FastAPI
from .routes import router

app = FastAPI()
app.include_router(router, prefix="/api")
"""
        routes_src = """\
from fastapi import APIRouter
router = APIRouter(prefix="/v1")

@router.get("/users/{user_id}")
async def get_user(user_id: int):
    pass
"""
        main_facts = extract_python("main.py", main_src)
        routes_facts = extract_python("routes.py", routes_src)
        all_facts = {"main.py": main_facts, "routes.py": routes_facts}
        anchors = resolve_routes(all_facts)
        route_defs = [a for a in anchors if a.kind is AnchorKind.ROUTE_DEF]
        # Should have the combined prefix
        assert any("/api/v1/users" in a.key for a in route_defs)
