"""Browser apply helper (Playwright).

assist mode: opens the application page, fills the standard fields, uploads the resume and
             waits for YOU to review and submit.
auto mode:   also clicks the final Submit button on simple company/ATS forms.
Sites in `manual_only_domains` (LinkedIn, Indeed, Naukri...) are only opened, never automated:
their terms forbid bots and accounts get banned.
"""
import os
import random
import re
import time
from urllib.parse import urlparse

FIELD_MAP = [  # (regex on label/name/placeholder, profile key)
    (r"first.?name", "first"), (r"last.?name|surname", "last"),
    (r"full.?name|^name$|your name", "full_name"), (r"e-?mail", "email"),
    (r"phone|mobile|contact number", "phone"), (r"city|location", "city"),
    (r"linkedin", "linkedin"), (r"github|portfolio|website", "github"),
    (r"notice", "notice_period"), (r"graduat|passing year", "graduation_year"),
    (r"experience.*years|years.*experience|total experience", "years_experience"),
    (r"cover.?letter|why .*(join|interest)|additional", "cover_letter"),
]


def cover_letter(cfg, job, skills):
    p = cfg["profile"]
    return p["cover_letter_template"].format(
        title=job["title"], company=job["company"], full_name=p["full_name"],
        skills=", ".join(s for s in skills if s in ("nmap", "metasploit", "burp suite", "wireshark", "vapt", "python")) or "VAPT")


def _values(cfg, letter):
    p = cfg["profile"]
    parts = p["full_name"].split()
    return {**p, "first": parts[0], "last": parts[-1], "cover_letter": letter}


def _label(page, el):
    txt = " ".join(filter(None, [el.get_attribute("aria-label"), el.get_attribute("placeholder"),
                                 el.get_attribute("name"), el.get_attribute("id")]))
    el_id = el.get_attribute("id")
    if el_id:
        lab = page.query_selector(f'label[for="{el_id}"]')
        if lab:
            txt += " " + lab.inner_text()
    return txt.lower()


def fill_form(page, cfg, letter, resume_abs):
    vals, filled = _values(cfg, letter), 0
    for el in page.query_selector_all("input:not([type=hidden]):not([type=submit]), textarea"):
        try:
            typ = (el.get_attribute("type") or "text").lower()
            if typ == "file":
                el.set_input_files(resume_abs)
                filled += 1
                continue
            if typ in ("checkbox", "radio") or not el.is_visible() or el.input_value():
                continue
            label = _label(page, el)
            for rx, key in FIELD_MAP:
                if re.search(rx, label) and vals.get(key):
                    el.fill(str(vals[key]))
                    filled += 1
                    break
        except Exception:
            continue
    return filled


def click_submit(page):
    for b in page.query_selector_all("button, input[type=submit]"):
        try:
            t = ((b.inner_text() or "") + (b.get_attribute("value") or "")).strip().lower()
            if re.fullmatch(r"(submit( application)?|apply( now)?|send application)", t) and b.is_visible():
                b.click()
                return True
        except Exception:
            continue
    return False


def run_applications(jobs, cfg, skills, tracker, log=print):
    from playwright.sync_api import sync_playwright
    a = cfg["apply"]
    resume_abs = os.path.abspath(cfg["profile"]["resume_path"])
    os.makedirs("data/letters", exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(a["browser_profile_dir"], headless=a["headless"])
        for n, job in enumerate(jobs[: a["max_per_run"]], 1):
            url = job["apply_url"]
            host = urlparse(url).netloc.lower()
            letter = cover_letter(cfg, job, skills)
            slug = re.sub(r"\W+", "_", f"{job['company']}_{job['title']}")[:60]
            open(f"data/letters/{slug}.txt", "w", encoding="utf-8").write(letter)
            log(f"\n[{n}] {job['title']} @ {job['company']}  ({job['score']}%)")
            page = ctx.new_page()
            try:
                page.goto(url, timeout=45000, wait_until="domcontentloaded")
                if any(d in host for d in a["manual_only_domains"]):
                    log("    manual-only site: opened for you. Cover letter saved in data/letters/")
                    input("    Apply in the browser, then press Enter (type 's' to skip): ")
                    tracker.mark(url, "opened_manual")
                else:
                    page.wait_for_timeout(3000)
                    log(f"    autofilled {fill_form(page, cfg, letter, resume_abs)} fields")
                    if a["mode"] == "auto" and click_submit(page):
                        page.wait_for_timeout(4000)
                        tracker.mark(url, "submitted_auto")
                        log("    submit clicked (verify in the browser / your email)")
                    else:
                        ans = input("    Review, submit yourself, then press Enter ('s' = skip): ")
                        tracker.mark(url, "skipped" if ans.strip().lower() == "s" else "applied")
            except Exception as e:
                log(f"    error: {e}")
                tracker.mark(url, "error")
            finally:
                page.close()
            time.sleep(random.uniform(*a["delay_seconds"]))
        ctx.close()
