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
}
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


def _city(lines, text):
    rx = re.compile(r"\b(" + "|".join(sorted(map(re.escape, CITY_STATE), key=len, reverse=True)) + r")\b", re.I)
    m = rx.search("\n".join(lines[:12])) or rx.search(text)
    return m.group(1).title() if m else ""


def _grad_year(text):
    m = re.search(r"(?:graduat\w*|b\.?\s?tech|b\.?\s?e\b|b\.?\s?sc|bca|m\.?\s?tech|mca|bachelor|expected|batch|class of)[^\n]{0,60}?\b(20\d\d)\b", text, re.I)
    if m:
        return m.group(1)
    spans = re.findall(r"\b(20\d\d)\s*(?:-|–|to)\s*(20\d\d)\b", text)
    return str(max(int(b) for _, b in spans)) if spans else ""


def _years(text):
    ys = [float(x) for x in re.findall(
        r"(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:professional\s+|work\s+)?(?:experience|exp)\b", text, re.I)]
    return str(int(max(ys))) if ys else "0"


def suggest_titles(skills, text, limit=6):
    have, low, scored = set(skills), text.lower(), []
    for title, needs in TITLES.items():
        s = len(needs & have) + (2 if title.lower() in low else 0)
        if s >= 2 or (s >= 1 and len(have) < 4):
            scored.append((-s, title))
    return [t for _, t in sorted(scored)][:limit]


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
    city = _city(lines, text)
    out = {"profile": {k: v for k, v in prof.items() if v}, "skills": skills, "titles": suggest_titles(skills, text)}
    if city:
        state = CITY_STATE[city.lower()]
        out["profile"].update({"city": city, "state": state, "country": "India"})
        out["locations"] = [f"{city}, {state}, India", "India"]
        out["preferred_locations"] = [city.lower(), state.lower(), "remote"]
    yrs = int(prof["years_experience"])
    out["experience_levels"] = ["1", "2"] if yrs == 0 else ["2", "3"] if yrs <= 3 else ["3", "4"]
    return out
