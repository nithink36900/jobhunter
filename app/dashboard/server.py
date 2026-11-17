"""JobHunter web app (local only, standard library).

    python run.py dashboard          # then open http://127.0.0.1:8765
"""
import base64
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import core, insights
from .. import resume as rparse
from ..cli import export_all

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
STATUSES = ["new", "applied", "opened_manual", "submitted_auto", "interview", "offer",
            "rejected", "skipped", "error"]
RUN = {"proc": None, "log": [], "code": None}
RESUME_TYPES = {".docx": b"PK", ".pdf": b"%PDF", ".txt": None}  # allowed extensions and the bytes a real file starts with
PROFILE_KEYS = ("full_name", "email", "phone", "city", "state", "country", "linkedin", "github",
                "notice_period", "graduation_year", "years_experience", "cover_letter_template")


# ------------------------------ database ------------------------------
def query(db_path, sql, args=()):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, args).fetchall()
        con.commit()
        return [dict(r) for r in rows]
    finally:
        con.close()


def list_jobs(db_path):
    out = []
    for r in query(db_path, "SELECT apply_url,title,company,score,status,updated,notes,starred,data FROM jobs ORDER BY score DESC"):
        d = json.loads(r.pop("data") or "{}")
        r.update({"location": d.get("location", ""), "level": d.get("level", ""), "work_type": d.get("work_type", ""),
                  "type": d.get("type", ""), "posted": d.get("posted", ""), "applicants": d.get("applicants", ""),
                  "source": d.get("source", ""), "job_url": d.get("job_url", ""),
                  "matched": d.get("matched", []), "missing": d.get("missing", []), "salary": d.get("salary", ""), "breakdown": d.get("breakdown", {}),
                  "starred": bool(r["starred"]), "notes": r["notes"] or ""})  # descriptions load on demand (/api/job)
        out.append(r)
    return out


# ------------------------------ background search ------------------------------
def start_search():
    if RUN["proc"] and RUN["proc"].poll() is None:
        return False
    RUN.update(log=[], code=None)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    p = subprocess.Popen([sys.executable, "-u", os.path.join(ROOT, "run.py"), "search"], cwd=ROOT, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    RUN["proc"] = p

    def pump():
        for line in p.stdout:
            RUN["log"].append(line.rstrip())
            del RUN["log"][:-300]
        RUN["code"] = p.wait()
    threading.Thread(target=pump, daemon=True).start()
    return True


APPLY = {"proc": None}


def start_apply():
    """Open the apply step in its own console window (it needs you to check each form)."""
    if sys.platform != "win32":
        return {"started": False, "message": "Open a terminal in this folder and run:  python run.py apply"}
    if APPLY["proc"] and APPLY["proc"].poll() is None:
        return {"started": False, "message": "The apply window is already open. Look for it in your taskbar."}
    APPLY["proc"] = subprocess.Popen([sys.executable, os.path.join(ROOT, "run.py"), "apply"], cwd=ROOT,
                                     env={**os.environ, "JH_NEWWINDOW": "1", "PYTHONIOENCODING": "utf-8"},
                                     creationflags=subprocess.CREATE_NEW_CONSOLE)
    return {"started": True, "message": "A new window opened. A browser will open for each job: check the form, submit it, then press Enter in that window."}


def run_state():
    p = RUN["proc"]
    return {"running": bool(p and p.poll() is None), "code": RUN["code"], "log": RUN["log"][-120:]}


# ------------------------------ settings ------------------------------
def clean_settings(b):
    def lines(v):
        v = [str(x).strip() for x in v if str(x).strip()]
        if not 1 <= len(v) <= 20:
            raise ValueError("Add between 1 and 20 entries for job titles and locations.")
        return v
    out = {"titles": lines(b["titles"]), "locations": lines(b["locations"])}
    if b["posted_within"] not in ("r86400", "r604800", "r2592000"):
        raise ValueError("Unknown time window.")
    out["posted_within"] = b["posted_within"]
    out["experience_levels"] = [x for x in b["experience_levels"] if x in ("1", "2", "3", "4", "5")]
    out["min_score"] = max(0, min(100, int(b["min_score"])))
    out["top_n"] = max(1, min(50, int(b["top_n"])))
    return out


def get_settings():
    cfg = core.load_cfg()
    p, m = cfg["profile"], cfg["matching"]
    try:
        skills = core.resume_skills(core.read_resume(p["resume_path"]))
    except Exception:
        skills = []
    s = cfg["search"]
    return {"settings": {"titles": s["titles"], "locations": s["locations"], "posted_within": s["posted_within"],
                         "experience_levels": s["experience_levels"], "min_score": m["min_score"], "top_n": m["top_n"]},
            "skills": skills, "profile": {k: p.get(k, "") for k in PROFILE_KEYS},
            "resume": os.path.basename(p["resume_path"]) if core.resume_present(cfg) else "",
            "apply_mode": cfg["apply"]["mode"], "token_set": core.token_present()}


def job_detail(db_path, url):
    rows = query(db_path, "SELECT data FROM jobs WHERE apply_url=?", (url,))
    if not rows:
        raise ValueError("Job not found.")
    d = json.loads(rows[0]["data"] or "{}")
    return {"description": (d.get("description") or "")[:6000], "prep": insights.prep_questions(d)}


def insight_data(db_path):
    js = list_jobs(db_path)
    days = core.load_cfg()["matching"].get("followup_days", 7)
    return {"analytics": insights.analytics(js), "followups": insights.followups(js, days)}


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_json(path, obj):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    os.replace(path + ".tmp", path)  # atomic swap: never leaves a half-written file


def save_resume(b):
    """Store the uploaded resume, read it, and fill in the profile and search settings from it."""
    ext = os.path.splitext(str(b.get("filename", "")))[1].lower()
    if ext not in RESUME_TYPES:
        raise ValueError("Please upload a .docx, .pdf or .txt resume.")
    try:
        raw = base64.b64decode(b["data"], validate=True)
    except (ValueError, KeyError):
        raise ValueError("The upload was damaged. Please try again.")
    if not raw or len(raw) > 5 * 1024 * 1024:
        raise ValueError("The file is empty or bigger than 5 MB.")
    if RESUME_TYPES[ext] and not raw.startswith(RESUME_TYPES[ext]):
        raise ValueError(f"That does not look like a real {ext} file.")
    data = os.path.join(ROOT, "data")
    dest = os.path.join(data, "resume" + ext)  # fixed name: the uploaded file name is never used as a path
    with open(dest + ".tmp", "wb") as f:
        f.write(raw)
    os.replace(dest + ".tmp", dest)
    try:
        text = core.read_resume(dest)
        if len(text.strip()) < 30:
            raise ValueError("No readable text found. If this is a scanned PDF, upload a .docx or a text-based PDF.")
    except Exception as e:
        os.remove(dest)
        raise ValueError(str(e) if isinstance(e, ValueError) else "Could not read that file. Try saving it as .docx or .pdf again.")
    for other in RESUME_TYPES:  # only one resume at a time
        if other != ext and os.path.exists(os.path.join(data, "resume" + other)):
            os.remove(os.path.join(data, "resume" + other))
    found = rparse.extract_profile(text, core.resume_skills(text))
    pp, sp = os.path.join(data, "profile.json"), os.path.join(data, "settings.json")
    _write_json(pp, {**_read_json(pp), **found["profile"], "resume_path": f"data/resume{ext}"})
    prefs = {k: found[k] for k in ("titles", "locations", "preferred_locations", "experience_levels") if found.get(k)}
    if prefs:
        _write_json(sp, {**_read_json(sp), **prefs})
    out = get_settings()
    out["found"] = sorted(found["profile"])
    return out


def save_profile(b):
    pp, sp = os.path.join(ROOT, "data", "profile.json"), os.path.join(ROOT, "data", "settings.json")
    new = {}
    for k in PROFILE_KEYS:
        if k in b:
            v = str(b[k]).strip()
            if len(v) > (4000 if k == "cover_letter_template" else 300):
                raise ValueError(f"'{k.replace('_', ' ')}' is too long.")
            new[k] = v
    if new.get("email") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", new["email"]):
        raise ValueError("That email address does not look right.")
    if new.get("phone") and not re.fullmatch(r"\+?[\d\s\-()]{7,20}", new["phone"]):
        raise ValueError("That phone number does not look right.")
    if "full_name" in new and not new["full_name"]:
        raise ValueError("Please enter your name.")
    old = _read_json(pp)
    _write_json(pp, {**old, **new})
    if new.get("city") and new["city"] != old.get("city"):  # keep location scoring in step with the city
        _write_json(sp, {**_read_json(sp), "preferred_locations": [new["city"].lower(), "remote"]})


def letter_for(db_path, url):
    rows = query(db_path, "SELECT data FROM jobs WHERE apply_url=?", (url,))
    if not rows:
        raise ValueError("Job not found.")
    from .. import applier
    cfg = core.load_cfg()
    skills = core.resume_skills(core.read_resume(cfg["profile"]["resume_path"]))
    return applier.cover_letter(cfg, json.loads(rows[0]["data"]), skills)


# ------------------------------ http ------------------------------
def make_handler(db_path):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json", headers=None):
            data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self):  # blocks DNS-rebinding tricks; only local names are served
            return (self.headers.get("Host", "").split(":")[0]) in ("127.0.0.1", "localhost")

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden"})
            u = urlparse(self.path)
            try:
                if u.path == "/api/jobs":
                    return self._send(200, {"jobs": list_jobs(db_path), "statuses": STATUSES, "token_set": core.token_present(),
                                            "resume_set": core.resume_present(core.load_cfg())})
                if u.path == "/api/run":
                    return self._send(200, run_state())
                if u.path == "/api/settings":
                    return self._send(200, get_settings())
                if u.path == "/api/job":
                    return self._send(200, job_detail(db_path, parse_qs(u.query)["url"][0]))
                if u.path == "/api/insights":
                    return self._send(200, insight_data(db_path))
                if u.path == "/api/export":
                    tmp = os.path.join(ROOT, "data", "all_jobs.csv")
                    export_all(db_path, tmp)
                    with open(tmp, "rb") as f:
                        return self._send(200, f.read(), "text/csv", {"Content-Disposition": 'attachment; filename="jobhunter_jobs.csv"'})
                if u.path == "/api/letter":
                    return self._send(200, {"letter": letter_for(db_path, parse_qs(u.query)["url"][0])})
                if u.path in ("/", "/index.html"):
                    with open(os.path.join(HERE, "index.html"), "rb") as f:
                        return self._send(200, f.read(), "text/html")
            except Exception as e:
                return self._send(400, {"error": str(e)})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            origin = self.headers.get("Origin", "")
            if (not self._host_ok() or self.headers.get("X-JobHunter") != "1"
                    or (origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"))):
                return self._send(403, {"error": "forbidden"})
            try:
                n = int(self.headers.get("Content-Length", 0))
                if n > 10 * 1024 * 1024:
                    return self._send(413, {"error": "That upload is too large."})
                b = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/api/resume":
                    return self._send(200, save_resume(b))
                if self.path == "/api/profile":
                    save_profile(b)
                elif self.path == "/api/status":
                    if b["status"] not in STATUSES:
                        raise ValueError("Unknown status.")
                    query(db_path, "UPDATE jobs SET status=?, updated=datetime('now') WHERE apply_url=?", (b["status"], b["url"]))
                elif self.path == "/api/star":
                    query(db_path, "UPDATE jobs SET starred=? WHERE apply_url=?", (1 if b["starred"] else 0, b["url"]))
                elif self.path == "/api/bulk":
                    if b["status"] not in STATUSES:
                        raise ValueError("Unknown status.")
                    urls = [str(u) for u in b["urls"]][:500]
                    query(db_path, f"UPDATE jobs SET status=?, updated=datetime('now') WHERE apply_url IN ({','.join('?' * len(urls))})",
                          (b["status"], *urls)) if urls else None
                elif self.path == "/api/notes":
                    query(db_path, "UPDATE jobs SET notes=?, updated=datetime('now') WHERE apply_url=?", (str(b["notes"])[:5000], b["url"]))
                elif self.path == "/api/search":
                    return self._send(200, {"started": start_search()})
                elif self.path == "/api/apply":
                    return self._send(200, start_apply())
                elif self.path == "/api/token":
                    tok = str(b["token"]).strip()
                    if not re.fullmatch(r"[A-Za-z0-9_\-]{15,200}", tok):
                        raise ValueError("That doesn't look like an Apify token. Copy it again from console.apify.com (Settings, API and integrations).")
                    core.save_token(tok, os.path.join(ROOT, ".env"))
                elif self.path == "/api/settings":
                    clean = clean_settings(b)  # validate BEFORE touching the file
                    path = os.path.join(ROOT, "data", "settings.json")
                    _write_json(path, {**_read_json(path), **clean})  # keeps keys this form does not edit
                else:
                    return self._send(404, {"error": "not found"})
                self._send(200, {"ok": True})
            except Exception as e:
                self._send(400, {"error": str(e)})

        def log_message(self, *a):
            pass

    return Handler


def serve(db_path="data/jobs.db", port=8765, open_browser=True):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    con = sqlite3.connect(db_path)
    core.ensure_schema(con)
    con.close()
    url = f"http://127.0.0.1:{port}"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(db_path))
    except OSError:
        print(f"Port {port} is already in use. JobHunter is probably already running: open {url}")
        if open_browser:
            webbrowser.open(url)
        return
    print(f"JobHunter web app running at {url}  (close this window or press Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    server.serve_forever()
