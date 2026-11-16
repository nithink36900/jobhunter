"""Analytics, follow-up reminders, resume gaps and interview prep (pure functions, no network)."""
from collections import Counter
from datetime import date, datetime

APPLIED = ("applied", "submitted_auto", "interview", "offer", "rejected")
WAITING = ("applied", "submitted_auto")

QUESTIONS = {
    "nmap": "Which Nmap scan types would you use to map a network quietly, and what does each send?",
    "metasploit": "Walk through exploiting a known vulnerability with Metasploit, from module choice to post-exploitation.",
    "burp suite": "How do you use Burp Suite to find an IDOR or SQL injection in a web app?",
    "sqlmap": "When is sqlmap the wrong tool, and how do you confirm an injection by hand first?",
    "wireshark": "How would you spot data exfiltration or a port scan in a packet capture?",
    "python": "Describe a Python script you wrote to automate a security task. How did you handle errors and rate limits?",
    "linux": "How do you check for suspicious processes, users and cron jobs on a Linux host?",
    "kali": "Which Kali tools do you reach for during recon, and why those?",
    "vapt": "Describe your VAPT process end to end, and how you write a finding so developers can fix it.",
    "penetration testing": "Explain the phases of a penetration test and what you deliver at the end.",
    "owasp": "Pick three items from the OWASP Top 10 and explain how each is exploited and prevented.",
    "siem": "How do you tune a SIEM so analysts see fewer false positives without missing real attacks?",
    "splunk": "Write or describe a Splunk search to detect repeated failed logins followed by a success.",
    "soc": "Walk through how you triage an alert from first look to escalation or closure.",
    "incident response": "Describe the stages of incident response and what you do in the first 30 minutes of a suspected breach.",
    "firewall": "How does a stateful firewall differ from a stateless one, and how do you review a rule set?",
    "dns": "How can DNS be abused by attackers, and how would you detect it?",
    "tcp/ip": "Explain the TCP three-way handshake and how SYN floods and scans abuse it.",
    "encryption": "Explain symmetric versus asymmetric encryption and where each is used in TLS.",
    "cryptography": "What is the difference between hashing, encryption and signing? Give one use of each.",
    "malware": "How would you safely analyse a suspicious executable, and what would you look for first?",
    "forensic": "What is the order of volatility, and how do you preserve evidence?",
    "iam": "What is least privilege, and how do you audit excessive access in an organisation?",
    "cloud security": "What are the most common cloud misconfigurations, and how do you detect them?",
    "aws": "How would you secure an S3 bucket and the IAM role that accesses it?",
    "nessus": "How do you separate real vulnerabilities from false positives in a Nessus report?",
    "ceh": "Which part of your CEH preparation taught you the most, and what did you apply afterwards?",
    "ctf": "Describe a CTF challenge you solved. What was your approach, and what did you learn?",
    "blockchain": "What security risks are specific to blockchain applications or smart contracts?",
}
GENERAL = [
    "Tell me about yourself and why you chose security.",
    "How do you keep up with new vulnerabilities and attack techniques?",
    "Describe a time you were stuck on a technical problem. How did you get unstuck?",
    "How would you explain a serious vulnerability to a non-technical manager?",
    "Why do you want to work at this company, and what do you know about it?",
]


def prep_questions(job):
    """Questions built from the skills this job asks for: ones you have, ones you lack, and general ones."""
    have, lack = job.get("matched") or [], job.get("missing") or []
    q = lambda s: QUESTIONS.get(s) or f"Explain {s} and describe a time you used it or would use it."
    out = {
        "technical": [q(s) for s in have[:6]],
        "gaps": [f"{s}: {q(s)}" for s in lack[:4]],
        "general": GENERAL[:],
    }
    if job.get("company"):
        out["general"][4] = f"Why do you want to work at {job['company']}, and what do you know about them?"
    return out


def _when(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", ""))
    except ValueError:
        return None


def followups(jobs, days=7, today=None):
    """Applications still waiting after `days` days: the ones worth a polite follow-up."""
    now = today or datetime.now()
    out = []
    for j in jobs:
        t = _when(j.get("updated"))
        if j.get("status") in WAITING and t and (now - t).days >= days:
            out.append({"apply_url": j["apply_url"], "title": j["title"], "company": j["company"],
                        "days": (now - t).days, "status": j["status"]})
    return sorted(out, key=lambda x: -x["days"])


def analytics(jobs):
    n = len(jobs)
    by_status = Counter(j["status"] for j in jobs)
    applied = sum(by_status[s] for s in APPLIED)
    answered = by_status["interview"] + by_status["offer"] + by_status["rejected"]
    buckets = Counter(min(j["score"] // 10 * 10, 90) for j in jobs)
    weeks = Counter()
    for j in jobs:
        t = _when(j.get("updated"))
        if j["status"] in APPLIED and t:
            y, w, _ = t.isocalendar()
            weeks[f"{y}-W{w:02d}"] += 1
    demand, missing = Counter(), Counter()
    for j in jobs:
        demand.update((j.get("matched") or []) + (j.get("missing") or []))
        missing.update(j.get("missing") or [])
    return {
        "total": n,
        "by_status": dict(by_status),
        "applied": applied,
        "response_rate": round(100 * answered / applied) if applied else 0,
        "avg_score": round(sum(j["score"] for j in jobs) / n) if n else 0,
        "score_buckets": {f"{b}-{b + 9}" if b < 90 else "90+": buckets.get(b, 0) for b in range(0, 100, 10)},
        "top_companies": Counter(j["company"] for j in jobs if j["company"]).most_common(5),
        "per_week": sorted(weeks.items()),
        "top_demand": demand.most_common(8),
        "resume_gaps": missing.most_common(8),
    }
