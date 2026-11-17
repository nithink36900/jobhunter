import json, os, tempfile, unittest
from app import core, resume

TEXT = """PRIYA SHARMA
Hyderabad, Telangana | +91 98765 43210 | priya.sharma@example.com
linkedin.com/in/priya-sharma-sec | github.com/priyasec
EDUCATION
B.Tech in Computer Science, Expected Graduation 2026
SKILLS: Python, Nmap, Burp Suite, Metasploit, SIEM, Splunk, VAPT, incident response"""


class Extract(unittest.TestCase):
    def setUp(self):
        self.r = resume.extract_profile(TEXT, core.resume_skills(TEXT))
        self.p = self.r["profile"]

    def test_contact_details(self):
        self.assertEqual((self.p["full_name"], self.p["email"], self.p["phone"]), ("Priya Sharma", "priya.sharma@example.com", "9876543210"))
        self.assertEqual(self.p["linkedin"], "https://linkedin.com/in/priya-sharma-sec")
        self.assertEqual(self.p["github"], "https://github.com/priyasec")

    def test_place_and_study(self):
        self.assertEqual((self.p["city"], self.p["state"], self.p["graduation_year"]), ("Hyderabad", "Telangana", "2026"))
        self.assertEqual(self.r["locations"][0], "Hyderabad, Telangana, India")
        self.assertIn("hyderabad", self.r["preferred_locations"])

    def test_fresher_defaults(self):
        self.assertEqual(self.p["years_experience"], "0")
        self.assertEqual(self.r["experience_levels"], ["1", "2"])

    def test_titles_follow_skills(self):
        self.assertIn("Penetration Tester", self.r["titles"])
        self.assertIn("SOC Analyst", self.r["titles"])
        self.assertNotIn("Cloud Security Engineer", self.r["titles"])

    def test_experienced_levels(self):
        r = resume.extract_profile("Ravi Kumar\n4 years of experience in SOC\nsplunk siem", ["splunk", "siem", "soc"])
        self.assertEqual((r["profile"]["years_experience"], r["experience_levels"]), ("4", ["3", "4"]))

    def test_missing_fields_are_left_out_not_guessed(self):
        r = resume.extract_profile("Skills: python\nI like security", ["python"])
        self.assertEqual(r["profile"].get("email"), None)
        self.assertNotIn("city", r["profile"])
        self.assertNotIn("locations", r)

    def test_heading_is_not_a_name(self):
        self.assertEqual(resume.extract_profile("Curriculum Vitae\nAnil Rao\nanil@x.com", [])["profile"]["full_name"], "Anil Rao")


def read(text):
    return resume.extract_profile(text, core.resume_skills(text))


class TitlesFollowTheResume(unittest.TestCase):
    def test_other_fields_get_their_own_titles(self):
        dev = read("Arjun M\nPune, Maharashtra | a@x.com | 9988776655\nFull Stack Developer. Skills: React, Node.js, MongoDB, SQL, Git")
        self.assertIn("Full Stack Developer", dev["titles"])
        self.assertNotIn("SOC Analyst", dev["titles"])
        self.assertEqual(read("Sneha R\nProfile: Data Analyst. SQL, Excel, Power BI, Tableau, Pandas")["titles"], ["Data Analyst"])
        self.assertEqual(read("Kavya N\nkavya@x.com\nSkills: Tally, Accounting, GST, Excel")["titles"], ["Accountant"])

    def test_no_junk_across_lines_and_no_level_words(self):
        r = read("Dev\nSKILLS SQL\nEXPERIENCE Software Developer Intern\nAspiring entry level SOC Analyst")
        self.assertTrue(all("EXPERIENCE" not in t and "Entry" not in t for t in r["titles"]), r["titles"])
        self.assertIn("SOC Analyst", r["titles"])

    def test_weak_side_matches_are_dropped(self):
        self.assertNotIn("Software Developer", read("Profile: Data Analyst. SQL, Excel, Power BI, Tableau, Pandas, Python")["titles"])

    def test_keywords_when_no_role_is_clear(self):
        r = read("Manoj\nSkills: Python, Git")
        self.assertTrue(r["titles"])

    def test_non_it_jobs(self):
        self.assertIn("Staff Nurse", read("Anitha\nChennai | a@x.com | 9111122222\nStaff Nurse with 3 years in ICU.\nSkills: patient care, BLS")["titles"])
        self.assertIn("Mathematics Teacher", read("Suresh\nMathematics Teacher with 5 years teaching CBSE.\nSkills: lesson planning")["titles"])
        self.assertIn("Design Engineer", read("Ravi\nOBJECTIVE\nTo work as a Design Engineer in a reputed company.\nSkills: AutoCAD, SolidWorks")["titles"])

    def test_skills_line_is_the_last_resort(self):
        r = read("Meena\nmeena@x.com\nSkills: patient care, IV cannulation, wound dressing, BLS")
        self.assertEqual(r["titles"], ["patient care", "IV cannulation", "wound dressing"])
        self.assertTrue(r["titles_are_keywords"])

    def test_graduation_year_is_the_end_of_the_course(self):
        self.assertEqual(read("B.E. Information Technology, 2022 - 2024")["profile"]["graduation_year"], "2024")
        self.assertEqual(read("Expected Graduation 2026")["profile"]["graduation_year"], "2026")


class Places(unittest.TestCase):
    def test_location_line_and_contact_line(self):
        self.assertEqual(read("Kavya\nLocation: Tirupati, Andhra Pradesh\nk@x.com")["profile"]["city"], "Tirupati")
        r = read("Tom\nAustin, Texas | tom@x.com | +1 512 555 0142\nJava")
        self.assertEqual((r["profile"]["city"], r["profile"]["state"], r["locations"]), ("Austin", "Texas", ["Austin, Texas"]))
        self.assertNotIn("country", r["profile"])  # not assumed to be India

    def test_degree_line_is_not_a_city(self):
        self.assertNotIn("city", read("Raj\nraj@x.com 9000000001\nB.Tech, Computer Science\nSkills: Python")["profile"])


class ProfileFile(unittest.TestCase):
    def test_profile_json_overrides_config_and_survives_damage(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "data"))
            cfgp, setp = os.path.join(d, "config.yaml"), os.path.join(d, "data", "settings.json")
            open(cfgp, "w").write("profile: {full_name: YOUR NAME, email: a@b, resume_path: data/resume.docx}\nsearch: {titles: [x]}\nmatching: {min_score: 70}\n")
            json.dump({"full_name": "Real Name", "resume_path": "data/resume.pdf"}, open(os.path.join(d, "data", "profile.json"), "w"))
            cfg = core.load_cfg(cfgp, setp)
            self.assertEqual((cfg["profile"]["full_name"], cfg["profile"]["email"], cfg["profile"]["resume_path"]), ("Real Name", "a@b", "data/resume.pdf"))
            open(os.path.join(d, "data", "profile.json"), "w").write("{broken")
            self.assertEqual(core.load_cfg(cfgp, setp)["profile"]["full_name"], "YOUR NAME")  # damaged file ignored, no crash

    def test_city_only_sources_use_the_users_city(self):
        s = {"titles": ["A", "B"], "locations": ["Pune, Maharashtra, India", "India"]}
        run = core._runs({"input_template": {"q": "{title}", "l": "{location}"}, "city_only": True}, {}, s)
        self.assertEqual({r["location"] for r in run}, {"Pune"})


if __name__ == "__main__":
    unittest.main()
