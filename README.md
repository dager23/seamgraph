# seamgraph

A deterministic graph of your repo's **seams** — the string-typed references
connecting code to configs, templates, frontend calls, CI, and `.env` — served
to coding agents via MCP + CLI, with every edge graded by evidence.

## Why

Every existing code graph tool (Serena, repowise, qartez, aider's repo-map)
models **code↔code**: symbol references, import trees, call graphs. None models
the **string-typed seams** where real full-stack repos actually break:

| Seam kind | Example |
|---|---|
| **Route** | `fetch("/api/users/" + id)` ↔ `@app.get("/api/users/{user_id}")` |
| **Env var** | `.env` / `docker-compose` / `Dockerfile` / GitHub Actions ↔ `os.environ["X"]` / `process.env.X` |
| **Template** | `render_template("checkout.html")` ↔ `templates/checkout.html` |
| **URL name** | `{% url 'order-detail' %}` ↔ `path(..., name="order-detail")` |
| **Task** | `send_task("app.tasks.send_email")` ↔ `@shared_task(name="...")` |
| **Script** | CI `run: make build` ↔ `Makefile` target `build:` |
| **Setting** | `settings.STRIPE_API_KEY` ↔ `STRIPE_API_KEY = "..."` in settings.py |

Agents currently answer "what calls this route?" and "where is this env var
defined?" with grep-storms that burn tokens and miss context. `seamgraph`
indexes these seams once, deterministically, and serves the answer in one call.

## Installation

```bash
pip install seamgraph          # core (CLI)
pip install seamgraph[mcp]     # + MCP server
```

## Quick start

```bash
# Index your repo
seamgraph index

# Show the full seam map
seamgraph map

# Find seams for a specific reference
seamgraph for DATABASE_URL
seamgraph for "/api/users"

# Impact analysis: what seams cross a change boundary?
seamgraph impact src/routes.py frontend/api.js

# CI check: index + report warnings (exit code 1 if warnings)
seamgraph check

# Env variable cross-reference table
seamgraph env

# Route cross-reference table
seamgraph routes

# Start MCP server (for coding agents)
seamgraph serve
```

All commands support `--json` for machine-readable output and `--root <path>`
to specify the repository root.

## How it works

### Two-gate discipline

Every seam edge passes through two quality gates:

1. **Gate A (anchored extraction):** Both endpoints are extracted by
   framework-aware patterns — a FastAPI decorator, a `fetch()` literal, an
   `env:` key in a YAML manifest. Never bare string grep.

2. **Gate B (co-change corroboration):** Git history mining scores file pairs
   by how often they change together. Static seams with co-change support above
   threshold are upgraded from `anchored` to `corroborated`. File pairs with
   high co-change but no static edge are surfaced as `statistical` discoveries.

### Edge grades

| Grade | Meaning |
|---|---|
| `anchored` | Both endpoints extracted by framework-aware patterns |
| `corroborated` | Anchored + confirmed by git co-change history |
| `statistical` | No static edge, but files co-change suspiciously often |

### Extractors

| Source | What's extracted | Method |
|---|---|---|
| Python (`.py`) | Routes (FastAPI/Flask/Django), env reads, templates, URL names, Celery tasks, Django settings, HTTP client calls | `ast` module (stdlib, precise) |
| JS/TS (`.js`, `.ts`, `.jsx`, `.tsx`, `.vue`, `.svelte`) | `fetch`/axios calls, `process.env.X`, Express routes | Anchored regex (v0.1) |
| `.env*` | Variable definitions | Line regex |
| `Dockerfile` | `ENV`/`ARG` instructions | Line regex |
| `docker-compose*.yml` | `environment:` / `build.args:` | YAML parse |
| GitHub Actions (`.github/workflows/*.yml`) | `env:` blocks, `run:` script references | YAML parse |
| Kubernetes manifests | Container `env:`, ConfigMap/Secret data | YAML parse |
| `pyproject.toml` | `[project.scripts]` entry points | TOML parse |
| `package.json` | `scripts` entries | JSON parse |
| `Makefile` | Target definitions | Line regex |
| Templates (`.html`, `.jinja2`, etc.) | `{% url %}`, `{% include %}`, `{% extends %}`, file existence | Regex |

### MCP tools

When connected as an MCP server, `seamgraph serve` exposes:

| Tool | Description |
|---|---|
| `seam_map` | Full seam overview (start here) |
| `seams_for` | Find seams for a reference (replaces grep) |
| `impact` | Seams crossing a change boundary |
| `verify` | Check if a reference is connected |
| `env_table` | Env variable cross-reference |
| `route_table` | Route cross-reference |
| `check` | Re-index + report warnings |

## Configuration

Create `seamgraph.toml` or add `[tool.seamgraph]` to `pyproject.toml`:

```toml
# seamgraph.toml
exclude = ["vendor", "third_party"]
strip_url_prefixes = ["http://localhost:8000", "/backend"]
max_commits = 2000
max_files_per_commit = 40
corroborate_support = 3
corroborate_confidence = 0.25
discover_support = 5
discover_confidence = 0.5
```

## Limitations (stated honestly)

- **Dynamic URL construction:** Only parameter-segment normalization
  (`{id}` ≈ `${id}` ≈ `:id`), never value guessing. Unresolvable fetches are
  reported as `unmatched` with location.
- **Reverse-proxy/base-URL prefixes:** Configurable via `strip_url_prefixes`.
- **JS/TS extraction:** Anchored regex in v0.1 (honest about it; tree-sitter
  extra planned for v0.2).
- **Generic identifier layer:** OFF by default; only co-change-gated to avoid
  false positives.

## License

MIT
