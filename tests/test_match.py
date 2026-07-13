"""Tests for the kind-specific matchers."""

from __future__ import annotations

from seamgraph.match import (
    match_all,
    match_env,
    match_routes,
    match_scripts,
    match_settings,
    match_tasks,
    match_templates,
    match_urlnames,
)
from seamgraph.models import Anchor, AnchorKind, SeamKind


def _anchor(kind: AnchorKind, key: str, path: str = "a.py", line: int = 1, **extra: str) -> Anchor:
    return Anchor(kind, key, key, path, line, "test", extra)


class TestMatchEnv:
    def test_basic_match(self) -> None:
        anchors = [
            _anchor(AnchorKind.ENV_DEF, "DATABASE_URL", ".env"),
            _anchor(AnchorKind.ENV_READ, "DATABASE_URL", "app.py"),
        ]
        seams, orphans = match_env(anchors)
        assert len(seams) == 1
        assert seams[0].kind is SeamKind.ENV
        assert seams[0].key == "DATABASE_URL"
        assert len(orphans) == 0

    def test_undefined_read(self) -> None:
        anchors = [
            _anchor(AnchorKind.ENV_READ, "MISSING_VAR", "app.py"),
        ]
        seams, orphans = match_env(anchors)
        assert len(seams) == 0
        assert len(orphans) == 1
        assert orphans[0].problem == "env-use-unmatched"

    def test_unused_def(self) -> None:
        anchors = [
            _anchor(AnchorKind.ENV_DEF, "UNUSED_VAR", ".env"),
        ]
        seams, orphans = match_env(anchors)
        assert len(seams) == 0
        assert len(orphans) == 1
        assert orphans[0].problem == "env-def-unused"


class TestMatchRoutes:
    def test_basic_route_match(self) -> None:
        anchors = [
            _anchor(AnchorKind.ROUTE_CALL, "/api/users", "frontend.js", method="GET"),
            _anchor(AnchorKind.ROUTE_DEF, "/api/users", "main.py", method="GET"),
        ]
        seams, _orphans = match_routes(anchors)
        assert len(seams) == 1
        assert seams[0].kind is SeamKind.ROUTE

    def test_param_route_match(self) -> None:
        anchors = [
            _anchor(AnchorKind.ROUTE_CALL, "/api/users/*", "frontend.js"),
            _anchor(AnchorKind.ROUTE_DEF, "/api/users/*", "main.py"),
        ]
        seams, _orphans = match_routes(anchors)
        assert len(seams) == 1

    def test_unmatched_call(self) -> None:
        anchors = [
            _anchor(AnchorKind.ROUTE_CALL, "/api/settings", "frontend.js"),
        ]
        seams, orphans = match_routes(anchors)
        assert len(seams) == 0
        assert len(orphans) == 1
        assert orphans[0].problem == "route-call-unmatched"


class TestMatchTemplates:
    def test_exact_match(self) -> None:
        anchors = [
            _anchor(AnchorKind.TEMPLATE_REF, "shop/order.html", "views.py"),
            _anchor(AnchorKind.TEMPLATE_FILE, "shop/order.html", "templates/shop/order.html"),
        ]
        seams, _orphans = match_templates(anchors)
        assert len(seams) == 1

    def test_suffix_match(self) -> None:
        anchors = [
            _anchor(AnchorKind.TEMPLATE_REF, "order.html", "views.py"),
            _anchor(AnchorKind.TEMPLATE_FILE, "shop/order.html", "templates/shop/order.html"),
        ]
        seams, _orphans = match_templates(anchors)
        # Should match via basename
        assert len(seams) == 1

    def test_missing_template(self) -> None:
        anchors = [
            _anchor(AnchorKind.TEMPLATE_REF, "nonexistent.html", "views.py"),
        ]
        seams, orphans = match_templates(anchors)
        assert len(seams) == 0
        assert len(orphans) == 1
        assert orphans[0].problem == "template-ref-missing"


class TestMatchUrlnames:
    def test_basic_match(self) -> None:
        anchors = [
            _anchor(AnchorKind.URLNAME_REF, "order-detail", "views.py"),
            _anchor(AnchorKind.URLNAME_DEF, "order-detail", "urls.py"),
        ]
        seams, _orphans = match_urlnames(anchors)
        assert len(seams) == 1
        assert seams[0].kind is SeamKind.URLNAME

    def test_undefined_urlname(self) -> None:
        anchors = [
            _anchor(AnchorKind.URLNAME_REF, "missing-name", "views.py"),
        ]
        _seams, orphans = match_urlnames(anchors)
        assert len(orphans) == 1


class TestMatchTasks:
    def test_exact_match(self) -> None:
        anchors = [
            _anchor(AnchorKind.TASK_CALL, "app.tasks.send_email", "worker.py"),
            _anchor(AnchorKind.TASK_DEF, "app.tasks.send_email", "tasks.py"),
        ]
        seams, _orphans = match_tasks(anchors)
        assert len(seams) == 1
        assert seams[0].kind is SeamKind.TASK

    def test_suffix_match(self) -> None:
        anchors = [
            _anchor(AnchorKind.TASK_CALL, "app.tasks.send_email", "worker.py"),
            _anchor(AnchorKind.TASK_DEF, "myproject.app.tasks.send_email", "tasks.py"),
        ]
        seams, _orphans = match_tasks(anchors)
        assert len(seams) == 1


class TestMatchScripts:
    def test_basic_match(self) -> None:
        anchors = [
            _anchor(AnchorKind.SCRIPT_USE, "build", ".github/workflows/ci.yml"),
            _anchor(AnchorKind.SCRIPT_DEF, "build", "Makefile"),
        ]
        seams, _orphans = match_scripts(anchors)
        assert len(seams) == 1
        assert seams[0].kind is SeamKind.SCRIPT


class TestMatchSettings:
    def test_basic_match(self) -> None:
        anchors = [
            _anchor(AnchorKind.SETTING_READ, "STRIPE_API_KEY", "views.py"),
            _anchor(AnchorKind.SETTING_DEF, "STRIPE_API_KEY", "settings.py"),
        ]
        seams, _orphans = match_settings(anchors)
        assert len(seams) == 1
        assert seams[0].kind is SeamKind.SETTING


class TestMatchAll:
    def test_combined(self) -> None:
        anchors = [
            _anchor(AnchorKind.ENV_DEF, "DB_URL", ".env"),
            _anchor(AnchorKind.ENV_READ, "DB_URL", "app.py"),
            _anchor(AnchorKind.ROUTE_CALL, "/api/users", "frontend.js"),
            _anchor(AnchorKind.ROUTE_DEF, "/api/users", "main.py"),
        ]
        seams, _orphans = match_all(anchors)
        assert len(seams) == 2
        kinds = {s.kind for s in seams}
        assert SeamKind.ENV in kinds
        assert SeamKind.ROUTE in kinds


class TestSeamSidesConsistency:
    def test_seam_sides_covers_every_kind(self) -> None:
        # SEAM_SIDES is the documented pairing contract; every SeamKind must
        # have exactly one (use, definition) AnchorKind pair
        from seamgraph.models import SEAM_SIDES, AnchorKind, SeamKind

        assert set(SEAM_SIDES) == set(SeamKind)
        used = [k for pair in SEAM_SIDES.values() for k in pair]
        assert len(used) == len(set(used))  # no anchor kind serves two seams
        assert set(used) == set(AnchorKind)  # every anchor kind participates
