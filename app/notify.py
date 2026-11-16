"""Optional alerts for new matches: Telegram, or any Slack/Discord-style webhook. Never raises."""
import json
import os
import urllib.request


def _env(key, cfg_val=""):
    if cfg_val:
        return str(cfg_val).strip()
    if os.environ.get(key):
        return os.environ[key].strip()
    if os.path.exists(".env"):
        for line in open(".env", encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            if k.strip() == key:
                return v.strip().strip("\"'")
    return ""


def message(jobs, limit=10):
    lines = [f"JobHunter: {len(jobs)} new match{'es' if len(jobs) != 1 else ''}"]
    for j in sorted(jobs, key=lambda x: -x["score"])[:limit]:
        pay = f" | {j['salary']}" if j.get("salary") else ""
        lines.append(f"{j['score']}% {j['title']} @ {j['company']}{pay}\n{j['apply_url']}")
    return "\n\n".join(lines)


def _post(url, payload):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()


def send(cfg, jobs, log=print):
    """Returns True if at least one channel accepted the message."""
    n = cfg.get("notify") or {}
    if not jobs or not n.get("enabled"):
        return False
    text, sent = message(jobs), False
    hook = _env("NOTIFY_WEBHOOK", n.get("webhook_url"))
    tok, chat = _env("TELEGRAM_BOT_TOKEN", n.get("telegram_bot_token")), _env("TELEGRAM_CHAT_ID", n.get("telegram_chat_id"))
    if hook.startswith(("http://", "https://")):
        try:
            _post(hook, {"text": text, "content": text[:1900]})  # Slack reads text, Discord reads content
            sent = True
        except Exception as e:
            log(f"[notify] webhook failed: {e}")
    if tok and chat:
        try:
            _post(f"https://api.telegram.org/bot{tok}/sendMessage", {"chat_id": chat, "text": text[:4000]})
            sent = True
        except Exception as e:
            log(f"[notify] telegram failed: {e}")
    return sent
