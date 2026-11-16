import json, os, sqlite3, tempfile, unittest
from datetime import datetime
from app import core, insights, applier
from app.cli import csv_safe

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = {
    "search": {"titles": ["Security Analyst", "SOC Analyst"], "locations": ["India"], "preferred_locations": ["hyderabad", "remote"]},
    "matching": {"min_score": 50, "top_n": 10, "exclude_title_words": ["senior", "lead", "sr"], "max_years_experience": 2,
                 "weights": {"title": 30, "skills": 30, "level": 15, "location": 10, "recency": 10, "competition": 5}},
}
SK = ["python", "nmap", "soc"]


def job(title, desc="", **kw):
    return {"title": title, "company": "Acme", "description": desc, "location": "Hyderabad", "work_type": "",
            "level": "", "posted": "1 day ago", "applicants": "5", "apply_url": "https://x.com/" + title, **kw}


class Scoring(unittest.TestCase):
    def test_short_words_need_whole_word(self):
        self.assertEqual(core.score_parts(job("Social Media Manager"), CFG, SK)[0]["title"], 0)  # 'soc' is not in 'social'
        self.assertEqual(core.job_terms("javascript only"), [])
        self.assertIn("java", core.job_terms("java developer"))

    def test_senior_excluded_but_not_via_associate(self):
        self.assertEqual(core.score_job(job("Senior Associate Security Analyst"), CFG, SK)[1], "senior title")
        self.assertEqual(core.score_job(job("Senior Security Analyst"), CFG, SK)[0], 0)

    def test_entry_title_beats_senior_word(self):
        self.assertGreater(core.score_job(job("Security Analyst Trainee (Lead Gen team)"), CFG, SK)[0], 0)

    def test_breakdown_adds_up(self):
        parts, _ = core.score_parts(job("SOC Analyst", "monitor nmap alerts"), CFG, SK)
        self.assertEqual(min(round(sum(parts.values())), 99), core.score_job(job("SOC Analyst", "monitor nmap alerts"), CFG, SK)[0])

    def test_age_formats(self):
        self.assertEqual(core._age_hours("3 days ago"), 72)
        self.assertEqual(core._age_hours("garbage"), 72)
        self.assertLess(core._age_hours(datetime.now().isoformat()), 1)
        self.assertGreater(core._age_hours("2020-01-01"), 24 * 365)

    def test_blocklist(self):
        cfg = {**CFG, "matching": {**CFG["matching"], "exclude_companies": ["acme"]}}
        self.assertEqual(core.rank([job("Security Analyst", "nmap")], cfg, SK), [])
        cfg = {**CFG, "matching": {**CFG["matching"], "exclude_keywords": ["night shift"]}}
        self.assertEqual(core.rank([job("Security Analyst", "night shift only")], cfg, SK), [])

    def test_rank_dedupes(self):
        out = core.rank([job("Security Analyst", "nmap", apply_url="a"), job("Security Analyst", "nmap", apply_url="b")], CFG, SK)
        self.assertEqual(len(out), 1)


class Salary(unittest.TestCase):
    def test_found(self):
        self.assertEqual(core.extract_salary("Pay: Rs. 4-6 LPA"), "Rs. 4-6 LPA")
        self.assertEqual(core.extract_salary("$80,000 a year"), "$80,000 a year")

    def test_not_found(self):
        self.assertEqual(core.extract_salary("5 years of experience, 24x7 shifts"), "")
        self.assertEqual(core.extract_salary(""), "")


class Urls(unittest.TestCase):
    def test_canon(self):
        self.assertEqual(core.canon_url("https://in.linkedin.com/jobs/view/1?refId=a&trackingId=b"), "https://in.linkedin.com/jobs/view/1")
        self.assertEqual(core.canon_url("https://x.com/j?jobId=9&utm_source=a"), "https://x.com/j?jobId=9")
        self.assertEqual(core.canon_url(None), "")


class Tracking(unittest.TestCase):
    def test_save_dedup_and_status(self):
        with tempfile.TemporaryDirectory() as d:
            t = core.Tracker(os.path.join(d, "j.db"))
            j = {**job("A", "x"), "score": 80}
            self.assertEqual(t.save([j]), 1)
            self.assertEqual(t.save([{**j, "score": 85}]), 0)
            self.assertEqual(t.all()[0][0], 85)
            t.mark(j["apply_url"], "applied")
            self.assertEqual(t.pending(10), [])
            t.db.close()

    def test_schema_migrates_old_db(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "old.db")
            c = sqlite3.connect(p)
            c.execute("CREATE TABLE jobs(apply_url TEXT PRIMARY KEY, title TEXT, company TEXT, score INT, status TEXT, data TEXT, updated TEXT)")
            core.ensure_schema(c)
            cols = [r[1] for r in c.execute("PRAGMA table_info(jobs)")]
            self.assertIn("notes", cols); self.assertIn("starred", cols)
            c.close()


class Config(unittest.TestCase):
    def good(self):
        return {"profile": {"resume_path": os.path.join(ROOT, "README.md"), "full_name": "Real Person"},
                "search": CFG["search"], "sources": [], "apply": {"mode": "assist"}, "matching": CFG["matching"]}

    def test_valid(self):
        core.validate_cfg(self.good())

    def test_bad_weights(self):
        c = self.good(); c["matching"] = {**CFG["matching"], "weights": {**CFG["matching"]["weights"], "title": 50}}
        with self.assertRaises(SystemExit): core.validate_cfg(c)

    def test_placeholder_name_and_missing_resume(self):
        c = self.good(); c["profile"]["full_name"] = "YOUR NAME"
        with self.assertRaises(SystemExit): core.validate_cfg(c)
        c = self.good(); c["profile"]["resume_path"] = "nope.docx"
        with self.assertRaises(SystemExit): core.validate_cfg(c)

    def test_local_override(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "config.yaml"), "w").write("profile: {full_name: A, email: a@b}\nsearch: {titles: [x]}\nmatching: {min_score: 70}\n")
            open(os.path.join(d, "config.local.yaml"), "w").write("profile: {full_name: Real}\n")
            cfg = core.load_cfg(os.path.join(d, "config.yaml"), os.path.join(d, "none.json"))
            self.assertEqual(cfg["profile"], {"full_name": "Real", "email": "a@b"})


class FieldMatching(unittest.TestCase):
    def test_matches(self):
        for label, key in [("first name", "first"), ("Email address", "email"), ("mobile number", "phone"),
                           ("last name", "last"), ("notice period", "notice_period")]:
            self.assertEqual(applier.match_field(label), key, label)

    def test_ambiguous_left_alone(self):
        for label in ("company name", "referrer email", "current employer location", "manager phone"):
            self.assertIsNone(applier.match_field(label), label)


class Insights(unittest.TestCase):
    def test_followups(self):
        rows = [{"apply_url": "u", "title": "t", "company": "c", "status": "applied", "updated": "2026-11-01T10:00:00"},
                {"apply_url": "v", "title": "t", "company": "c", "status": "new", "updated": "2026-11-01T10:00:00"}]
        out = insights.followups(rows, 7, datetime(2026, 11, 17))
        self.assertEqual([x["apply_url"] for x in out], ["u"])

    def test_analytics_empty_and_rate(self):
        self.assertEqual(insights.analytics([])["response_rate"], 0)
        a = insights.analytics([{"status": "interview", "score": 80, "company": "C", "updated": "2026-11-01 10:00:00"},
                                {"status": "applied", "score": 75, "company": "C", "updated": "2026-11-02 10:00:00"}])
        self.assertEqual(a["response_rate"], 50)

    def test_prep_has_sections(self):
        p = insights.prep_questions({"company": "Acme", "matched": ["nmap"], "missing": ["aws"]})
        self.assertTrue(p["technical"] and p["gaps"] and "Acme" in p["general"][4])


class Export(unittest.TestCase):
    def test_csv_safe(self):
        self.assertEqual(csv_safe("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(csv_safe("Analyst"), "Analyst")
        self.assertEqual(csv_safe(None), "")


if __name__ == "__main__":
    unittest.main()
