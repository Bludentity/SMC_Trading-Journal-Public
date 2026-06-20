# SMC Backtest Journal

SMC Backtest Journal is a compact web-based backtesting trading journal focused on Smart Money Concepts (SMC).

Overview (technical)
- Python Flask app serving a single-page UI; data stored in SQLite by default or Postgres when `DATABASE_URL` is set.
- Key modules:
	- `app.py` — Flask routes and validation logic.
	- `trade_views.py` — trade detail pages, screenshots, and export endpoints.
	- `database.py` — DB schema and persistence layer (SQLAlchemy). Handles local DB and Postgres via `DATABASE_URL`.
	- `launcher.py` — runtime helper used by the desktop exe to set a writable data dir and start the Flask app.
- Desktop packaging uses PyInstaller (build scripts provided).

Project layout (important files)
- `app.py` — main Flask app and validation
- `trade_views.py` — blueprint serving trade detail pages and upload endpoints
- `database.py` — schema and DB helpers
- `templates/` — HTML templates (`index.html`, `trade_details.html`)
- `static/` (optional) — static assets
- `scripts/` — helper scripts for creating desktop shortcuts and inspecting runtime state
- `build_desktop.py` / `SMC_Journal.spec` — packaging helpers

Quick start (local)
1. Create and activate a virtual environment, then install dependencies:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
```

2. Start the app via the launcher (opens the UI in your default browser):

```bash
python launcher.py
```

3. Verify the server is running:

```bash
curl -i http://127.0.0.1:5000/api/trades
```

Local vs Remote DB
- Local (default): when `DATABASE_URL` is not configured the app uses a local SQLite DB named `smc_backtest.db` stored in the working directory or the runtime `DATA_DIR` chosen by `launcher.py` (typically `%LOCALAPPDATA%\SMC_Journal` on Windows when using the exe).
- Remote Postgres: set `DATABASE_URL` (standard SQLAlchemy URI). Example `.env` containing runtime configuration placed beside the exe or in your environment:

```
SECRET_KEY=<pick-a-secret>
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

Desktop exe (Windows)
- Build (requires PyInstaller):

```bash
python build_desktop.py --icon icon.ico --name SMC_Journal
```

- Deployment: copy the produced `SMC_Journal.exe` to a writable location such as `%LOCALAPPDATA%\SMC_Journal`, place a `.env` file there if you use Postgres, and create a desktop shortcut. `scripts/set_shortcut_local.ps1` automates creating the shortcut and launching the exe.

Deploy to Render / Railway
- Both providers run the Flask app the same way. Use `gunicorn` in your service start command:

```
gunicorn app:app --bind 0.0.0.0:$PORT
```

- Set the required env vars in the provider dashboard: `DATABASE_URL`, `SECRET_KEY`, and any other runtime flags your deployment needs.

Exporting data to AI
- Use the `/api/export` endpoint to generate an AI-friendly data payload. The UI also exposes an `Export AI File` action that saves a text export to the runtime `exports/` folder.

Testing and validation
- Basic smoke test: ensure `GET /api/trades` returns 200 and JSON.
- The codebase includes validation for trade fields; dynamic entry zones accept `null`, empty, a dict, or a JSON string (the UI treats `N/A` as no value).

Cleaning and preparing to push (For contributors)
- The repo should not contain build artifacts, local DBs, or runtime files. Recommended files to leave out of VCS (already in `.gitignore`):
	- `dist/`, `build/`, `*.spec`, `*.exe`
	- `smc_backtest.db`, `*.db`
	- `uploads/`, `exports/`, `errors.log`
	- `.env`, `.env.local`

Troubleshooting
- If the desktop exe does not start, check `%LOCALAPPDATA%\SMC_Journal\errors.log` for tracebacks.
- If deployment cannot connect to Postgres, verify `DATABASE_URL`, firewall rules, and that your cloud provider allows outbound DB connections.

Further notes
- The app is intentionally small and uses server-side validation in `app.py` and controlled storage normalization in `database.py`.

---

