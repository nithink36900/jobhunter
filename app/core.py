"""Resume parsing, job fetching (Apify), scoring and SQLite tracking."""
import json
import os
import re
import sqlite3
import time
from datetime import datetime
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

SKILL_VOCAB = [
    "wireshark", "nmap", "metasploit", "burp suite", "sqlmap", "steghide", "python", "java",
    "kali", "linux", "ubuntu", "windows", "vapt", "penetration testing", "pentest", "ethical hacking",
    "vulnerability assessment", "vulnerability management", "threat detection", "threat intelligence",
    "network security", "firewall", "vpn", "dns", "tcp/ip", "encryption", "cryptography", "steganography",
    "siem", "splunk", "soc", "incident response", "owasp", "ceh", "blockchain", "exploit", "malware",
    "forensic", "iam", "access control", "nessus", "qradar", "sentinel", "edr", "grc", "iso 27001",
    "web application security", "appsec", "automation", "scripting", "ctf", "cloud security", "aws",
]
ROLE_WORDS = ["security", "cyber", "soc", "vapt", "pentest", "penetration", "infosec", "threat",
              "vulnerability", "appsec", "red team", "blue team", "forensic", "iam", "grc"]


# ------------------------------ config ------------------------------
def _apply_vocab(v):
    """config.yaml 'vocabulary:' adds your own skills and role words, so the tool is not tied to one field."""
    for lst, extra in ((SKILL_VOCAB, (v or {}).get("skills")), (ROLE_WORDS, (v or {}).get("role_words"))):
        for w in extra or []:
            w = str(w).strip().lower()
            if w and w not in lst:
                lst.append(w)


def _merge(base, over):
    for k, v in over.items():
        base[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return base


def validate_cfg(cfg):
    """Fail early with a plain message instead of a crash half-way through a run."""
    errs = []
    for sec in ("profile", "search", "sources", "matching", "apply"):
        if sec not in cfg:
            errs.append(f"config.yaml is missing the '{sec}' section")
    if errs:
        raise SystemExit("\n".join(errs))
    p, m = cfg["profile"], cfg["matching"]
    if not os.path.exists(p.get("resume_path", "")):
        errs.append("No resume yet. Open the web app (python run.py dashboard), go to Setup and upload your resume.")
    if not str(p.get("full_name", "")).strip() or "YOUR" in str(p.get("full_name", "")).upper():
        errs.append("Your name is not set. Upload your resume in the web app's Setup page, or fill in config.local.yaml.")
    w = m.get("weights", {})
    if set(w) != {"title", "skills", "level", "location", "recency", "competition"} or any(v < 0 for v in w.values()):
        errs.append("matching.weights needs title, skills, level, location, recency and competition (none negative).")
    elif sum(w.values()) != 100:
        errs.append(f"matching.weights should add up to 100 (they add up to {sum(w.values())}).")
    if not 0 <= m.get("min_score", -1) <= 100:
        errs.append("matching.min_score must be between 0 and 100.")
    if not cfg["search"].get("titles") or not cfg["search"].get("locations"):
        errs.append("search.titles and search.locations cannot be empty.")
    if cfg["apply"].get("mode") not in ("assist", "auto"):
        errs.append("apply.mode must be 'assist' or 'auto'.")
    if errs:
        raise SystemExit("Fix these in config.yaml / config.local.yaml:\n - " + "\n - ".join(errs))


def load_cfg(path="config.yaml", settings="data/settings.json"):
    """config.yaml, with anything saved from the web Settings page laid on top."""
    import yaml
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    _apply_vocab(cfg.get("vocabulary"))
    local = os.path.join(os.path.dirname(path) or ".", "config.local.yaml")  # private values; git-ignored
    if os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            cfg = _merge(cfg, yaml.safe_load(f) or {})
        _apply_vocab(cfg.get("vocabulary"))
    prof = os.path.join(os.path.dirname(settings) or ".", "profile.json")  # written by the web app's Setup page
    if os.path.exists(prof):
        try:
            with open(prof, encoding="utf-8") as f:
                cfg["profile"].update(json.load(f))
        except ValueError:
            pass  # damaged file: ignore it instead of crashing
    if os.path.exists(settings):
        try:
            ov = json.load(open(settings, encoding="utf-8"))
        except ValueError:
            ov = {}  # damaged settings file: fall back to config.yaml instead of crashing
        cfg["search"].update({k: ov[k] for k in ("titles", "locations", "posted_within", "experience_levels", "preferred_locations") if k in ov})
        cfg["matching"].update({k: ov[k] for k in ("min_score", "top_n") if k in ov})
    return cfg


# ------------------------------ resume ------------------------------
def read_resume(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        import docx
        d = docx.Document(path)
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts += [c.text for c in row.cells]
        return "\n".join(parts)
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
    return open(path, encoding="utf-8", errors="ignore").read()


@lru_cache(maxsize=None)
def _term_rx(term):
    """Whole-word match, so 'soc' does not hit 'associate' and 'java' does not hit 'javascript'."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])")


@lru_cache(maxsize=None)
def _stem_rx(stem):
    """Word-start match ('cyber' still matches 'cybersecurity'); short stems must be whole words."""
    return _term_rx(stem) if len(stem) <= 3 else re.compile(r"(?<![a-z0-9])" + re.escape(stem))


def resume_present(cfg):
    return os.path.exists(cfg["profile"].get("resume_path", ""))


def resume_skills(text):
    low = text.lower()
    return sorted({s for s in SKILL_VOCAB if _term_rx(s).search(low)})


def job_terms(text):
    """Skills from the vocabulary that a job description asks for."""
    low = (text or "").lower()
    return [s for s in SKILL_VOCAB if _term_rx(s).search(low)]


_U = r"(?:lpa|lakhs?|lacs?|million|k|l|m)\b"
_N = r"\d[\d,]*(?:\.\d+)?"
_C = r"(?:₹|rs\.?|inr|\$|usd|€|£)"
_SAL_RX = re.compile(
    rf"(?:(?<![a-z]){_C}\s?{_N}(?:\s?{_U})?(?:\s?(?:-|–|to)\s?(?:{_C}\s?)?{_N}(?:\s?{_U})?)?"
    rf"|{_N}(?:\s?(?:-|–|to)\s?{_N})?\s?(?:lpa|lakhs?|lacs?)\b(?:\s?per\s?annum)?)"
    rf"(?:\s?(?:/|per|a)\s?(?:year|yr|annum|month|mo|hour|hr)\b)?", re.I)


def extract_salary(text):
    """First plausible pay figure in a description ('Rs. 4-6 LPA', '$80,000 a year'), else ''."""
    for m in _SAL_RX.finditer(text or ""):
        s = " ".join(m.group(0).split())
        nums = [float(n.replace(",", "")) for n in re.findall(_N, s)]
        has_unit = re.search(r"(?:lpa|lakh|lac|million)|\d\s?[klm]\b", s, re.I)
        if nums and (has_unit or max(nums) >= 10000):
            return s
    return ""


def annotate(job, have):
    """Attach matched/missing skills and any salary found, so the app can show why a job scored as it did."""
    terms = job_terms(job.get("description"))
    job["matched"] = [s for s in terms if s in have]
    job["missing"] = [s for s in terms if s not in have]
    job["salary"] = extract_salary(job.get("description")) or job.get("pay", "")
    return job


# ------------------------------ fetching ------------------------------
def _fill(template, values):
    """Replace '{key}' strings with real values (keeps lists/ints as-is)."""
    if isinstance(template, dict):
        return {k: _fill(v, values) for k, v in template.items()}
    if isinstance(template, str):
        m = re.fullmatch(r"\{(\w+)\}", template)
        return values[m.group(1)] if m else template
    return template


_TRACKING = {"refid", "trackingid", "trk", "tracking", "ref", "src", "source", "from", "gclid", "fbclid"}


def canon_url(url):
    """Strip tracking params so the same job is not saved twice (LinkedIn changes them every run)."""
    if not url or not isinstance(url, str):
        return url or ""
    u = urlparse(url.strip())
    if "linkedin.com" in u.netloc.lower():
        return urlunparse(u._replace(query="", fragment=""))
    q = [(k, v) for k, v in parse_qsl(u.query) if k.lower() not in _TRACKING and not k.lower().startswith("utm_")]
    return urlunparse(u._replace(query=urlencode(q), fragment=""))


def _dig(item, key):
    """item['a.b'] or item['a']['b'] (actors return either flat dotted keys or nested objects)."""
    if key in item:
        return item[key]
    cur = item
    for part in key.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _salary_text(item):
    lab = _dig(item, "salary.label")
    if isinstance(lab, str) and lab.strip() and "not disclosed" not in lab.lower():
        return lab.strip()
    lo, hi = _dig(item, "baseSalary.min"), _dig(item, "baseSalary.max")
    if lo or hi:
        cur, unit = _dig(item, "baseSalary.currencyCode") or "", (_dig(item, "baseSalary.unitOfWork") or "").lower()
        return f"{cur} {lo or ''}-{hi or ''}".replace(" -", " ").rstrip("-").strip() + (f" per {unit}" if unit else "")
    return ""


def normalise(item):
    def g(*ks):  # first non-empty plain value (skips objects/lists so a 'location' dict cannot leak through)
        for k in ks:
            v = _dig(item, k)
            if isinstance(v, (str, int, float)) and not isinstance(v, bool) and v not in ("", None):
                return v
        return ""
    locs = item.get("locations")
    loc_list = ", ".join(x.get("label", "") for x in locs if isinstance(x, dict) and x.get("label")) if isinstance(locs, list) else ""
    desc = g("description", "descriptionText", "jobDescription", "description.full", "description.text", "description.short")
    return {
        "title": g("title", "jobTitle", "positionName", "name"),
        "company": g("companyName", "company", "companyname", "company.name", "employer.name"),
        "location": g("location", "jobLocation", "city", "location.city", "location.countryName") or loc_list,
        "pay": _salary_text(item),
        "posted": g("postedTime", "postedAt", "postingDateParsed", "publishedAt", "datePosted", "createdDateText", "datePublished", "dateOnIndeed"),
        "job_url": canon_url(g("jobUrl", "url", "link", "jobLink")),
        "apply_url": canon_url(g("applyUrl", "externalApplyLink", "applyLink", "jobUrl", "url", "link")),
        "level": g("experienceLevel", "seniority", "experience", "experience.text"),
        "type": g("contractType", "employmentType", "jobType"),
        "work_type": g("workType", "workplaceType"),
        "applicants": g("applicationsCount", "applicants", "applyCount"),
        "description": desc,
    }


def get_apify_token(token=None):
    """Token comes from the .env file in the project folder (saved from the web app), else the APIFY_TOKEN variable."""
    token = (token or "").strip()
    if not token and os.path.exists(".env"):
        for line in open(".env", encoding="utf-8"):
            key, _, val = line.strip().partition("=")
            if key.strip() == "APIFY_TOKEN":
                token = val.strip().strip("\"'")
    if not token:
        token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "Apify token not found.\n"
            "Open the web app, go to Settings and paste your token there.\n"
            "Get a token at console.apify.com > Settings > API & integrations.")
    return token


def token_present():
    try:
        get_apify_token()
        return True
    except SystemExit:
        return False


def save_token(token, path=".env"):
    """Store the token in .env (keeps any other lines)."""
    keep = []
    if os.path.exists(path):
        keep = [l.rstrip("\n") for l in open(path, encoding="utf-8") if not l.startswith("APIFY_TOKEN")]
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write("\n".join(keep + ["APIFY_TOKEN=" + token]) + "\n")
    os.replace(path + ".tmp", path)


def _dataset_id(run):
    """Old apify-client returns a dict, new versions return a Run object. Handle both."""
    if run is None:
        raise RuntimeError("Apify did not start the job. Check your Apify account and credits at console.apify.com.")
    if isinstance(run, dict):
        return run["defaultDatasetId"]
    for name in ("default_dataset_id", "defaultDatasetId"):
        if getattr(run, name, None):
            return getattr(run, name)
    if hasattr(run, "model_dump"):
        d = run.model_dump(by_alias=True)
        if d.get("defaultDatasetId") or d.get("default_dataset_id"):
            return d.get("defaultDatasetId") or d.get("default_dataset_id")
    raise RuntimeError("Could not read the results id from Apify's reply.")


def _runs(src, values, s):
    """Actors that take {title}/{location} (one keyword per run) are run once per title and location."""
    if not re.search(r"\{(title|location)\}", json.dumps(src.get("input_template") or {})):
        return [values]
    titles = s["titles"][: src.get("max_titles", 3)]
    locs = src.get("locations") or ([l.split(",")[0].strip() for l in s["locations"]] if src.get("city_only") else s["locations"])
    locs = list(dict.fromkeys(locs))[: src.get("max_locations", 1)]
    return [{**values, "title": t, "location": loc} for t in titles for loc in locs]


def fetch_jobs(cfg, token=None, log=print):
    token = get_apify_token(token)  # check the token first, so a missing one gives a clear message
    from apify_client import ApifyClient
    client = ApifyClient(token)
    s = cfg["search"]
    days = {"r86400": 1, "r604800": 7, "r2592000": 30}.get(s["posted_within"], 7)
    try:
        years = int(float(cfg["profile"].get("years_experience") or 0))
    except (TypeError, ValueError):
        years = 0
    values = {"titles": s["titles"], "locations": s["locations"], "rows": s["rows_per_search"],
              "posted_within": s["posted_within"], "experience_levels": s["experience_levels"],
              "days": str(days), "days14": str(min(days, 14)), "years": years}
    jobs, errors = [], []
    for src in cfg["sources"]:
        if not src.get("enabled"):
            continue
        log(f"[fetch] {src['name']} via {src['actor']} ...")
        for vals in _runs(src, values, s):  # one run, or one per title/location for single-keyword actors
            try:  # one broken run must not throw away what the others found
                run = client.actor(src["actor"]).call(run_input=_fill(src["input_template"], vals))
                for it in client.dataset(_dataset_id(run)).iterate_items():
                    j = normalise(it)
                    j["source"] = src["name"]
                    if j["title"] and j["apply_url"]:
                        jobs.append(j)
            except Exception as e:
                errors.append(f"{src['name']}: {e}")
                log(f"[fetch] {src['name']} failed: {e}")
        log(f"[fetch] {src['name']}: {len(jobs)} total so far")
    if errors and not jobs:
        raise RuntimeError("All job sources failed. " + " | ".join(errors))
    return jobs


# ------------------------------ scoring ------------------------------
def _age_hours(posted):
    p = str(posted).lower()
    d = re.match(r"\d{4}-\d{2}-\d{2}", p)
    if d:  # absolute date such as 2026-11-16 or 2026-11-16T09:30:00Z
        try:
            t = datetime.fromisoformat(p[:19].replace("z", ""))
            return max(0.0, (datetime.now() - t).total_seconds() / 3600)
        except ValueError:
            pass
    m = re.search(r"(\d+)\s*(minute|hour|day|week|month)", p)
    if not m:
        return 72
    n, unit = int(m.group(1)), m.group(2)
    return n * {"minute": 1 / 60, "hour": 1, "day": 24, "week": 168, "month": 720}[unit]


def _applicants(txt):
    m = re.search(r"(\d+)", str(txt))
    if "over" in str(txt).lower() and m:
        return int(m.group(1)) + 1
    return int(m.group(1)) if m else 100


def score_parts(job, cfg, skills):
    w, mt = cfg["matching"]["weights"], cfg["matching"]
    title, desc = job["title"].lower(), job["description"].lower()
    loc = f"{job['location']} {job['work_type']}".lower()

    # title: role keywords + closeness to searched titles; excluded words kill the score
    entry_title = re.search(r"trainee|intern|junior|fresher|entry|graduate", title)
    if not entry_title and any(_term_rx(x.lower()).search(title) for x in mt["exclude_title_words"]):
        return {}, "senior title"
    hits = sum(bool(_stem_rx(k).search(title)) for k in ROLE_WORDS)
    wanted = max((len(set(title.split()) & set(t.lower().split())) / len(t.split())
                  for t in cfg["search"]["titles"]), default=0)
    t = w["title"] * min(1.0, 0.5 * min(hits, 2) + 0.5 * wanted) if hits else 0

    # skills overlap with description (falls back to neutral if no description)
    if desc:
        found = [s for s in skills if _term_rx(s).search(desc)]
        sk = w["skills"] * min(1.0, len(found) / 5)
    else:
        sk = w["skills"] * 0.4

    # level
    lvl = f"{job['level']} {title}".lower()
    if any(k in lvl for k in ("intern", "entry", "junior", "trainee", "associate", "fresher", "graduate")):
        lv = w["level"]
    elif "not applicable" in lvl or not job["level"]:
        lv = w["level"] * 0.5
    else:
        lv = w["level"] * 0.2
    em = re.search(r"(\d+)\s*(?:-|to)\s*\d+\s*y", lvl)
    if em:  # Naukri style "0-2 Yrs": judged by the minimum asked for
        lv = w["level"] if int(em.group(1)) <= mt["max_years_experience"] else w["level"] * 0.2
    yrs = [int(x) for x in re.findall(r"(\d+)\+?\s*(?:-\s*\d+\s*)?years", desc)]
    if yrs and min(yrs) > mt["max_years_experience"]:
        lv *= 0.3

    # location
    pref = cfg["search"]["preferred_locations"]
    lo = w["location"] if any(p in loc for p in pref) else w["location"] * (0.5 if "india" in loc else 0.1)

    # recency + competition
    age = _age_hours(job["posted"])
    rc = w["recency"] * (1 if age <= 24 else 0.8 if age <= 72 else 0.5 if age <= 168 else 0.2)
    ap = _applicants(job["applicants"])
    cp = w["competition"] * (1 if ap < 25 else 0.7 if ap < 75 else 0.4 if ap < 150 else 0.2)

    return {"title": t, "skills": sk, "level": lv, "location": lo, "recency": rc, "competition": cp}, ""


def score_job(job, cfg, skills):
    parts, note = score_parts(job, cfg, skills)
    return min(round(sum(parts.values())), 99), note


def rank(jobs, cfg, skills):
    mt = cfg["matching"]
    bad_co = [c.lower() for c in mt.get("exclude_companies") or []]
    bad_kw = [k.lower() for k in mt.get("exclude_keywords") or []]
    for j in jobs:
        blob = f"{j['title']} {j['description']}".lower()
        if any(c in j["company"].lower() for c in bad_co) or any(_term_rx(k).search(blob) for k in bad_kw):
            j["score"], j["note"], j["breakdown"] = 0, "blocked", {}  # blocklist from config.yaml
        else:
            parts, j["note"] = score_parts(j, cfg, skills)
            j["breakdown"] = {k: round(v, 1) for k, v in parts.items()}
            j["score"] = min(round(sum(parts.values())), 99)
    seen, out = set(), []
    for j in sorted(jobs, key=lambda x: -x["score"]):
        key = (j["title"].lower(), j["company"].lower(), j["location"].lower())
        if key in seen or j["score"] < mt["min_score"]:
            continue
        seen.add(key)
        out.append(j)
    have = set(skills)
    return [annotate(j, have) for j in out[: mt["top_n"]]]


# ------------------------------ tracking ------------------------------
def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS jobs(
        apply_url TEXT PRIMARY KEY, title TEXT, company TEXT, score INT,
        status TEXT DEFAULT 'new', data TEXT, updated TEXT)""")
    have = [r[1] for r in db.execute("PRAGMA table_info(jobs)")]
    for col, ddl in (("notes", "TEXT DEFAULT ''"), ("starred", "INT DEFAULT 0")):
        if col not in have:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")
    db.commit()


class Tracker:
    def __init__(self, path="data/jobs.db"):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path)
        self.last_new = []
        ensure_schema(self.db)

    def save(self, jobs):
        new = 0
        self.last_new = []  # jobs first seen in this save (used for notifications)
        known = {r[0] for r in self.db.execute("SELECT apply_url FROM jobs")}  # one query, not one per job
        for j in jobs:
            if j["apply_url"] in known:
                self.db.execute("UPDATE jobs SET score=?, data=? WHERE apply_url=?",
                                (j["score"], json.dumps(j), j["apply_url"]))  # refresh skills/salary too
            else:
                known.add(j["apply_url"])
                new += 1
                self.last_new.append(j)
                self.db.execute("INSERT INTO jobs(apply_url,title,company,score,status,data,updated) VALUES(?,?,?,?,?,?,?)",
                                (j["apply_url"], j["title"], j["company"], j["score"], "new",
                                 json.dumps(j), datetime.now().isoformat()))
        self.db.commit()
        return new

    def pending(self, limit):
        rows = self.db.execute("SELECT data FROM jobs WHERE status='new' ORDER BY score DESC LIMIT ?",
                               (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def mark(self, url, status):
        self.db.execute("UPDATE jobs SET status=?, updated=? WHERE apply_url=?",
                        (status, datetime.now().isoformat(), url))
        self.db.commit()

    def all(self):
        return self.db.execute(
            "SELECT score,title,company,status,apply_url FROM jobs ORDER BY score DESC").fetchall()


def markdown_table(jobs):
    lines = ["| Apply Link | Rank | Match Score | Role | Company |", "|---|---|---|---|---|"]
    for i, j in enumerate(jobs, 1):
        lines.append(f"| [Apply]({j['apply_url']}) | {i} | {j['score']}% | {j['title']} "
                     f"({j['location']}) | {j['company']} |")
    return "\n".join(lines)
