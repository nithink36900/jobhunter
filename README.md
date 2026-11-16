# JobHunter

Reads your resume, finds matching jobs (via Apify), ranks them, helps you apply, and tracks everything in a web app.

## Quick start
- **Windows:** install Python (tick "Add python.exe to PATH"), then double-click **Start JobHunter.bat**. First run sets everything up, then the web app opens in your browser. Everything else (token, search, apply) is done inside the web app.
- **Mac / Linux:** run `./start.sh`.

See **READ ME FIRST.txt** for the step-by-step version.

---

## Features
- Three job sources out of the box: LinkedIn, Naukri and Indeed (Naukri/Indeed run once per title; see `sources:` in config.yaml)
- Add your own skills and role words under `vocabulary:` so it works outside cybersecurity
- Resume-based scoring with whole-word skill matching, senior-title filter, company and keyword blocklists
- Skill gap per job (skills you have vs. asked for), salary detection, resume-gap summary
- Web app: jobs list, search, sort, star, bulk status change, notes, cover letter, interview prep questions
- Insights tab: score spread, applications per week, reply rate, top companies, in-demand skills
- Follow-up reminders for applications with no reply after `followup_days`
- Alerts for new matches via Telegram or Slack/Discord webhook (`notify` in config.yaml)
- CSV export (`python run.py export` or the Export button), auto-repeat search (`python run.py watch --every 6`)

## Private details and tests
Your name, contact details and resume stay on your computer: copy `config.local.example.yaml` to `config.local.yaml` and fill it in. Both that file and `data/resume.*` are git-ignored.
Run the tests with `python -m unittest discover -s tests`. They also run on every push through GitHub Actions.
In `auto` apply mode, `apply.confirm_auto: true` asks y/n before each submit.

## Project layout
```
jobhunter/
├── Start JobHunter.bat   the only file you need to open (Windows)
├── start.sh              same for Mac / Linux
├── READ ME FIRST.txt     plain-language steps
├── run.py                command-line entry point (the launchers call this)
├── config.yaml         search, matching and apply settings (shared, no personal data)
├── config.local.yaml   YOUR name, email, phone, cover letter (private, git-ignored; copy from config.local.example.yaml)
├── requirements.txt
├── .env.example        copy to .env to save your Apify token (optional)
├── app/                code (no need to touch)
│   ├── cli.py          commands
│   ├── core.py         resume parsing, Apify fetch, scoring, tracker
│   ├── insights.py     analytics, follow-ups, interview prep
│   ├── notify.py       Telegram / webhook alerts
│   ├── applier.py      browser autofill / apply
│   └── dashboard/      server.py + index.html (the web app)
└── data/               your files and everything the tool creates
    ├── resume.docx     your resume (git-ignored, never uploaded; .pdf/.txt also work)
    ├── sample_jobs.json  test data
    ├── jobs.db, settings.json, matches.csv, matches.md, letters/   (created as you use it)
```

## Manual setup (only if you skip the launchers)
```
pip install -r requirements.txt
python -m playwright install chromium
```
Then put your token in `.env` (copy `.env.example`) or set `$env:APIFY_TOKEN="your_token"` in PowerShell.

## Commands
```
python run.py search       # fetch, score, save -> data/matches.csv + matches.md
python run.py apply        # work through saved jobs in the browser
python run.py run          # search + apply
python run.py status       # list tracked jobs
python run.py dashboard    # web dashboard at http://127.0.0.1:8765
python run.py search --offline data/sample_jobs.json   # try it with no Apify
```
Works from any folder. Daily run: cron `0 9 * * * python /path/to/jobhunter/run.py search`

## How applying works
- `assist` (default): opens the page, fills name/email/phone, uploads the resume, saves a cover letter to `data/letters/`, then waits for you to review and submit.
- `auto`: also clicks Submit on simple company/ATS forms.
- LinkedIn, Indeed, Naukri and Glassdoor are opened for manual apply only (`manual_only_domains`); automating them breaks their terms and can get your account banned.
- CAPTCHA, login-gated or multi-step forms may need manual finishing.

## Web app
```
python run.py dashboard      # then open http://127.0.0.1:8765
```
- **Overview:** totals, average match, pipeline bar (click a stage to filter) and your best matches still to apply.
- **Jobs:** search, sort and filter. Click any job for its full details, status, your own notes, a ready cover letter (with a copy button) and the job description.
- **Search:** one button runs a new job search and shows live progress.
- **Settings:** change job titles, locations, time window, experience level and minimum score without editing files. Saved to `data/settings.json` and used by both the web app and `python run.py search`.

Applying stays in the terminal (`python run.py apply`) because it opens a browser window for you to check each form.
The web app only listens on your own computer (127.0.0.1) and rejects requests from other websites.

## Add more job boards
In `config.yaml` enable a source, set its Apify `actor` and `input_template` (check that actor's input schema). Field names are normalised in `app/core.py` (`normalise`).
