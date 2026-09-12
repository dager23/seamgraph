# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] — 2026-09-12

First public release. Everything below is in that release; the list is grouped
rather than split across versions because nothing before this was published.

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

### Release-readiness pass

A pre-release verification pass exercised every documented command against
fresh repositories and fixed what it found:

- `--json` and `--root` are accepted on **both sides** of the subcommand.
  Previously only `seamgraph --json map` worked and `seamgraph map --json`
  failed with "unrecognized arguments", contradicting the README.
- `seamgraph routes` groups calls under the definition they actually matched.
  It previously grouped by literal anchor key, so every call to a
  parameterized route (`/api/users/7` against `/api/users/{id}`) was labelled
  unmatched despite having a seam, and contradicted `check` on the same repo.
- `seamgraph check` now reports **dangling references** that are rated
  informational instead of dropping them silently. A frontend call to a route
  with no handler — the case the tool exists to catch — was invisible whenever
  seamgraph could not vouch for the namespace. `--strict` promotes these to
  build failures.
- **The MCP server worked only against the `mcp` SDK version pinned in the
  development venv.** It was written against the low-level decorator API
  (`Server.list_tools()`), which the 2.x SDK removed, so a fresh
  `pip install "seamgraph[mcp]"` crashed on startup with `AttributeError`
  while the repo's own tests passed. It now uses the high-level server class
  and resolves it under either name - `FastMCP` on `mcp` 1.x, `MCPServer` on
  2.x - and is exercised against both.
- **The source distribution contained a 15 MB virtualenv.** Virtualenvs write
  their own `.gitignore`, so `git status` showed a clean tree while the build
  swept the directory in. The sdist is now an explicit allowlist.
- Dockerfile `ENV KEY=value` no longer extracts `value` as a second variable.
- `seamgraph verify <ref>` added as a CLI command (it already existed in the
  API and over MCP), exiting non-zero when a reference is not connected.
- The first `index` on a repo no longer indexes twice and no longer reports
  "(0 changed)".
- Long finding lists are truncated in human output with a pointer to `--json`.
- `impact` output is ASCII-only, so it does not mojibake on legacy consoles.
- Release workflow moved to its own file: a tag push does not match a
  `branches:` filter, so the previous tag-gated release job could never fire.
- CI now builds the wheel *and* the sdist on every push and installs each into
  a clean virtualenv, running the CLI and the MCP server from the installed
  package.
