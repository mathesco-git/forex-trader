#!/usr/bin/env python3
"""
push_to_github.py
=================
Pushes the forex trader project files to GitHub.
Repo: https://github.com/mathesco-git/forex-trader

Usage:
    python push_to_github.py

Credentials are read from .env in the same folder:
    GITHUB_USERNAME=mathesco-git
    GITHUB_TOKEN=your_token_here
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
REPO_URL   = "https://github.com/mathesco-git/forex-trader"
BRANCH     = "main"
COMMIT_MSG = "Update forex signal engine v2 and dashboard"

FILES_TO_PUSH = [
    "README.md",
    "forex_engine_v2.py",
    "forex_signal_dashboard_v2.html",
]

SCRIPT_DIR = Path(__file__).parent.resolve()
WORK_DIR   = Path.home() / "forex-trader-push"
# ─────────────────────────────────────────────────────────────────────────────


def load_env():
    """Load credentials from .env file next to this script."""
    env_path = SCRIPT_DIR / ".env"
    if not env_path.exists():
        print(f"✗ .env file not found at {env_path}")
        print("  Create it with:\n    GITHUB_USERNAME=your_username\n    GITHUB_TOKEN=your_token")
        sys.exit(1)

    creds = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            creds[key.strip()] = val.strip()

    username = creds.get("GITHUB_USERNAME", "")
    token    = creds.get("GITHUB_TOKEN", "")

    if not username or not token or token == "your_token_here":
        print("✗ Missing or placeholder credentials in .env")
        print("  Fill in GITHUB_USERNAME and GITHUB_TOKEN")
        sys.exit(1)

    return username, token


def run(cmd, cwd=None, check=True):
    """Run a shell command and print it."""
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"    {result.stdout.strip()}")
    if result.returncode != 0 and check:
        print(f"  ✗ ERROR: {result.stderr.strip()}")
        sys.exit(1)
    return result


def main():
    print("=" * 60)
    print("  GitHub Push — forex-trader")
    print("=" * 60)

    # ── Load credentials ──────────────────────────────────────────
    username, token = load_env()
    auth_url = f"https://{username}:{token}@github.com/mathesco-git/forex-trader.git"
    print(f"\n  Logged in as: {username}")

    # ── Prepare working directory ─────────────────────────────────
    print(f"\n[1/5] Preparing working directory...")
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    WORK_DIR.mkdir(parents=True)

    # ── Clone or init ─────────────────────────────────────────────
    print(f"\n[2/5] Cloning repo...")
    clone = run(["git", "clone", auth_url, str(WORK_DIR)], check=False)

    if clone.returncode != 0:
        print("  Repo appears empty — initialising locally.")
        run(["git", "init", "-b", BRANCH], cwd=WORK_DIR)
        run(["git", "remote", "add", "origin", auth_url], cwd=WORK_DIR)

    # ── Copy files ────────────────────────────────────────────────
    print(f"\n[3/5] Copying files...")
    for fname in FILES_TO_PUSH:
        src = SCRIPT_DIR / fname
        if not src.exists():
            print(f"  ⚠ Skipping (not found): {fname}")
            continue
        shutil.copy2(src, WORK_DIR / fname)
        print(f"  ✓ {fname}")

    # ── Stage, commit, push ───────────────────────────────────────
    run(["git", "config", "user.email", f"{username}@users.noreply.github.com"], cwd=WORK_DIR)
    run(["git", "config", "user.name", username], cwd=WORK_DIR)

    print(f"\n[4/5] Staging and committing...")
    run(["git", "add"] + FILES_TO_PUSH, cwd=WORK_DIR)

    status = run(["git", "status", "--porcelain"], cwd=WORK_DIR, check=False)
    if not status.stdout.strip():
        print("  Nothing new to commit — already up to date.")
    else:
        run(["git", "commit", "-m", COMMIT_MSG], cwd=WORK_DIR)

    print(f"\n[5/5] Pushing to {REPO_URL}...")
    run(["git", "push", "-u", "origin", BRANCH], cwd=WORK_DIR)

    # ── Cleanup ───────────────────────────────────────────────────
    shutil.rmtree(WORK_DIR)

    print("\n" + "=" * 60)
    print(f"  ✓ Done!  →  {REPO_URL}")
    print("=" * 60)


if __name__ == "__main__":
    main()
