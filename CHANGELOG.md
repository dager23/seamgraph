# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] — 2026-07-13

### Added

- **Core extractors**: Python (ast-based), JS/TS (anchored regex, including
  `const {X} = process.env` destructuring), config files (.env, Dockerfile,
  docker-compose, GitHub Actions, Kubernetes manifests, pyproject.toml,
  package.json, Makefile), Jinja/Django templates (HTML-family files anywhere
  are render-target candidates, not just `templates/` directories).
- **Route extraction across registration styles**: decorator routes
  (FastAPI/Flask, including routers/blueprints imported from other modules),
  Django `path()`, Flask-RESTful `add_resource`, DRF `router.register`,
  Express-style JS handlers, and **file-convention routes** (Next.js
  `pages/api/**` + app-router `route.ts`, SvelteKit `+server.ts`, Nuxt
  `server/api/**`).
- **Route normalization**: Cross-framework path matching (FastAPI `{id}` ≈
  Flask `<id>` ≈ Express `:id` ≈ JS `${id}` ≈ Next.js `[id]`), prefix
  resolution for `include_router`/`register_blueprint`, method-aware
  matching, and a fan-out cap (a concat call matching more than 8 handlers
  is reported as `route-call-unspecific` instead of asserting seams).
  Catch-all definitions (`[...path]` routes, `app.use("/x", sub)` /
  hono `app.route("/x", sub)` mounts) match everything below their prefix;
  a leading template-literal hole (`` `${API_URL}/api/users` ``) is treated
  as a base-URL variable, not a path segment.
- **Kind-specific matchers**: env chains, route linking, template refs,
  URL names (Django namespaces and Flask `blueprint.view` qualifiers),
  Celery tasks, scripts (matched within the same script type only),
  Django settings.
- **Co-change mining**: `git log` file-pair co-occurrence with *directional*
  confidence (`support / min(changes)`, per the change-coupling literature);
  corroborates anchored seams and surfaces cross-artifact-only statistical
  discoveries.
- **SQLite graph store**: Content-hash incremental indexing at
  `.seamgraph/graph.db`; query commands auto-index on first use.
- **CLI**: `seamgraph index|map|for|impact|check|env|routes|serve` with
  `--json` output.
- **MCP server**: 7 tools (`seam_map`, `seams_for`, `impact`, `verify`,
  `env_table`, `route_table`, `check`) via stdio; indexes at startup.
- **Edge grading**: `anchored` → `corroborated`; separate cross-artifact
  co-change *discoveries* (never asserted as edges).
- **Orphan detection** with evidence-gated severities: unmatched route calls
  warn only when the repo defines routes in the same path family; missing
  templates warn only when template files are visible; env reads without
  in-repo definitions are informational.
- **Benchmark suite** (`tests/benchmark_real_repos.py`) against 20 OSS
  full-stack repos and a deterministic token-cost comparison
  (`scripts/measure_token_story.py`).
