"""SQLite-backed seam graph store with content-hash incremental indexing.

The graph is stored at ``<repo>/.seamgraph/graph.db``. Indexing is incremental:
only files whose content hash has changed since the last index are re-extracted.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .cochange import corroborate_seams, discover_statistical, mine_cochange
from .config import Config, load_config
from .extract.configs import extract_config_file
from .extract.js_ts import extract_js_ts
from .extract.python_code import PyFileFacts, extract_python, resolve_routes
from .extract.templates import extract_template_file, extract_template_refs
from .fswalk import list_files, read_text
from .match import match_all
from .models import Anchor, AnchorKind, Discovery, Seam

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS file_hash (
    path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS anchors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    raw TEXT NOT NULL,
    path TEXT NOT NULL,
    line INTEGER NOT NULL,
    detail TEXT NOT NULL,
    extra TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS seams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    use_anchor_id INTEGER NOT NULL REFERENCES anchors(id),
    def_anchor_id INTEGER NOT NULL REFERENCES anchors(id),
    grade TEXT NOT NULL DEFAULT 'anchored',
    cochange_support INTEGER NOT NULL DEFAULT 0,
    cochange_confidence REAL NOT NULL DEFAULT 0.0,
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS orphans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anchor_id INTEGER NOT NULL REFERENCES anchors(id),
    problem TEXT NOT NULL,
    severity TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discoveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path_a TEXT NOT NULL,
    path_b TEXT NOT NULL,
    support INTEGER NOT NULL,
    confidence REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_anchors_kind ON anchors(kind);
CREATE INDEX IF NOT EXISTS idx_anchors_key ON anchors(key);
CREATE INDEX IF NOT EXISTS idx_anchors_path ON anchors(path);
CREATE INDEX IF NOT EXISTS idx_seams_kind ON seams(kind);
CREATE INDEX IF NOT EXISTS idx_seams_key ON seams(key);
"""


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _anchor_to_row(a: Anchor) -> tuple[str, str, str, str, int, str, str]:
    return (a.kind.value, a.key, a.raw, a.path, a.line, a.detail, json.dumps(a.extra))


def _row_to_anchor(row: sqlite3.Row) -> Anchor:
    return Anchor(
        kind=AnchorKind(row["kind"]),
        key=row["key"],
        raw=row["raw"],
        path=row["path"],
        line=row["line"],
        detail=row["detail"],
        extra=json.loads(row["extra"]),
    )


class SeamGraph:
    """The main indexing and query object."""

    def __init__(self, root: Path, config: Config | None = None) -> None:
        self.root = root.resolve()
        self.config = config or load_config(self.root)
        self.db_dir = self.root / ".seamgraph"
        self.db_path = self.db_dir / "graph.db"

    def _connect(self) -> sqlite3.Connection:
        self.db_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        return conn

    def index(self, full: bool = False) -> dict[str, Any]:
        """Index the repository. Returns stats about what was processed.

        ``full=True`` forces re-indexing of all files (ignores hashes).
        """
        conn = self._connect()
        stats: dict[str, Any] = {
            "files_scanned": 0, "files_changed": 0,
            "anchors": 0, "seams": 0,
            "orphans": 0, "discoveries": 0,
        }

        files = list_files(self.root, exclude=self.config.exclude)
        stats["files_scanned"] = len(files)

        # Load existing hashes
        old_hashes: dict[str, str] = {}
        if not full:
            for row in conn.execute("SELECT path, content_hash FROM file_hash"):
                old_hashes[row["path"]] = row["content_hash"]

        # Determine which files changed
        new_hashes: dict[str, str] = {}
        changed_files: set[str] = set()
        file_texts: dict[str, str] = {}

        for rel in files:
            text = read_text(self.root, rel)
            if text is None:
                continue
            h = _content_hash(text)
            new_hashes[rel] = h
            file_texts[rel] = text
            if full or old_hashes.get(rel) != h:
                changed_files.add(rel)

        # Detect removed files
        removed = set(old_hashes) - set(new_hashes)
        if removed:
            changed_files |= removed

        stats["files_changed"] = len(changed_files)

        if not changed_files and not full:
            conn.close()
            return stats

        # Full re-extract (simpler and correct; incremental per-file is a v0.2 optimization)
        all_anchors: list[Anchor] = []
        py_facts: dict[str, PyFileFacts] = {}

        for rel, text in sorted(file_texts.items()):
            if rel.endswith(".py"):
                # anchors are NOT collected here: resolve_routes() returns every
                # Python anchor (with routes/auto-task names resolved cross-file)
                py_facts[rel] = extract_python(rel, text)
            else:
                prefixes = self.config.strip_url_prefixes
                all_anchors.extend(
                    extract_js_ts(rel, text, strip_prefixes=prefixes)
                )
                all_anchors.extend(extract_config_file(rel, text))
                all_anchors.extend(extract_template_file(rel))
                all_anchors.extend(extract_template_refs(rel, text))

        # Resolve cross-file Python routes and auto-named tasks
        all_anchors.extend(resolve_routes(py_facts))

        stats["anchors"] = len(all_anchors)

        # Match anchors into seams
        seams, orphans = match_all(all_anchors, strip_prefixes=self.config.strip_url_prefixes)

        # Co-change mining and corroboration
        anchor_paths = {a.path for a in all_anchors}
        cochange = mine_cochange(
            self.root,
            max_commits=self.config.max_commits,
            max_files_per_commit=self.config.max_files_per_commit,
            paths=anchor_paths,
        )

        seam_file_pairs: set[tuple[str, str]] = set()
        for s in seams:
            a, b = s.use.path, s.definition.path
            if a != b:
                seam_file_pairs.add((min(a, b), max(a, b)))

        corroborated = corroborate_seams(
            seam_file_pairs,
            cochange,
            min_support=self.config.corroborate_support,
            min_confidence=self.config.corroborate_confidence,
        )

        # Upgrade seam grades
        graded_seams: list[Seam] = []
        for s in seams:
            a, b = s.use.path, s.definition.path
            pair = (min(a, b), max(a, b))
            cc = corroborated.get(pair)
            if cc:
                graded_seams.append(
                    Seam(
                        s.kind, s.key, s.use, s.definition,
                        grade="corroborated",
                        cochange_support=cc.support,
                        cochange_confidence=cc.confidence,
                        note=s.note,
                    )
                )
            else:
                graded_seams.append(s)

        # Discover statistical-only pairs
        statistical = discover_statistical(
            cochange,
            seam_file_pairs,
            min_support=self.config.discover_support,
            min_confidence=self.config.discover_confidence,
        )
        discoveries = [
            Discovery(cc.path_a, cc.path_b, cc.support, cc.confidence)
            for cc in statistical
        ]

        stats["seams"] = len(graded_seams)
        stats["orphans"] = len(orphans)
        stats["discoveries"] = len(discoveries)

        # Write to DB
        conn.execute("DELETE FROM discoveries")
        conn.execute("DELETE FROM orphans")
        conn.execute("DELETE FROM seams")
        conn.execute("DELETE FROM anchors")
        conn.execute("DELETE FROM file_hash")

        for rel, h in sorted(new_hashes.items()):
            conn.execute("INSERT INTO file_hash (path, content_hash) VALUES (?, ?)", (rel, h))

        anchor_id_map: dict[int, int] = {}
        for anchor in all_anchors:
            sql = (
                "INSERT INTO anchors"
                " (kind, key, raw, path, line, detail, extra)"
                " VALUES (?,?,?,?,?,?,?)"
            )
            cur = conn.execute(sql, _anchor_to_row(anchor))
            anchor_id_map[id(anchor)] = cur.lastrowid or 0

        for s in graded_seams:
            use_id = anchor_id_map.get(id(s.use), 0)
            def_id = anchor_id_map.get(id(s.definition), 0)
            sql = (
                "INSERT INTO seams"
                " (kind, key, use_anchor_id, def_anchor_id,"
                " grade, cochange_support, cochange_confidence,"
                " note) VALUES (?,?,?,?,?,?,?,?)"
            )
            conn.execute(
                sql,
                (
                    s.kind.value, s.key, use_id, def_id,
                    s.grade, s.cochange_support,
                    s.cochange_confidence, s.note,
                ),
            )

        for o in orphans:
            a_id = anchor_id_map.get(id(o.anchor), 0)
            conn.execute(
                "INSERT INTO orphans (anchor_id, problem, severity) VALUES (?,?,?)",
                (a_id, o.problem, o.severity),
            )

        for d in discoveries:
            conn.execute(
                "INSERT INTO discoveries (path_a, path_b, support, confidence) VALUES (?,?,?,?)",
                (d.path_a, d.path_b, d.support, d.confidence),
            )

        conn.commit()
        conn.close()
        return stats

    # -- Query helpers (used by api.py) ------------------------------------

    def query_seams(
        self,
        kind: str | None = None,
        key: str | None = None,
        path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query seams, optionally filtered by kind, key substring, or file path."""
        conn = self._connect()
        query = """
            SELECT s.kind, s.key, s.grade, s.cochange_support, s.cochange_confidence, s.note,
                   u.kind as use_kind, u.key as use_key, u.raw as use_raw,
                   u.path as use_path, u.line as use_line, u.detail as use_detail,
                   d.kind as def_kind, d.key as def_key, d.raw as def_raw,
                   d.path as def_path, d.line as def_line, d.detail as def_detail
            FROM seams s
            JOIN anchors u ON s.use_anchor_id = u.id
            JOIN anchors d ON s.def_anchor_id = d.id
            WHERE 1=1
        """
        params: list[Any] = []
        if kind:
            query += " AND s.kind = ?"
            params.append(kind)
        if key:
            query += " AND s.key LIKE ?"
            params.append(f"%{key}%")
        if path:
            query += " AND (u.path = ? OR d.path = ?)"
            params.extend([path, path])
        query += " ORDER BY s.kind, s.key"

        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def query_orphans(
        self,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        query = """
            SELECT o.problem, o.severity,
                   a.kind, a.key, a.raw, a.path, a.line, a.detail
            FROM orphans o
            JOIN anchors a ON o.anchor_id = a.id
            WHERE 1=1
        """
        params: list[Any] = []
        if severity:
            query += " AND o.severity = ?"
            params.append(severity)
        query += " ORDER BY o.severity DESC, a.path, a.line"

        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def query_discoveries(self) -> list[dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT path_a, path_b, support, confidence FROM discoveries ORDER BY confidence DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def query_anchors(
        self,
        kind: str | None = None,
        path: str | None = None,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        query = "SELECT kind, key, raw, path, line, detail, extra FROM anchors WHERE 1=1"
        params: list[Any] = []
        if kind:
            query += " AND kind = ?"
            params.append(kind)
        if path:
            query += " AND path = ?"
            params.append(path)
        query += " ORDER BY path, line"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def query_env_table(self) -> list[dict[str, Any]]:
        """Build an env-variable table: name → [{source, path, line}]."""
        conn = self._connect()
        sql = (
            "SELECT kind, key, path, line, detail, extra"
            " FROM anchors WHERE kind IN (?, ?)"
            " ORDER BY key, path"
        )
        rows = conn.execute(
            sql,
            (AnchorKind.ENV_DEF.value, AnchorKind.ENV_READ.value),
        ).fetchall()
        conn.close()

        from collections import defaultdict
        table: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
            lambda: {"definitions": [], "reads": []}
        )
        for r in rows:
            entry = {"path": r["path"], "line": r["line"], "detail": r["detail"]}
            extra = json.loads(r["extra"])
            if extra.get("source"):
                entry["source"] = extra["source"]
            side = "definitions" if r["kind"] == AnchorKind.ENV_DEF.value else "reads"
            table[r["key"]][side].append(entry)

        return [{"name": k, **v} for k, v in sorted(table.items())]

    def query_route_table(self) -> list[dict[str, Any]]:
        """Build a route table: path → [{side, method, file, line}]."""
        conn = self._connect()
        sql = (
            "SELECT kind, key, raw, path, line, detail, extra"
            " FROM anchors WHERE kind IN (?, ?)"
            " ORDER BY key, path"
        )
        rows = conn.execute(
            sql,
            (AnchorKind.ROUTE_DEF.value, AnchorKind.ROUTE_CALL.value),
        ).fetchall()
        conn.close()

        from collections import defaultdict
        table: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
            lambda: {"definitions": [], "calls": []}
        )
        for r in rows:
            extra = json.loads(r["extra"])
            entry: dict[str, Any] = {"path": r["path"], "line": r["line"], "detail": r["detail"]}
            if extra.get("method"):
                entry["method"] = extra["method"]
            if extra.get("framework"):
                entry["framework"] = extra["framework"]
            side = "definitions" if r["kind"] == AnchorKind.ROUTE_DEF.value else "calls"
            table[r["key"]][side].append(entry)

        return [{"route": k, **v} for k, v in sorted(table.items())]
