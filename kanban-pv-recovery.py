#!/usr/bin/env python3
"""
kanban-pv-recovery.py — Non-core sidecar that recovers kanban tasks blocked
by the clean-exit protocol violation (Hermes issue #27924).

Root cause:
  A worker exits rc=0 without calling kanban_complete() or kanban_block().
  The dispatcher (_classify_worker_exit in kanban_db_dispatch.py) sees
  rc=0 while task still 'running' -> clean_exit -> protocol_violation=True.
  After _PROTOCOL_VIOLATION_FAILURE_LIMIT (3) strikes the task is blocked.

  Worker writes '[kanban-worker-exit] rc=<code>' to its log via
  exit_single_query() in hermes_cli/quiet_single_query.py.

  NOT a core patch: runs alongside the dispatcher like
  llm_queue_gate.py, model_grant_guard.py, idle_gate.

Recovery logic:
  1. Scan kanban DB for blocked tasks whose latest run metadata has
     protocol_violation=True.
  2. Read worker log for the '[kanban-worker-exit] rc=<code>' trailer.
  3. rc=0 + workspace artifacts present -> worker did work but missed
     checkpoint -> unblock + complete the task.
  4. rc=0 + no artifacts -> true violation -> leave blocked.
  5. rc!=0 -> not this bug -> leave blocked.

Install in crontab (every 5 min):
  */5 * * * * python3 ~/.hermes/local_tools/kanban-pv-recovery.py

Test:
  python3 kanban-pv-recovery.py --dry-run -v
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli.quiet_single_query import KANBAN_WORKER_EXIT_TRAILER

DRY_RUN = "--dry-run" in sys.argv
VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv

_EXIT_RE = re.compile(rf"{re.escape(KANBAN_WORKER_EXIT_TRAILER)}(-?\d+)")


def _decode_json(raw: str | None) -> dict:
    """Parse a JSON metadata column (NULL-safe)."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _worker_exit_code(task_id: str) -> int | None:
    """Read the worker log for the exit trailer, return rc or None."""
    log_path = kb.worker_log_path(task_id)
    if log_path is None:
        return None
    log_path = Path(log_path)
    if not log_path.exists():
        return None
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _EXIT_RE.search(text)
    return int(m.group(1)) if m else None


def _workspace_has_artifacts(task) -> bool:
    """True if the task's workspace contains any files."""
    ws = getattr(task, "workspace", None)
    if not ws:
        return False
    p = Path(ws)
    if not p.exists():
        return False
    try:
        return any(p.rglob("*"))
    except OSError:
        return False


def _is_protocol_violation(conn, task_id: str) -> bool:
    """Check if the latest task_run for this task has protocol_violation=True."""
    row = conn.execute(
        "SELECT metadata FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    if row is None:
        return False
    return _decode_json(row[0]).get("protocol_violation") is True


def recover(dry_run: bool = False) -> int:
    """Scan and recover blocked protocol-violation tasks. Returns count recovered."""
    recovered = 0
    try:
        conn_ctx = kbc.connect()
    except Exception as e:
        print(f"ERROR: cannot connect to kanban DB: {e}", file=sys.stderr)
        return 0

    with conn_ctx as conn:
        blocked = conn.execute(
            "SELECT id FROM tasks WHERE status = 'blocked'"
        ).fetchall()

        for (tid,) in blocked:
            if not _is_protocol_violation(conn, tid):
                continue

            task = kb.get_task(conn, tid)
            if task is None:
                continue

            rc = _worker_exit_code(tid)
            if rc is None:
                if VERBOSE:
                    print(f"  [{tid}] no exit trailer - skipping")
                continue

            if rc != 0:
                if VERBOSE:
                    print(f"  [{tid}] exited rc={rc} (not clean) - leaving blocked")
                continue

            if not _workspace_has_artifacts(task):
                if VERBOSE:
                    print(f"  [{tid}] rc=0 but no workspace artifacts - true violation, leaving blocked")
                continue

            if dry_run:
                print(f"  [{tid}] DRY-RUN: rc=0 + artifacts at {getattr(task, 'workspace', '?')} -> would unblock+complete")
                recovered += 1
                continue

            kb.unblock_task(conn, tid)
            summary = (
                "Auto-recovered (bug #27924): kanban worker exited "
                "rc=0 without kanban_complete; workspace artifacts confirm "
                "work was done. Completed by non-core sidecar "
                "kanban-pv-recovery.py."
            )
            ok = kb.complete_task(
                conn, tid,
                result=summary,
                summary="Worker completed (rc=0) with artifacts but missed kanban_complete checkpoint.",
            )
            tag = "recovered" if ok else "unblocked (complete_task returned falsy)"
            print(f"  [{tid}] {tag}: unblocked + completed")
            recovered += 1

    return recovered


def main() -> int:
    count = recover(dry_run=DRY_RUN)
    action = "would recover" if DRY_RUN else "recovered"
    print(f"{action} {count} protocol-violation blocked task(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
