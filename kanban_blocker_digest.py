#!/usr/bin/env python3
"""
kanban_blocker_digest.py — Non-core sidecar that comments on blocked kanban cards
and files needs_input as described in ANALYSIS.md.

Actions:
  1. t_e7b781c2 [default]: comment with findings, dispatch search for round 1 page list
  2. t_444ba31c [None]: link→t_68c17d81, comment blocked reason
  3. t_e4e5d10e [None]: link→t_7a803733, comment blocked reason
  4. t_f81619b4 [None]: link→t_68c17d81, comment blocked reason

No core patches. Uses `hermes kanban` CLI via subprocess, like kanban_protocol_guard.py.

Deploy:
  python3 ~/.local/bin/kanban_blocker_digest.py

Config env:
  HERMES_KANBAN_DB — path to kanban.db (default: ~/.hermes/kanban.db)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv
VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv

# Cards to process
# (task_id, owner, new_comment, parent_id_to_link, parent_name)
ACTIONS = [
    {
        "task_id": "t_e7b781c2",
        "comment": (
            "Checked ECS site (catalog.edgecasesignals.com) via WP REST API. "
            "Found: Sample Page (placeholder, kill), TEST post (marked for removal, kill), "
            "5 categories (4 empty: On The Air, Sundry, The Antenna Farm, Uncategorized). "
            "WP admin at 127.0.0.1:8088/wp-admin/ requires auth — draft/private pages inaccessible. "
            "Card has no embedded list of 5 live + 2 retired admin page URLs — "
            "need round 1 output from ~/.hermes/skills/ or SB notes. "
            "Dispatching search task to default profile."
        ),
        "link_parent": None,
        "dispatch": (
            "Search ~/.hermes/skills/ and ~/.hermes/cache/scratch/ for "
            "Date-or-kill round 1 outputs. Extract the 5 live + 2 retired "
            "admin page URLs. HEAD each URL and report 2xx (live) vs "
            "4xx/5xx/timeout (dead). Report results with URLs and status codes."
        ),
    },
    {
        "task_id": "t_444ba31c",
        "comment": "Blocked on Paul PBR spec disposition decision (t_68c17d81). Need Paul to decide: provide spec or retire stub.",
        "link_parent": "t_68c17d81",
        "dispatch": None,
    },
    {
        "task_id": "t_e4e5d10e",
        "comment": "Blocked on Paul PNL input spec disposition decision (t_7a803733). Need Paul to decide: provide spec or retire stub.",
        "link_parent": "t_7a803733",
        "dispatch": None,
    },
    {
        "task_id": "t_f81619b4",
        "comment": "Blocked on Paul PBR input disposition decision (t_68c17d81). Need Paul to decide: provide spec or retire stub.",
        "link_parent": "t_68c17d81",
        "dispatch": None,
    },
]


def _run(cmd: list[str]) -> bool:
    """Run a hermes CLI command. Returns True on success."""
    if DRY_RUN:
        print(f"  DRY-RUN: {' '.join(cmd)}")
        return True
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"  ERROR: rc={result.returncode} stderr={result.stderr.strip()[:200]}")
            return False
        if VERBOSE:
            print(f"  OK: {result.stdout.strip()[:100]}")
        return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def run() -> int:
    actions_taken = 0
    for action in ACTIONS:
        tid = action["task_id"]
        print(f"Processing {tid}...")

        # 1. Comment on the card
        comment = action["comment"]
        ok = _run([
            "hermes", "kanban", "comment", tid,
            "--body", comment,
        ])
        if ok:
            actions_taken += 1

        # 2. Link as dependency (child → parent)
        parent = action.get("link_parent")
        if parent:
            ok = _run([
                "hermes", "kanban", "link", parent, tid,
            ])
            if ok:
                actions_taken += 1

        # 3. Dispatch search task (for t_e7b781c2 only)
        dispatch_query = action.get("dispatch")
        if dispatch_query:
            ok = _run([
                "hermes", "-p", "default", "chat", "-q", dispatch_query,
            ])
            if ok:
                actions_taken += 1
            print(f"  Dispatched search task to default profile")

    print(f"\nTotal actions taken: {actions_taken}")
    print("\nParent cards needing Paul decision (NOT closed):")
    print("  t_68c17d81 — PBR spec/stub disposition")
    print("  t_7a803733 — PNL input spec disposition")
    return 0


def main() -> int:
    print(f"kanban_blocker_digest.py — dry_run={DRY_RUN} verbose={VERBOSE}")
    return run()


if __name__ == "__main__":
    sys.exit(main())
