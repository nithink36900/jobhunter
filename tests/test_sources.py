import sys, types, unittest
from app import core

NAUKRI = {"title": "SOC Analyst - L1", "url": "https://www.naukri.com/job-listings-soc-analyst-l1-123",
          "company.name": "Prudent Globaltech Solutions", "experience.text": "0-2 Yrs", "salary.label": "Not Disclosed",
          "description.short": "Splunk and SIEM knowledge|Monitor security events, alert triage", "createdDateText": "2026-11-16 10:42:21",
          "applyCount": 261, "locations": [{"label": "Hyderabad"}, {"label": "Chennai"}]}
INDEED = {"title": "Security Analyst", "url": "https://in.indeed.com/viewjob?jk=1", "jobUrl": "https://careers.example.com/j/1",
          "employer": {"name": "Google"}, "location": {"city": "", "countryName": "India"}, "datePublished": "2026-11-10T06:00:00.000Z",
          "baseSalary": {"min": 600000, "max": 900000, "currencyCode": "INR", "unitOfWork": "YEAR"},
          "description": {"text": "SOC and incident response with python"}}
LINKEDIN = {"title": "Cyber Analyst", "companyName": "CGI", "location": "Bengaluru", "jobUrl": "https://linkedin.com/jobs/view/1?refId=x",
            "applyUrl": "https://cgi.example/apply", "description": "nmap", "postedTime": "2 days ago", "applicationsCount": "Over 200 applicants"}


class Normalise(unittest.TestCase):
    def test_naukri(self):
        j = core.normalise(NAUKRI)
        self.assertEqual((j["company"], j["level"], j["applicants"], j["location"]), ("Prudent Globaltech Solutions", "0-2 Yrs", 261, "Hyderabad, Chennai"))
        self.assertEqual(j["pay"], "")  # "Not Disclosed" is not a salary
        self.assertIn("Splunk", j["description"])

    def test_indeed(self):
        j = core.normalise(INDEED)
        self.assertEqual((j["company"], j["location"], j["apply_url"]), ("Google", "India", "https://careers.example.com/j/1"))
        self.assertTrue(j["pay"].startswith("INR 600000-900000") and j["pay"].endswith("per year"))
        self.assertIn("incident response", j["description"])

    def test_linkedin_unchanged(self):
        j = core.normalise(LINKEDIN)
        self.assertEqual((j["company"], j["apply_url"], j["job_url"]), ("CGI", "https://cgi.example/apply", "https://linkedin.com/jobs/view/1"))

    def test_experience_range_scores_as_entry_level(self):
        cfg = {"search": {"titles": ["SOC Analyst"], "preferred_locations": ["hyderabad"]},
               "matching": {"exclude_title_words": [], "max_years_experience": 2,
                            "weights": {"title": 30, "skills": 30, "level": 15, "location": 10, "recency": 10, "competition": 5}}}
        mk = lambda lvl: {**core.normalise(NAUKRI), "level": lvl}
        low, high = core.score_parts(mk("0-2 Yrs"), cfg, ["splunk"])[0], core.score_parts(mk("5-8 Yrs"), cfg, ["splunk"])[0]
        self.assertEqual(low["level"], 15)
        self.assertLess(high["level"], 5)


class FetchRuns(unittest.TestCase):
    def setUp(self):
        self.calls = []
        calls, items = self.calls, {"a/linkedin": [LINKEDIN], "a/naukri": [NAUKRI], "a/indeed": [INDEED]}

        class Client:
            def __init__(self, token): pass
            def actor(self, name):
                class A:
                    def call(_, run_input): calls.append((name, run_input)); return {"defaultDatasetId": name}
                return A()
            def dataset(self, name):
                class D:
                    def iterate_items(_):
                        if name == "a/indeed" and any(c[0] == "a/indeed" and c[1]["title"] == "VAPT" for c in calls[-1:]):
                            raise RuntimeError("boom")
                        return iter(items[name])
                return D()
        sys.modules["apify_client"] = types.SimpleNamespace(ApifyClient=Client)

    def cfg(self):
        return {"profile": {"years_experience": "0"},
                "search": {"titles": ["SOC Analyst", "VAPT", "Pentester", "Extra"], "locations": ["Hyderabad, Telangana, India", "India"],
                           "rows_per_search": 10, "posted_within": "r2592000", "experience_levels": ["1", "2"]},
                "sources": [
                    {"name": "linkedin", "enabled": True, "actor": "a/linkedin", "input_template": {"titles": "{titles}", "rows": "{rows}"}},
                    {"name": "naukri", "enabled": True, "actor": "a/naukri", "max_titles": 3, "locations": ["Hyderabad"],
                     "input_template": {"keywords": "{title}", "location": "{location}", "jobAge": "{days}", "experience": "{years}", "limit": "{rows}"}},
                    {"name": "indeed", "enabled": True, "actor": "a/indeed", "max_titles": 3, "locations": ["Hyderabad"],
                     "input_template": {"title": "{title}", "location": "{location}", "datePosted": "{days14}", "limit": "{rows}"}}]}

    def test_expansion_and_inputs(self):
        core.fetch_jobs(self.cfg(), token="x", log=lambda *a: None)
        by = {}
        for n, i in self.calls: by.setdefault(n, []).append(i)
        self.assertEqual(len(by["a/linkedin"]), 1)
        self.assertEqual(by["a/linkedin"][0]["titles"], ["SOC Analyst", "VAPT", "Pentester", "Extra"])
        self.assertEqual([i["keywords"] for i in by["a/naukri"]], ["SOC Analyst", "VAPT", "Pentester"])  # capped at max_titles
        self.assertEqual(by["a/naukri"][0], {"keywords": "SOC Analyst", "location": "Hyderabad", "jobAge": "30", "experience": 0, "limit": 10})
        self.assertEqual(by["a/indeed"][0]["datePosted"], "14")  # 30 days clamps to Indeed's maximum

    def test_one_failed_run_keeps_the_rest(self):
        jobs = core.fetch_jobs(self.cfg(), token="x", log=lambda *a: None)
        self.assertEqual({j["source"] for j in jobs}, {"linkedin", "naukri", "indeed"})
        self.assertEqual(sum(j["source"] == "indeed" for j in jobs), 2)  # the VAPT run failed, the other two worked


class Vocabulary(unittest.TestCase):
    def test_custom_words(self):
        core._apply_vocab({"skills": ["Kubernetes"], "role_words": ["devops"]})
        self.assertIn("kubernetes", core.job_terms("we use Kubernetes daily"))
        self.assertIn("devops", core.ROLE_WORDS)
        core.SKILL_VOCAB.remove("kubernetes"); core.ROLE_WORDS.remove("devops")


if __name__ == "__main__":
    unittest.main()
