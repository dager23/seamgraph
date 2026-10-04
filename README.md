# seamgraph

[![CI](https://github.com/dager23/seamgraph/actions/workflows/ci.yml/badge.svg)](https://github.com/dager23/seamgraph/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/seamgraph.svg)](https://pypi.org/project/seamgraph/)
[![Python versions](https://img.shields.io/pypi/pyversions/seamgraph.svg)](https://pypi.org/project/seamgraph/)
[![License](https://img.shields.io/pypi/l/seamgraph.svg)](LICENSE)

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

## Measured results (20 real OSS repos)

Run against 20 popular full-stack repositories — saleor, redash, label-studio,
cal.com, dify, lobe-chat, twenty, and more. [BENCHMARKS.md](BENCHMARKS.md) has
the per-repo table and methodology; every number there is produced by
`python tests/benchmark_real_repos.py`, not written by hand.

- **118,520 files → 25,690 anchors → 16,048 seams** across 7 seam kinds;
  242 of those seams are additionally corroborated by git co-change history.
- **Token cost of "where is this referenced?"** — one `seams_for` response
  against the grep-then-read-every-match workflow, counted byte for byte by
  `scripts/measure_token_story.py`: a median of **14.8x** less context on
  redash, **98.3x** on saleor, **12.8x** on papermark.
- **84 warnings across all 20 repos**, and 11 of the 20 report none. Sampled
  warnings were checked by hand against the source: they are real, such as
  papermark's frontend calling `/api/teams/{id}/billing/manage`, which no
  handler in that repo serves.
- A further **1,632 findings are informational** rather than warnings, and
  two repos account for more than half of them. Those are codebases whose
  route definitions seamgraph does not parse — infisical registers routes
  through Fastify, and much of open-webui's API is reached from Svelte — so
  it reports the dangling references but will not fail a build over them.
  That split is the point: seamgraph separates "this is broken" from "I
  cannot see the other side of this".

**Correctness, not just volume.** `tests/correctness_harness.py` seeds
scenarios into each of those repositories from facts taken out of the
repository itself — reading an environment variable it really defines, calling
a route it really defines, and separately reading a variable and calling a
route that provably do not exist anywhere in it. seamgraph must link the first
two and refuse to invent the second two. All 20 repos pass, and every CLI
command runs against each of them without crashing or emitting malformed JSON.

## Installation

```bash
pip install seamgraph            # core (CLI)
pip install "seamgraph[mcp]"     # + MCP server for coding agents
```

Requires Python 3.10+. `git` is optional: without it, file discovery falls back
to a filtered walk and co-change grading is skipped (all seams stay `anchored`).

### Connect to Claude Code (or any MCP client)

```bash
claude mcp add seamgraph -- python -m seamgraph.cli --root /path/to/repo serve
```

Works with both generations of the Python MCP SDK (`mcp` 1.x and 2.x); the
server indexes the repo on startup so the first tool call has a real graph.

## Quick start

```bash
# Index your repo (--full forces a re-index of every file)
seamgraph index

# Show the full seam map (--kind env|route|template|urlname|task|script|setting)
seamgraph map
seamgraph map --kind route

# Find seams for a specific reference
seamgraph for DATABASE_URL
seamgraph for "/api/users"

# Is one reference connected on both sides? (exit code 1 if not)
seamgraph verify DATABASE_URL

# Impact analysis: what seams cross a change boundary?
seamgraph impact src/routes.py frontend/api.js

# CI check: index + report findings (exit code 1 if warnings)
seamgraph check
seamgraph check --strict   # also fail on informational dangling references

# Env variable cross-reference table
seamgraph env

# Route cross-reference table
seamgraph routes

# Start MCP server (for coding agents)
seamgraph serve
```

`--json` (machine-readable output) and `--root <path>` (repository root) work
on every command, and on either side of the subcommand — `seamgraph --json map`
and `seamgraph map --json` are equivalent.

> **Git Bash on Windows:** MSYS rewrites arguments that look like absolute
> paths, so `seamgraph for "/api/users"` arrives as `C:/Git/api/users`. Use
> PowerShell/cmd, or set `MSYS_NO_PATHCONV=1` for that command.

## How it works

### Two-gate discipline

Every seam edge passes through two quality gates:

1. **Gate A (anchored extraction):** Both endpoints are extracted by
   framework-aware patterns — a FastAPI decorator, a `fetch()` literal, an
   `env:` key in a YAML manifest. Never bare string grep.

2. **Gate B (co-change corroboration):** Git history mining scores file pairs
   by how often they change together (directional confidence:
   `support / min(changes_a, changes_b)`, as in the change-coupling
   literature). Static seams with co-change support above threshold are
   upgraded from `anchored` to `corroborated`.

### Edge grades

| Grade | Meaning |
|---|---|
| `anchored` | Both endpoints extracted by framework-aware patterns |
| `corroborated` | Anchored + confirmed by git co-change history |

### Finding severities

`seamgraph check` separates what it is confident about from what it is not:

| Severity | Meaning | Fails the build? |
|---|---|---|
| **warning** | A reference resolves to nothing, *and* the repo visibly serves that namespace — so the target is genuinely missing | yes |
| **informational** | A reference resolves to nothing, but seamgraph never extracted the definition side of that namespace, so it cannot tell a dead reference from a framework it does not parse | only with `--strict` |

This is why a dead `fetch("/api/does-not-exist")` is a warning in a repo whose
routes seamgraph fully understands, and informational in one where it found no
routes in that namespace at all. Both are always *reported* — the severity only
decides whether CI fails. Unused definitions are never findings: an env var
defined and not read, or a handler nobody calls, is not a defect.

Separately from graded seams, **discoveries** are *cross-artifact* file pairs
(e.g. a `.py` and a `.ts` file) that co-change suspiciously often but have no
static seam we can see — surfaced by `seamgraph map` as leads, never asserted
as edges. Same-class pairs (two Python files) are deliberately excluded: that
is ordinary import coupling, already visible to LSP and code-graph tools.

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
- **No generic string matching:** seamgraph never links two files just because
  they share an identifier. Everything is either pattern-anchored on both ends
  or reported as a statistical *discovery* with its co-change evidence attached.
- **Env reads with no in-repo definition are informational**, never warnings —
  variables legitimately come from the deployment environment.

## License

MIT
