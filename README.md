# SMC Backtest Journal

This is my Smart Money Concepts (SMC) Trading Journal. It runs locally (Python), as a single-file Windows exe, or on Render.

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

1. Push this project to GitHub.
2. In Render, create a new Web Service → Import from GitHub and select the repo/branch.
3. Use these settings:
	- Environment: `Python`
	- Build command: `pip install -r requirements.txt`
	- Start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
4. Add environment variables in Render dashboard:
	- `DATABASE_URL` (Postgres connection string)
	- `SECRET_KEY`
5. Optionally include `render.yaml` in the repo — Render will use it when importing the service.

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

If you want this README adjusted for a different host or to include a Dockerfile, tell me what you prefer.

Set the following environment variables in the service settings on Render:
- `DATABASE_URL` — full SQLAlchemy/Postgres URL (e.g., `postgresql://user:pass@host:5432/dbname?sslmode=require`).
- `SECRET_KEY` — a strong random secret.

The app exposes a `/webhook` POST endpoint for TradingView and a small admin API for settings and trade CRUD.

## Database & Connectivity Tips
- `DATABASE_URL` handling: if the URL lacks `sslmode`, the code appends `sslmode=require` automatically for Postgres.
- Local fallback: with no `DATABASE_URL` the app creates `smc_backtest.db` in the working folder or next to the exe when frozen.
- Troubleshooting connection issues: common problems are DNS resolution and outbound port (5432) blocking. Useful CLI checks:

```powershell
nslookup <db-host>
Test-NetConnection -ComputerName <db-host> -Port 5432
tracert <db-host>
```

If DNS fails from your machine, try switching to a public resolver (e.g., 8.8.8.8) or test from a cloud host.

## Smoke Tests
Run these quick checks after installing dependencies:

```bash
python -c "from database import init_db, get_pairs; init_db(); print('Pairs:', get_pairs())"
python -c "from app import app; print('Flask app OK:', app.name)"
```

## Files of Interest
- `app.py` — Flask routes, validation and webhook receiver
- `database.py` — SQLAlchemy Core engine, table definitions and CRUD helpers
- `launcher.py` — Local launcher that opens browser and starts the app
- `build_desktop.py` — PyInstaller build helper used to create `dist/SMC_Journal.exe`
- `render.yaml`, `Procfile` — deployment helpers for Render
