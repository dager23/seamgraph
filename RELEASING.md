# Releasing

Publishing uses [PyPI Trusted Publishing][tp] (OIDC). No API token is stored in
the repository, in GitHub secrets, or anywhere else — PyPI verifies the release
came from this repository's workflow and mints a short-lived credential for
that one upload.

[tp]: https://docs.pypi.org/trusted-publishers/

## One-time setup on PyPI

Do this once per index, in the PyPI web UI, before the first release.

For a project that does not exist yet, use **Your account → Publishing → Add a
pending publisher**. For an existing project, use **Manage project → Publishing**.

| Field | Value |
|---|---|
| PyPI project name | `seamgraph` |
| Owner | `dager23` |
| Repository name | `seamgraph` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

Repeat on [test.pypi.org](https://test.pypi.org) with environment name
`testpypi` if you want to rehearse.

Then create the matching environments in GitHub under
**Settings → Environments**: `pypi`, and `testpypi` if used. They can be empty;
they exist so the workflow's `environment:` key resolves and so you can add
required reviewers later.

## Rehearsing

```
Actions → Release → Run workflow → target: testpypi
```

Then install what was actually published and exercise it:

```bash
python -m venv /tmp/rehearsal
/tmp/rehearsal/bin/pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  seamgraph
/tmp/rehearsal/bin/seamgraph --root /path/to/some/repo check
```

The extra index is needed because TestPyPI does not mirror dependencies.

If TestPyPI is unavailable, the equivalent local check is to install the built
**sdist** (not just the wheel) into a clean virtualenv and run the CLI and the
MCP server from it — that catches the same class of "works in the checkout,
broken once packaged" bug. CI does exactly this on every push, in the
`package` job.

## Releasing for real

```bash
# 1. version + changelog
#    bump `version` in pyproject.toml and add the CHANGELOG entry
git commit -am "Release vX.Y.Z"

# 2. tag and push — the tag is what triggers publishing
git tag vX.Y.Z
git push origin main --tags
```

The `Release` workflow builds the wheel and sdist, runs `twine check`, and
publishes to PyPI.

A version number can never be reused on PyPI, even after deleting a release.
Get the rehearsal right rather than relying on being able to retry.

## Checklist

- [ ] `python -m pytest` green
- [ ] `python -m ruff check src tests && python -m ruff format --check src tests`
- [ ] `python -m mypy`
- [ ] `python -m seamgraph.cli check` (seamgraph on its own repo)
- [ ] `python tests/correctness_harness.py` if extraction or matching changed
- [ ] version bumped in `pyproject.toml`
- [ ] `CHANGELOG.md` entry added
