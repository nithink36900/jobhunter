#!/usr/bin/env python3
"""JobHunter CLI.

  python run.py search            fetch -> score -> save -> print ranked table + CSV
  python run.py apply             apply to saved 'new' jobs (assist/auto per config)
  python run.py run               search + apply
  python run.py status            show everything tracked so far
  python run.py dashboard         web app at http://127.0.0.1:8765
  python run.py search --offline jobs.json   score a saved JSON list (no Apify needed)
"""
import argparse
import csv
import json
import os
import sys

from . import core

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = "data"


def do_search(cfg, tracker, offline=None):
    text = core.read_resume(cfg["profile"]["resume_path"])
    skills = core.resume_skills(text)
    print(f"Resume skills detected ({len(skills)}): {', '.join(skills)}")
    if offline:
        jobs = [core.normalise(x) | {"source": "file"} for x in json.load(open(offline, encoding="utf-8"))]
    else:
        jobs = core.fetch_jobs(cfg)
    top = core.rank(jobs, cfg, skills)
    new = tracker.save(top)
    print(f"\n{len(jobs)} fetched, {len(top)} above {cfg['matching']['min_score']}%, {new} new\n")
    print(core.markdown_table(top))
    with open(os.path.join(DATA, "matches.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Rank", "Score", "Role", "Company", "Location", "Apply Link"])
        for i, j in enumerate(top, 1):
            w.writerow([i, j["score"], j["title"], j["company"], j["location"], j["apply_url"]])
    open(os.path.join(DATA, "matches.md"), "w", encoding="utf-8").write(core.markdown_table(top))
    return skills


def do_apply(cfg, tracker, skills=None):
    from . import applier
    text = core.read_resume(cfg["profile"]["resume_path"])
    skills = skills or core.resume_skills(text)
    jobs = tracker.pending(cfg["apply"]["max_per_run"])
    try:
        if not jobs:
            return print("Nothing to apply to yet. Run a search first.")
        applier.run_applications(jobs, cfg, skills, tracker)
    finally:
        if os.environ.get("JH_NEWWINDOW"):  # opened from the web app: let the person read the result
            input("\nFinished. Press Enter to close this window.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["search", "apply", "run", "status", "dashboard"])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--offline", help="JSON file of jobs to score instead of calling Apify")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):  # Windows: avoid crashes on characters like the en dash
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.chdir(ROOT)  # all paths in config.yaml are relative to the project folder
    cfg, tracker = core.load_cfg(a.config), core.Tracker(os.path.join(DATA, "jobs.db"))
    if a.command in ("search", "run"):
        skills = do_search(cfg, tracker, a.offline)
    if a.command == "apply":
        do_apply(cfg, tracker)
    if a.command == "run":
        do_apply(cfg, tracker, skills)
    if a.command == "dashboard":
        from .dashboard import server
        server.serve(os.path.join(DATA, "jobs.db"))
    if a.command == "status":
        for s, t, c, st, u in tracker.all():
            print(f"{s:>3}%  {st:<14} {t} @ {c}")


if __name__ == "__main__":
    main()
