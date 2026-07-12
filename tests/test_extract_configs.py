"""Tests for config file extractors."""
from __future__ import annotations

from seamgraph.extract.configs import (
    extract_actions,
    extract_compose,
    extract_config_file,
    extract_dockerfile,
    extract_dotenv,
    extract_k8s,
    extract_makefile,
    extract_package_json,
    extract_pyproject_scripts,
)
from seamgraph.models import AnchorKind


class TestDotenv:
    def test_basic_env(self) -> None:
        text = "DATABASE_URL=postgresql://localhost\nSECRET_KEY=abc\n"
        anchors = extract_dotenv(".env", text)
        assert len(anchors) == 2
        keys = {a.key for a in anchors}
        assert keys == {"DATABASE_URL", "SECRET_KEY"}
        assert all(a.kind is AnchorKind.ENV_DEF for a in anchors)

    def test_export_prefix(self) -> None:
        text = "export API_KEY=xyz\n"
        anchors = extract_dotenv(".env", text)
        assert len(anchors) == 1
        assert anchors[0].key == "API_KEY"

    def test_skip_comments(self) -> None:
        text = "# comment\nKEY=val\n"
        anchors = extract_dotenv(".env", text)
        assert len(anchors) == 1


class TestDockerfile:
    def test_env_instruction(self) -> None:
        text = "FROM python:3.12\nENV APP_ENV=production\nENV DEBUG=0\n"
        anchors = extract_dockerfile("Dockerfile", text)
        keys = {a.key for a in anchors}
        assert "APP_ENV" in keys
        assert "DEBUG" in keys

    def test_arg_instruction(self) -> None:
        text = "ARG BUILD_VERSION=1.0\n"
        anchors = extract_dockerfile("Dockerfile", text)
        assert len(anchors) == 1
        assert anchors[0].key == "BUILD_VERSION"


class TestCompose:
    def test_environment_dict(self) -> None:
        text = """\
version: "3"
services:
  web:
    environment:
      DATABASE_URL: postgresql://db:5432/app
      REDIS_URL: redis://redis:6379
"""
        anchors = extract_compose("docker-compose.yml", text)
        keys = {a.key for a in anchors}
        assert "DATABASE_URL" in keys
        assert "REDIS_URL" in keys

    def test_environment_list(self) -> None:
        text = """\
version: "3"
services:
  web:
    environment:
      - DATABASE_URL=postgresql://db:5432/app
      - SECRET_KEY
"""
        anchors = extract_compose("docker-compose.yml", text)
        keys = {a.key for a in anchors}
        assert "DATABASE_URL" in keys
        assert "SECRET_KEY" in keys


class TestActions:
    def test_env_block(self) -> None:
        text = """\
on: push
env:
  CI: true
  NODE_ENV: production
jobs:
  build:
    runs-on: ubuntu-latest
    env:
      DATABASE_URL: test
    steps:
      - run: echo "hello"
"""
        anchors = extract_actions(".github/workflows/ci.yml", text)
        env_anchors = [a for a in anchors if a.kind is AnchorKind.ENV_DEF]
        keys = {a.key for a in env_anchors}
        assert "CI" in keys
        assert "NODE_ENV" in keys
        assert "DATABASE_URL" in keys


class TestK8s:
    def test_deployment_env(self) -> None:
        text = """\
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
        - name: app
          env:
            - name: DATABASE_URL
              value: postgresql://db:5432
            - name: REDIS_URL
              valueFrom:
                secretKeyRef:
                  name: redis
                  key: url
"""
        anchors = extract_k8s("deploy.yaml", text)
        keys = {a.key for a in anchors}
        assert "DATABASE_URL" in keys
        assert "REDIS_URL" in keys

    def test_configmap(self) -> None:
        text = """\
apiVersion: v1
kind: ConfigMap
data:
  APP_ENV: production
  LOG_LEVEL: info
"""
        anchors = extract_k8s("configmap.yaml", text)
        keys = {a.key for a in anchors}
        assert "APP_ENV" in keys
        assert "LOG_LEVEL" in keys


class TestScripts:
    def test_pyproject_scripts(self) -> None:
        text = """\
[project.scripts]
seamgraph = "seamgraph.cli:main"
myctl = "myapp.ctl:run"
"""
        anchors = extract_pyproject_scripts("pyproject.toml", text)
        keys = {a.key for a in anchors}
        assert "seamgraph" in keys
        assert "myctl" in keys

    def test_package_json_scripts(self) -> None:
        text = '{"scripts": {"build": "tsc", "test": "jest", "lint": "eslint ."}}'
        anchors = extract_package_json("package.json", text)
        keys = {a.key for a in anchors}
        assert keys == {"build", "test", "lint"}

    def test_makefile_targets(self) -> None:
        text = "build:\n\tgo build\n\ntest:\n\tgo test\n\n.PHONY: build test\n"
        anchors = extract_makefile("Makefile", text)
        keys = {a.key for a in anchors}
        assert "build" in keys
        assert "test" in keys


class TestDispatch:
    def test_env_file_dispatch(self) -> None:
        anchors = extract_config_file(".env", "KEY=val\n")
        assert len(anchors) == 1

    def test_dockerfile_dispatch(self) -> None:
        anchors = extract_config_file("Dockerfile", "ENV X=1\n")
        assert len(anchors) == 1

    def test_compose_dispatch(self) -> None:
        text = 'version: "3"\nservices:\n  web:\n    environment:\n      X: 1\n'
        anchors = extract_config_file("docker-compose.yml", text)
        assert len(anchors) >= 1

    def test_unknown_file(self) -> None:
        anchors = extract_config_file("readme.md", "hello")
        assert len(anchors) == 0
