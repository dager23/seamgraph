"""Tests for the route normalization and matching module."""

from __future__ import annotations

from seamgraph.routes import RoutePattern, match_route, normalize_backend, normalize_call


class TestNormalizeBackend:
    def test_fastapi_params(self) -> None:
        p = normalize_backend("/api/users/{user_id}/posts", "fastapi")
        assert p.segments == ("api", "users", "*", "posts")

    def test_flask_params(self) -> None:
        p = normalize_backend("/users/<int:id>", "flask")
        assert p.segments == ("users", "*")

    def test_django_params(self) -> None:
        p = normalize_backend("/orders/<int:pk>/", "django")
        assert p.segments == ("orders", "*")

    def test_express_params(self) -> None:
        p = normalize_backend("/api/users/:id", "express")
        assert p.segments == ("api", "users", "*")

    def test_no_params(self) -> None:
        p = normalize_backend("/health", "fastapi")
        assert p.segments == ("health",)


class TestNormalizeCall:
    def test_simple_path(self) -> None:
        p = normalize_call("/api/users")
        assert p is not None
        assert p.segments == ("api", "users")

    def test_template_literal_hole(self) -> None:
        p = normalize_call("/api/users/${userId}")
        assert p is not None
        assert p.segments == ("api", "users", "*")

    def test_open_tail(self) -> None:
        p = normalize_call("/api/users/", open_tail=True)
        assert p is not None
        assert p.segments == ("api", "users", "**")

    def test_strip_prefix(self) -> None:
        p = normalize_call(
            "http://localhost:8000/api/users", strip_prefixes=("http://localhost:8000",)
        )
        assert p is not None
        assert p.segments == ("api", "users")

    def test_reject_mailto(self) -> None:
        p = normalize_call("mailto:user@example.com")
        assert p is None

    def test_reject_data_url(self) -> None:
        p = normalize_call("data:text/plain;base64,abc")
        assert p is None


class TestMatchRoute:
    def test_exact_match(self) -> None:
        call = RoutePattern(("api", "users"))
        defn = RoutePattern(("api", "users"))
        score = match_route(call, defn)
        assert score is not None
        assert score >= 1

    def test_param_match(self) -> None:
        call = RoutePattern(("api", "users", "*"))
        defn = RoutePattern(("api", "users", "*"))
        score = match_route(call, defn)
        assert score is not None

    def test_no_match_different_path(self) -> None:
        call = RoutePattern(("api", "users"))
        defn = RoutePattern(("api", "orders"))
        score = match_route(call, defn)
        assert score is None

    def test_param_wildcard(self) -> None:
        call = RoutePattern(("api", "users", "*"))
        defn = RoutePattern(("api", "users", "*"))
        score = match_route(call, defn)
        assert score is not None

    def test_length_mismatch(self) -> None:
        call = RoutePattern(("api", "users"))
        defn = RoutePattern(("api", "users", "*"))
        score = match_route(call, defn)
        assert score is None

    def test_tail_match(self) -> None:
        call = RoutePattern(("api", "users", "**"))
        defn = RoutePattern(("api", "users", "*"))
        score = match_route(call, defn)
        assert score is not None

    def test_prefix_match(self) -> None:
        call = RoutePattern(("api", "v1", "users"))
        defn = RoutePattern(("users",))
        score = match_route(call, defn, allow_def_prefix=True)
        assert score is not None

    def test_trivial_only_fails(self) -> None:
        # Only single-char segments → no non-trivial literal overlap
        call = RoutePattern(("*",))
        defn = RoutePattern(("*",))
        score = match_route(call, defn)
        assert score is None


class TestLeadingHole:
    def test_leading_hole_is_base_url(self) -> None:
        p = normalize_call("${x}/api/users")
        assert p is not None and p.segments == ("api", "users")

    def test_mid_path_hole_kept(self) -> None:
        p = normalize_call("/api/${x}/users")
        assert p is not None and p.segments == ("api", "*", "users")


class TestDefCatchAll:
    def test_def_tail_matches_deep_call(self) -> None:
        call = RoutePattern(("api", "v2", "document", "*"))
        defn = RoutePattern(("api", "v2", "**"))
        assert match_route(call, defn) == 2

    def test_def_tail_matches_zero_segments(self) -> None:
        # optional catch-all [[...path]] also serves the bare prefix
        call = RoutePattern(("api", "auth"))
        defn = RoutePattern(("api", "auth", "**"))
        assert match_route(call, defn) == 2

    def test_call_tail_still_requires_one_segment(self) -> None:
        call = RoutePattern(("api", "users", "**"))
        defn = RoutePattern(("api", "users"))
        assert match_route(call, defn) is None
