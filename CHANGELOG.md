# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] — 2026-07-12

### Added

- **Core extractors**: Python (ast-based), JS/TS (anchored regex), config files
  (.env, Dockerfile, docker-compose, GitHub Actions, Kubernetes manifests,
  pyproject.toml, package.json, Makefile), Jinja/Django templates.
- **Route normalization**: Cross-framework path matching (FastAPI `{id}` ≈
  Flask `<id>` ≈ Express `:id` ≈ JS `${id}`), prefix resolution for
  `include_router`/`register_blueprint`.
- **Kind-specific matchers**: env chains, route linking, template refs,
  URL names, Celery tasks, scripts, Django settings.
- **Co-change mining**: `git log` file-pair co-occurrence for corroboration
  and statistical discovery.
- **SQLite graph store**: Content-hash incremental indexing at
  `.seamgraph/graph.db`.
- **CLI**: `seamgraph index|map|for|impact|check|env|routes|serve` with
  `--json` output.
- **MCP server**: 7 tools (`seam_map`, `seams_for`, `impact`, `verify`,
  `env_table`, `route_table`, `check`) via stdio.
- **Edge grading**: `anchored` → `corroborated`; separate cross-artifact
  co-change *discoveries* (never asserted as edges).
- **Orphan detection** with evidence-gated severities: unmatched route calls
  and missing templates warn only when the definition side is visible in the
  repo; env reads without in-repo definitions are informational.
