# ⚡ SMC Backtest Journal — Architecture & Deployment

This repository holds a production-ready SMC Trading Journal designed to run in three modes:

- Local developer mode (run with Python locally)
- Desktop single-file Windows executable (PyInstaller)
- Cloud deployment (Render/Gunicorn)

The codebase uses SQLAlchemy for cross-database compatibility and `python-dotenv` for local configuration. If `DATABASE_URL` is present in your environment (or in a `.env` file placed next to the executable), the app will use PostgreSQL. Otherwise it gracefully falls back to a local `smc_backtest.db` SQLite file.

## Quick Start (Local)

1. Create and activate a Python virtual environment.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. Run the app locally (opens browser automatically):

```bash
python app.py
```

The site will be available at `http://127.0.0.1:5000`.

## Desktop Build (Single EXE)

1. Place any desired `.env` file next to the built `SMC_Journal.exe` if you want it to connect to a remote `DATABASE_URL` when running as an exe. Otherwise the exe will create and use `smc_backtest.db` locally.

2. Build the exe (from project root):

```bash
python build_desktop.py --icon icon.ico --name SMC_Journal
```

3. Copy `dist/SMC_Journal.exe` to your Desktop. Double-clicking the exe starts a local server and opens the UI in the default browser.

## Cloud / Render Deployment

Render and other cloud hosts expect a working web server. Use Gunicorn as the production WSGI server and set `DATABASE_URL` as an environment variable in the service settings.

Example `render` service command:

```bash
gunicorn --bind 0.0.0.0:$PORT app:app
```

Ensure you set the `PORT` env var and `DATABASE_URL` in Render. The `/webhook` endpoint listens for TradingView POSTs and stores them in the configured database.

## Environment

- `.env` optional file: supports `DATABASE_URL` and `PORT`.
- If `DATABASE_URL` points to PostgreSQL, SSL will be required automatically if `sslmode` is not present.
- Without `DATABASE_URL`, a local `smc_backtest.db` SQLite file is used.

## Building Blocks & Architecture

- `app.py` — Flask routes, validation, and webhook receiver. When executed as `__main__` it opens a browser automatically and respects `PORT`.
- `database.py` — SQLAlchemy Core-based schema and CRUD helpers. Uses a single code path for both SQLite and PostgreSQL, eliminating parameter marker differences.
- `templates/index.html` — Frontend UI with Tailwind CDN and vanilla JS.
- `build_desktop.py` — PyInstaller helper wrapper for reproducible exe builds.

## Security & Operational Notes

- Do NOT commit `.env` or the SQLite file to source control; `.gitignore` excludes them by default.
- For production, use managed Postgres (Render, RDS, etc.) and set `DATABASE_URL` in the service environment. The code will add `sslmode=require` when missing.

## Running Tests / Sanity Checks

Quick smoke checks:

```bash
python -c "from database import init_db, get_pairs; init_db(); print('Pairs:', get_pairs())"
python -c "from app import app; print('Flask app OK:', app.name)"
```

## Files of Interest

- `app.py` — Flask entrypoint and webhook handling
- `database.py` — SQLAlchemy Core engine, table definitions, CRUD
- `build_desktop.py` — PyInstaller build helper
- `templates/index.html` — frontend UI
- `.gitignore` — prevents secrets and DB leakage

If you want, I can also create a small `Procfile` and `render.yaml` to further simplify Render deployment.
