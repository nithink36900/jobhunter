"""Read a resume's text and work out the profile, skills and job titles to search for (pure functions)."""
import re

CITY_STATE = {
    "hyderabad": "Telangana", "warangal": "Telangana", "bengaluru": "Karnataka", "bangalore": "Karnataka",
    "mysuru": "Karnataka", "mysore": "Karnataka", "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu",
    "mumbai": "Maharashtra", "pune": "Maharashtra", "nagpur": "Maharashtra", "new delhi": "Delhi", "delhi": "Delhi",
    "noida": "Uttar Pradesh", "lucknow": "Uttar Pradesh", "gurugram": "Haryana", "gurgaon": "Haryana",
    "kolkata": "West Bengal", "ahmedabad": "Gujarat", "kochi": "Kerala", "thiruvananthapuram": "Kerala",
    "jaipur": "Rajasthan", "indore": "Madhya Pradesh", "chandigarh": "Chandigarh", "visakhapatnam": "Andhra Pradesh",
    "vijayawada": "Andhra Pradesh", "bhubaneswar": "Odisha",
    "tirupati": "Andhra Pradesh", "guntur": "Andhra Pradesh", "nellore": "Andhra Pradesh", "kakinada": "Andhra Pradesh",
    "rajahmundry": "Andhra Pradesh", "karimnagar": "Telangana", "nizamabad": "Telangana", "khammam": "Telangana",
    "madurai": "Tamil Nadu", "tiruchirappalli": "Tamil Nadu", "trichy": "Tamil Nadu", "salem": "Tamil Nadu", "vellore": "Tamil Nadu",
    "mangaluru": "Karnataka", "mangalore": "Karnataka", "hubballi": "Karnataka", "belagavi": "Karnataka",
    "surat": "Gujarat", "vadodara": "Gujarat", "rajkot": "Gujarat", "gandhinagar": "Gujarat", "bhopal": "Madhya Pradesh",
    "nashik": "Maharashtra", "thane": "Maharashtra", "navi mumbai": "Maharashtra", "aurangabad": "Maharashtra",
    "kanpur": "Uttar Pradesh", "agra": "Uttar Pradesh", "varanasi": "Uttar Pradesh", "ghaziabad": "Uttar Pradesh",
    "faridabad": "Haryana", "patna": "Bihar", "ranchi": "Jharkhand", "jamshedpur": "Jharkhand", "guwahati": "Assam",
    "dehradun": "Uttarakhand", "amritsar": "Punjab", "ludhiana": "Punjab", "mohali": "Punjab", "jodhpur": "Rajasthan",
    "udaipur": "Rajasthan", "raipur": "Chhattisgarh", "thrissur": "Kerala", "kozhikode": "Kerala", "panaji": "Goa",
    "pondicherry": "Puducherry", "puducherry": "Puducherry", "siliguri": "West Bengal",
}
# job title -> skills that point to it (tuned for security; add your own words under vocabulary: in config.yaml)
TITLES = {
    "Cybersecurity Analyst": {"threat detection", "vulnerability assessment", "siem", "soc", "incident response", "network security", "wireshark"},
    "Penetration Tester": {"penetration testing", "pentest", "metasploit", "burp suite", "nmap", "sqlmap", "kali", "exploit", "ethical hacking", "vapt"},
    "SOC Analyst": {"soc", "siem", "splunk", "qradar", "sentinel", "incident response", "threat detection", "edr"},
    "VAPT Analyst": {"vapt", "vulnerability assessment", "nessus", "owasp", "burp suite"},
    "Security Engineer": {"firewall", "network security", "cloud security", "iam", "encryption", "automation", "scripting"},
    "Application Security Engineer": {"appsec", "owasp", "web application security", "burp suite"},
    "Information Security Analyst": {"grc", "iso 27001", "access control", "vulnerability management", "iam"},
    "Digital Forensics Analyst": {"forensic", "malware", "steganography"},
    "Cloud Security Engineer": {"cloud security", "aws", "iam"},
    # other fields (matched against TECH words found in the resume)
    "Software Developer": {"python", "java", "javascript", "typescript", "c++", "c#", "git", "sql", "rest api"},
    "Web Developer": {"html", "css", "javascript", "react", "angular", "node.js", "php", "bootstrap"},
    "Frontend Developer": {"html", "css", "react", "angular", "javascript", "bootstrap", "vue.js"},
    "Full Stack Developer": {"react", "node.js", "mongodb", "javascript", "django", "sql", "angular"},
    "Python Developer": {"python", "django", "flask", "pandas"},
    "Java Developer": {"java", "spring boot", "mysql", "hibernate"},
    "Data Analyst": {"sql", "excel", "power bi", "tableau", "pandas", "data analysis", "data visualization"},
    "Data Scientist": {"machine learning", "deep learning", "tensorflow", "pytorch", "pandas", "numpy", "scikit-learn", "nlp"},
    "Machine Learning Engineer": {"machine learning", "deep learning", "tensorflow", "pytorch", "nlp"},
    "DevOps Engineer": {"docker", "kubernetes", "jenkins", "terraform", "ansible", "ci/cd", "aws", "linux"},
    "Cloud Engineer": {"aws", "azure", "gcp", "terraform", "kubernetes"},
    "QA Engineer": {"selenium", "manual testing", "automation testing", "postman", "jira"},
    "Android Developer": {"android", "kotlin", "flutter", "react native"},
    "UI/UX Designer": {"figma", "photoshop", "ui/ux"},
    "Digital Marketing Executive": {"seo", "digital marketing", "content writing"},
    "Accountant": {"tally", "accounting", "gst", "tds", "bookkeeping"},
    "HR Executive": {"recruitment", "payroll", "onboarding"},
    "Customer Support Executive": {"customer support", "crm", "customer service"},
    "Network Engineer": {"ccna", "cisco", "routing", "switching", "networking"},
}
# general tech and work skills (beyond the security words in core.SKILL_VOCAB) read from any resume
TECH = ["python", "java", "javascript", "typescript", "c++", "c#", "php", "ruby", "kotlin", "swift", "sql", "mysql", "postgresql",
        "mongodb", "oracle", "html", "css", "react", "angular", "vue.js", "node.js", "django", "flask", "spring boot", "hibernate",
        "bootstrap", "git", "github", "docker", "kubernetes", "jenkins", "terraform", "ansible", "ci/cd", "aws", "azure", "gcp",
        "linux", "excel", "power bi", "tableau", "pandas", "numpy", "scikit-learn", "machine learning", "deep learning",
        "tensorflow", "pytorch", "nlp", "data analysis", "data visualization", "figma", "photoshop", "ui/ux", "selenium",
        "manual testing", "automation testing", "postman", "jira", "agile", "scrum", "rest api", "android", "flutter",
        "react native", "seo", "digital marketing", "content writing", "tally", "accounting", "recruitment", "customer support",
        "gst", "tds", "bookkeeping", "payroll", "onboarding", "crm", "customer service", "ccna", "cisco", "routing", "switching", "networking"]


def tech_skills(text):
    low = text.lower()
    return [t for t in TECH if re.search(r"(?<![\w+#.])" + re.escape(t) + r"(?![\w+#])", low)]


_ROLE = r"(?:engineers?|developers?|analysts?|testers?|administrators?|architects?|consultants?|specialists?|designers?|scientists?|researchers?|programmers?|technicians?|executives?|officers?|trainees?|interns?|associates?|managers?)"
_TITLE_RX = re.compile(r"\b((?:[A-Za-z][\w+#/&.\-]*[ \t]+){0,3}" + _ROLE + r")\b", re.I)
_LEAD_STOP = set("a an the as and or of in at to for with by from on my our your their his her i we is was be been being am are role roles "
                 "position post job opening opportunity seeking seek looking aspiring experienced motivated passionate dedicated strong good great "
                 "new highly skilled certified qualified senior sr lead principal head chief entry level entry-level junior jr fresher graduate fresh experience education skills projects summary objective profile certifications achievements internship internships training working worked work currently currently-working "
                 "team project projects company companies college university school institute department client clients hiring technical "
                 "responsible applying applied apply used using use build built develop developed developing manage managed managing "
                 "that this which who whom into onto under over about also like such other any each every certain".split())


def _nice(w):
    return w if w.isupper() and len(w) <= 5 or not w.islower() else w[:1].upper() + w[1:]


def titles_in_text(text, limit=4):
    """Job titles the resume itself uses (headline, objective, experience, projects), most prominent first."""
    lines = [l for l in text.splitlines() if l.strip()]
    top = " ".join(lines[:6]).lower()
    score, shown = {}, {}
    for m in _TITLE_RX.finditer(text):
        words = m.group(1).split()
        while len(words) > 1 and words[0].lower().strip(".,:;") in _LEAD_STOP:
            words = words[1:]
        if len(words) < 2 or any(re.search(r"\d", w) for w in words) or len(" ".join(words)) > 40:
            continue
        if any(w.lower().strip(".,:;") in _LEAD_STOP for w in words[:-1]):
            continue
        words[-1] = re.sub(r"s$", "", words[-1], flags=re.I) if re.search(r"s$", words[-1], re.I) and not re.search(r"(?i)ss$", words[-1]) else words[-1]
        title = " ".join(_nice(w.strip(".,:;")) for w in words)
        key = title.lower()
        score[key] = score.get(key, 0) + 1 + (3 if key in top else 0)
        shown.setdefault(key, title)
    return [shown[k] for k, _ in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))][:limit]


_NOT_NAME = re.compile(r"resume|curriculum|vitae|objective|summary|profile|contact|career|education|skills|@|\d|http|www", re.I)


def _name(lines):
    for line in lines[:8]:
        l = line.strip(" \t|-•*·,:")
        words = l.split()
        if 2 <= len(words) <= 4 and not _NOT_NAME.search(l) and all(re.fullmatch(r"[A-Za-z.'\-]+", w) for w in words):
            return l.title() if l.isupper() else l
    return ""


def _phone(text):
    m = re.search(r"(?<!\d)(?:\+?91[\s\-]?)?0?([6-9]\d{4}[\s\-]?\d{5})(?!\d)", text)
    if m:
        return re.sub(r"\D", "", m.group(1))
    for m in re.finditer(r"\+?\d[\d\s\-()]{8,16}\d", text):
        d = re.sub(r"\D", "", m.group(0))
        if 10 <= len(d) <= 13 and not re.fullmatch(r"(19|20)\d{2}\D*(19|20)\d{2}", m.group(0)):
            return ("+" if m.group(0).lstrip().startswith("+") else "") + d
    return ""


_PLACE = r"[A-Za-z][A-Za-z .]{1,28}"


def _place(lines, text):
    """(city, state): a known city first, else one written as 'Location: City, State' or on the contact line."""
    rx = re.compile(r"\b(" + "|".join(sorted(map(re.escape, CITY_STATE), key=len, reverse=True)) + r")\b", re.I)
    m = rx.search("\n".join(lines[:12])) or rx.search(text)
    if m:
        c = m.group(1).title()
        return c, CITY_STATE[c.lower()]
    for line in lines[:15]:
        lab = re.match(r"(?:current\s+)?(?:location|address|city|place|residence)\s*[:\-]\s*(.+)$", line, re.I)
        parts = [p.strip(" .") for p in re.split(r",", re.sub(r"\d{5,}.*$", "", lab.group(1)))] if lab else []
        if not lab and ("@" in line or re.search(r"\d{10}", re.sub(r"[\s\-]", "", line))):  # a contact line: 'City, State | phone | email'
            for seg in re.split(r"[|•·]", line):
                if "@" not in seg and re.fullmatch(_PLACE + r",\s*" + _PLACE, seg.strip()):
                    parts = [p.strip(" .") for p in seg.split(",")]
                    break
        if parts and re.fullmatch(_PLACE, parts[0]) and len(parts[0].split()) <= 3:
            return parts[0].title(), (parts[1].title() if len(parts) > 1 and re.fullmatch(_PLACE, parts[1]) else "")
    return "", ""


def _grad_year(text):
    m = re.search(r"(?:graduat\w*|expected|batch|class of|pass(?:ing|ed)?\s*out)[^\n]{0,40}?\b(20\d\d)\b", text, re.I)
    if m:
        return m.group(1)
    deg = r"(?:b\.?\s?tech|b\.?\s?e\b|b\.?\s?sc|b\.?\s?com|bca|bba|m\.?\s?tech|m\.?\s?sc|mca|mba|bachelor|master|diploma|degree)"
    m = re.search(deg + r"[^\n]{0,80}?\b20\d\d\s*(?:-|–|to)\s*(20\d\d)\b", text, re.I) or re.search(deg + r"[^\n]{0,80}?\b(20\d\d)\b", text, re.I)
    if m:
        return m.group(1)
    spans = re.findall(r"\b(20\d\d)\s*(?:-|–|to)\s*(20\d\d)\b", text)
    return str(max(int(b) for _, b in spans)) if spans else ""


def _years(text):
    ys = [float(x) for x in re.findall(
        r"(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:professional\s+|work\s+)?(?:experience|exp)\b", text, re.I)]
    return str(int(max(ys))) if ys else "0"


def suggest_titles(skills, text, limit=6):
    """Titles from the resume's own words first, then roles its skills point to. Nothing is invented from other resumes."""
    have = set(skills) | set(tech_skills(text))
    low, scored = text.lower(), []
    for title, needs in TITLES.items():
        s = len(needs & have) + (2 if title.lower() in low else 0)
        if s >= 2:
            scored.append((s, title))
    best = max((s for s, _ in scored), default=0)
    skill_titles = [t for s, t in sorted(scored, key=lambda x: (-x[0], x[1])) if s >= best / 2]  # drop weak side matches
    out = []
    for t in titles_in_text(text)[:3] + skill_titles:
        if t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out[:limit]


def keyword_titles(skills, text, limit=3):
    """Last resort when no role can be told: search by the resume's own strongest skills."""
    words = list(dict.fromkeys(list(skills) + tech_skills(text)))
    return [w.upper() if len(w) <= 4 and w.isalpha() else w.title() for w in words[:limit]]


def extract_profile(text, skills):
    """Everything we could read from the resume. Only fields that were actually found are returned."""
    lines = [l for l in (x.strip() for x in text.splitlines()) if l]
    flat = " ".join(lines)
    prof = {
        "full_name": _name(lines),
        "email": (re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text) or [""])[0],
        "phone": _phone(text),
        "linkedin": (re.search(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w\-%]+", text, re.I) or [""])[0],
        "github": (re.search(r"(?:https?://)?github\.com/[\w\-]+", text, re.I) or [""])[0],
        "graduation_year": _grad_year(text),
        "years_experience": _years(flat),
    }
    for k in ("linkedin", "github"):
        if prof[k] and not prof[k].startswith("http"):
            prof[k] = "https://" + prof[k]
    city, state = _place(lines, text)
    out = {"profile": {k: v for k, v in prof.items() if v}, "skills": skills, "titles": suggest_titles(skills, text)}
    if not out["titles"]:
        out["titles"], out["titles_are_keywords"] = keyword_titles(skills, text), True
    if city:
        india = city.lower() in CITY_STATE
        out["profile"].update({"city": city, **({"state": state} if state else {}), **({"country": "India"} if india else {})})
        place = ", ".join(x for x in (city, state, "India" if india else "") if x)
        out["locations"] = [place] + (["India"] if india else [])
        out["preferred_locations"] = [x.lower() for x in (city, state) if x] + ["remote"]
    yrs = int(prof["years_experience"])
    out["experience_levels"] = ["1", "2"] if yrs == 0 else ["2", "3"] if yrs <= 3 else ["3", "4"]
    return out
