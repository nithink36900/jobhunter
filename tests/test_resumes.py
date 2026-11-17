import base64, io, os, shutil, tempfile, unittest, zipfile
import docx
from app.dashboard import server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_docx(*lines):
    d, buf = docx.Document(), io.BytesIO()
    for l in lines:
        d.add_paragraph(l)
    d.save(buf)
    return {"filename": "cv.docx", "data": base64.b64encode(buf.getvalue()).decode()}


PRIYA = ("PRIYA SHARMA", "Hyderabad, Telangana | priya@example.com", "Python, Nmap, Burp Suite, Metasploit, SIEM, Splunk, VAPT")
RAHUL = ("RAHUL VERMA", "Bengaluru, Karnataka | rahul@example.com", "AWS, cloud security, IAM, Python, encryption, firewall")


class MultiResume(unittest.TestCase):
    def setUp(self):
        self.tmp, self.cwd, self.root = tempfile.mkdtemp(), os.getcwd(), server.ROOT
        os.makedirs(os.path.join(self.tmp, "data"))
        shutil.copy(os.path.join(ROOT, "config.yaml"), self.tmp)
        os.chdir(self.tmp)
        server.ROOT = self.tmp
        self.addCleanup(lambda: (os.chdir(self.cwd), setattr(server, "ROOT", self.root), shutil.rmtree(self.tmp, True)))

    def ids(self, r):
        return {x["label"]: x["id"] for x in r["resumes"]}

    def test_add_switch_keeps_edits_rename_delete(self):
        a = server.save_resume({**make_docx(*PRIYA), "label": "Pentester"})
        self.assertEqual((a["profile"]["full_name"], a["resume"]), ("Priya Sharma", "Pentester"))
        self.assertEqual(a["resumes"][0]["file"], "cv.docx")  # the user's own file name, not the stored one
        server.save_profile({"notice_period": "15 days"})
        b = server.save_resume({**make_docx(*RAHUL), "label": "Cloud"})
        self.assertEqual((b["profile"]["full_name"], b["profile"]["city"]), ("Rahul Verma", "Bengaluru"))
        self.assertIn("Cloud Security Engineer", b["settings"]["titles"])
        ids = self.ids(b)
        back = server.resume_select({"id": ids["Pentester"]})
        self.assertEqual((back["profile"]["full_name"], back["profile"]["notice_period"]), ("Priya Sharma", "15 days"))
        self.assertEqual(server.resume_rename({"id": ids["Cloud"], "label": " Cloud   sec "})["resumes"][1]["label"], "Cloud sec")
        gone = server.resume_delete({"id": ids["Pentester"]})  # deleting the one in use falls back to the other
        self.assertEqual((len(gone["resumes"]), gone["profile"]["full_name"]), (1, "Rahul Verma"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "data", "resumes", ids["Pentester"] + ".json")))
        empty = server.resume_delete({"id": ids["Cloud"]})
        self.assertEqual((empty["resumes"], empty["resume"]), ([], ""))

    def test_legacy_single_resume_is_adopted(self):
        shutil.copy(os.path.join(self.tmp, "config.yaml"), os.path.join(self.tmp, "config.yaml.bak"))
        r = make_docx(*PRIYA)
        open(os.path.join(self.tmp, "data", "resume.docx"), "wb").write(base64.b64decode(r["data"]))
        server._write_json(os.path.join(self.tmp, "data", "profile.json"), {"full_name": "Priya Sharma", "resume_path": "data/resume.docx"})
        s = server.get_settings()
        self.assertEqual([x["label"] for x in s["resumes"]], ["My resume"])

    def test_rejects_bad_input_and_path_tricks(self):
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, "w") as z:
            z.writestr("xl/workbook.xml", "x")  # a zip that is not a Word file (e.g. a renamed spreadsheet)
        word = make_docx(*PRIYA)
        for bad in ({"filename": "a.exe", "data": "QUJD"}, {"filename": "a.docx", "data": base64.b64encode(b"nope").decode()}, {"filename": "a.docx", "data": "!!!"},
                    {"filename": "cv.pdf", "data": word["data"]}, {"filename": "cv.txt", "data": word["data"]}, {"filename": "cv.doc", "data": word["data"]},
                    {"filename": "cv.docx", "data": base64.b64encode(zbuf.getvalue()).decode()}):
            with self.assertRaises(ValueError, msg=bad["filename"]):
                server.save_resume(bad)
        self.assertEqual(server.get_settings()["resumes"], [])  # nothing was stored
        rd = os.path.join(self.tmp, "data", "resumes")
        self.assertEqual(os.listdir(rd) if os.path.isdir(rd) else [], [])  # no leftover files
        for fn in (server.resume_select, server.resume_delete):
            with self.assertRaises(ValueError):
                fn({"id": "../../etc/passwd"})
        server.save_resume(make_docx(*PRIYA))
        with self.assertRaises(ValueError):
            server.resume_rename({"id": "main", "label": "x"})

    def test_old_pdf_resume_is_not_adopted(self):
        open(os.path.join(self.tmp, "data", "resume.pdf"), "wb").write(b"%PDF-1.4")
        server._write_json(os.path.join(self.tmp, "data", "profile.json"), {"resume_path": "data/resume.pdf"})
        self.assertEqual(server.get_settings()["resumes"], [])

    def test_limit(self):
        for _ in range(server.MAX_RESUMES):
            server.save_resume(make_docx(*PRIYA))
        with self.assertRaises(ValueError):
            server.save_resume(make_docx(*PRIYA))


if __name__ == "__main__":
    unittest.main()
