# SMC Backtest Journal

This is a Smart Money Concepts (SMC) Trading Journal. It runs locally (Python), as a single-file Windows exe, or on Render.

Prerequisites
- Python 3.10+ (3.11/3.13 tested)
- `pip` and a virtual environment
- For Postgres: working `DATABASE_URL` and outbound access to the DB host on port 5432

Local quick start
1. Create a virtual environment and install deps:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
```

2. Start the app (launcher opens the UI in your browser):

```bash
python launcher.py
```

3. Smoke test (confirm DB + server):

```bash
python -c "from database import init_db, get_pairs; init_db(); print('Pairs:', get_pairs())"
curl -i http://127.0.0.1:5000/
```

Desktop build (Windows exe)
- Build single-file exe (PyInstaller required):

```bash
python build_desktop.py --icon icon.ico --name SMC_Journal
```

- Place a `.env` next to `SMC_Journal.exe` to connect to Postgres at runtime. Example `.env`:

```
SECRET_KEY=replace-with-a-strong-secret
DATABASE_URL=postgresql://user:password@host:5432/dbname?sslmode=require
```

Render deployment (direct, fast)
Follow these exact steps to deploy from a GitHub repo to Render:

1. Clone this repo.
2. In Render, create a new Web Service → Import from GitHub and select the cloned repo/branch.
3. Use these settings:
	- Environment: `Python`
	- Build command: `pip install -r requirements.txt`
	- Start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
4. Add environment variables in Render dashboard:
	- `DATABASE_URL` (Postgres connection string)
	- `SECRET_KEY`

Quick Render tips
- Use `render logs <service-name>` or the dashboard to view runtime logs.
- If DB connections fail, check DNS and outbound port 5432 from Render (Render generally has outbound DB access).

Webhooks & API
- `POST /webhook` accepts TradingView webhooks; payloads are queued in the DB for review in the UI.

Environment behavior
- If `DATABASE_URL` is set the app connects to Postgres; otherwise it creates and uses `smc_backtest.db` locally.
- For the frozen exe, the app looks for `.env` in the exe folder.

Troubleshooting
- DNS/connection checks (PowerShell):

```powershell
nslookup <db-host>
Test-NetConnection -ComputerName <db-host> -Port 5432
tracert <db-host>
```

- Generate a secure `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Data import example

```bash
python - <<'PY'
from database import import_tradingview_csv
csv = open('sample.csv','r',encoding='utf-8').read()
print(import_tradingview_csv(csv))
PY
```
