#!/usr/bin/env python3
"""JobHunter CLI.

  python run.py search            fetch -> score -> save -> print ranked table + CSV
  python run.py apply             apply to saved 'new' jobs (assist/auto per config)
  python run.py run               search + apply
  python run.py status            show everything tracked so far
  python run.py dashboard         web app at http://127.0.0.1:8765
  python run.py export            save every tracked job to data/all_jobs.csv
  python run.py followups         list applications that need a follow-up
  python run.py watch [--every H] repeat the search every H hours and alert on new matches
  python run.py search --offline jobs.json   score a saved JSON list (no Apify needed)
"""
import argparse
import csv
import json
import os
import sys
import time

from . import core, insights, notify

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
    if notify.send(cfg, tracker.last_new):
        print(f"Alert sent for {len(tracker.last_new)} new match(es).")
    print(f"\n{len(jobs)} fetched, {len(top)} above {cfg['matching']['min_score']}%, {new} new\n")
    print(core.markdown_table(top))
    with open(os.path.join(DATA, "matches.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Rank", "Score", "Role", "Company", "Location", "Apply Link"])
        for i, j in enumerate(top, 1):
            w.writerow([i, j["score"], j["title"], j["company"], j["location"], j["apply_url"]])
    open(os.path.join(DATA, "matches.md"), "w", encoding="utf-8").write(core.markdown_table(top))
    return skills


def csv_safe(v):
    """Stop spreadsheet apps from running job text that starts with = + - @ as a formula."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


def export_all(db_path, out):
    import sqlite3
    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT score,title,company,status,apply_url,data,notes,updated FROM jobs ORDER BY score DESC").fetchall()
    con.close()
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Score", "Role", "Company", "Location", "Salary", "Status", "Missing skills", "Notes", "Updated", "Apply Link"])
        for sc, t, c, st, u, d, n, up in rows:
            d = json.loads(d or "{}")
            w.writerow([csv_safe(x) for x in (sc, t, c, d.get("location", ""), d.get("salary", ""), st,
                                              ", ".join(d.get("missing", [])), n or "", up, u)])
    return len(rows)


def do_followups(cfg, tracker):
    rows = [dict(zip(("score", "title", "company", "status", "apply_url", "updated"), r))
            for r in tracker.db.execute("SELECT score,title,company,status,apply_url,updated FROM jobs")]
    due = insights.followups(rows, cfg["matching"].get("followup_days", 7))
    if not due:
        return print("No follow-ups due.")
    for d in due:
        print(f"{d['days']:>3} days  {d['title']} @ {d['company']}\n          {d['apply_url']}")


def do_watch(cfg, tracker, hours):
    hours = hours or cfg.get("watch", {}).get("interval_hours", 6)
    print(f"Watching: searching every {hours}h. Press Ctrl+C to stop.")
    while True:
        try:
            do_search(cfg, tracker)
        except Exception as e:  # keep watching after a bad run (network, Apify credits...)
            print(f"Search failed: {e}")
        time.sleep(max(0.1, hours) * 3600)


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
    ap.add_argument("command", choices=["search", "apply", "run", "status", "dashboard", "export", "followups", "watch"])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--offline", help="JSON file of jobs to score instead of calling Apify")
    ap.add_argument("--every", type=float, help="hours between searches (watch)")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):  # Windows: avoid crashes on characters like the en dash
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.chdir(ROOT)  # all paths in config.yaml are relative to the project folder
    cfg, tracker = core.load_cfg(a.config), core.Tracker(os.path.join(DATA, "jobs.db"))
    if a.command in ("search", "apply", "run", "watch"):
        core.validate_cfg(cfg)
    if a.command in ("search", "run"):
        skills = do_search(cfg, tracker, a.offline)
    if a.command == "apply":
        do_apply(cfg, tracker)
    if a.command == "run":
        do_apply(cfg, tracker, skills)
    if a.command == "dashboard":
        from .dashboard import server
        server.serve(os.path.join(DATA, "jobs.db"))
    if a.command == "export":
        out = os.path.join(DATA, "all_jobs.csv")
        print(f"Saved {export_all(os.path.join(DATA, 'jobs.db'), out)} jobs to {out}")
    if a.command == "followups":
        do_followups(cfg, tracker)
    if a.command == "watch":
        try:
            do_watch(cfg, tracker, a.every)
        except KeyboardInterrupt:
            print("\nStopped.")
    if a.command == "status":
        for s, t, c, st, u in tracker.all():
            print(f"{s:>3}%  {st:<14} {t} @ {c}")


if __name__ == "__main__":
    main()
