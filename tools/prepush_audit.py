# -*- coding: utf-8 -*-
"""Pre-push audit: scan the exact commit content (HEAD) for identity strings,
verify tracked file set, worktree state, and author anonymity.

The blocklist lives ONLY in the local file blocked-words.txt (git-ignored) —
never hardcode actual sensitive words in this public file.
Usage:  python tools/prepush_audit.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GIT = shutil.which("git") or next(
    (p for p in (r"C:\Program Files\Git\cmd\git.exe",
                 r"C:\Program Files (x86)\Git\cmd\git.exe",
                 "/usr/bin/git") if Path(p).exists()), "git")

blocked_file = ROOT / "blocked-words.txt"
if blocked_file.exists():
    words = [w.strip() for w in blocked_file.read_text(encoding="utf-8").splitlines() if w.strip()]
else:
    print("blocked-words.txt not found — word scan skipped "
          "(maintainers: create it locally per docs/RELEASE-PROCESS.md)")
    words = []


def git(*args):
    return subprocess.run([GIT, *args], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


problems = []

for w in words:
    escaped = w.replace(" ", ".")
    r = git("grep", "-i", "-l", "-E", escaped, "HEAD")
    if r.stdout.strip():
        problems.append(f"HEAD contains '{w}' in: {r.stdout.strip().splitlines()}")

tracked = git("ls-files").stdout.splitlines()
for bad in ("acceptance/", "espacenet-journal/", ".egg-info", "blocked-words.txt",
            "pytest-results", "__pycache__"):
    if any(bad in f for f in tracked):
        problems.append(f"tracked sensitive path: {bad}")

author = git("log", "-1", "--format=%an <%ae>").stdout.strip()
if "@" in author and "noreply" not in author:
    problems.append(f"author email may leak identity: {author}")

status = git("status", "--porcelain").stdout.strip()
if status:
    problems.append(f"uncommitted changes:\n{status[:500]}")

print("tracked files:", len(tracked))
print("author:", author)
print("HEAD:", git("log", "-1", "--oneline").stdout.strip())
if problems:
    print("\n=== PROBLEMS (push blocked) ===")
    for p in problems:
        print(" -", p)
    sys.exit(1)
print("\nPRE-PUSH AUDIT: CLEAN — safe to push")
