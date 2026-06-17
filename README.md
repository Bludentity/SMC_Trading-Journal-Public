# ⚡ SMC Backtest Journal — Architecture, Status & Deployment

This repository implements a production-ready Smart Money Concepts (SMC) Trading Journal that runs in three modes:

- Local development (run with Python)
- Desktop single-file Windows executable (PyInstaller)
- Cloud deployment (Render / Gunicorn)

Core design choices
- Database abstraction with SQLAlchemy Core so the same code works with SQLite (local) and PostgreSQL (cloud).
- Configuration via `python-dotenv` — the app loads `.env` from the working directory or, for a bundled exe, from the exe folder.
- Web server: Flask for UI + API routes; `gunicorn` recommended for production.

Current status (most recent changes)
- `database.py` replaced with a SQLAlchemy-based dual-database routing layer (auto-falls back to `smc_backtest.db` when `DATABASE_URL` is not set).
- `build_desktop.py` helper added and used to produce `dist/SMC_Journal.exe` (single-file, no-console build).
- `Procfile` and `render.yaml` added for simple Render deployment.
- `requirements.txt` updated; added `pytz` and `psycopg2-binary` for Postgres support.

## Quick Start — Local (Developer)

1. Create and activate a virtual environment, then install dependencies:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
```

2. Start the app for development (launcher opens your browser):

```bash
python launcher.py
```

Open `http://127.0.0.1:5000` in your browser.

## Desktop (Single EXE)

1. Build the exe from the project root (requires PyInstaller):

```bash
python build_desktop.py --icon icon.ico --name SMC_Journal
```

2. Copy `dist/SMC_Journal.exe` to the folder where you want it to run (e.g., Desktop). If you want the exe to connect to a remote Postgres DB, place a `.env` file next to the exe containing `DATABASE_URL` and `SECRET_KEY`.

Notes about `.env` and the exe
- The frozen exe looks for `.env` in its folder. If `DATABASE_URL` is present it will attempt to connect to Postgres; otherwise it uses `smc_backtest.db`.
- If you use OneDrive for Desktop, be aware that syncing secrets may expose them to the cloud — prefer a non-synced folder for sensitive `.env` files.

## Cloud / Render Deployment

Recommended start command (Render / production):

```bash
gunicorn --bind 0.0.0.0:$PORT app:app
```

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

## Next actions
- Add your `DATABASE_URL` and `SECRET_KEY` to a `.env` (for local or cloud). For the desktop exe, put the `.env` next to `SMC_Journal.exe`.
- If you want, I can: test your `DATABASE_URL` connectivity, produce a Dockerfile, or prepare a Render-ready configuration with secrets masked.

---
If anything in this README is out of date for your environment, tell me what changed and I'll update it.
