"""SMC Journal web application.

Provides Flask routes for settings, trades, and exports.
"""

import json
import sys
from flask import Flask, request, jsonify, render_template, abort
from werkzeug.exceptions import HTTPException
from database import (
    init_db,
    insert_trade, get_all_trades, get_trade, delete_trade,
    queue_webhook, get_pending_webhooks, dismiss_webhook,
    generate_ai_export,
    get_pairs, add_pair, delete_pair,
    get_timeframes, add_timeframe, delete_timeframe,
    get_entry_modules, add_entry_module, delete_entry_module,
    get_reversal_levels, add_reversal_level, delete_reversal_level,
    import_tradingview_csv,
)
import threading
import webbrowser
import os
import logging
import traceback
import datetime

# Resource and data directory resolution
if getattr(sys, 'frozen', False):
    RESOURCE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
else:
    RESOURCE_DIR = os.getcwd()

def _select_writable_data_dir():
    smc_base = os.environ.get('SMC_BASE_DIR')
    if smc_base:
        return smc_base
    local = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    cand = os.path.join(local, 'SMC_Journal')
    try:
        os.makedirs(cand, exist_ok=True)
        return cand
    except Exception:
        return os.getcwd()

DATA_DIR = _select_writable_data_dir()
template_dir = os.path.join(RESOURCE_DIR, 'templates')
static_dir = os.path.join(RESOURCE_DIR, 'static') if os.path.exists(os.path.join(RESOURCE_DIR, 'static')) else None

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)

import json as _json
app.jinja_env.filters['fromjson'] = lambda s: _json.loads(s) if s else []

try:
    init_db()
except Exception:
    pass

# Register blueprint after app and filters are configured
from trade_views import trade_bp
app.register_blueprint(trade_bp)

log_path = os.path.join(DATA_DIR, "errors.log")
try:
    fh = logging.FileHandler(log_path)
    fh.setLevel(logging.ERROR)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh.setFormatter(fmt)
    app.logger.addHandler(fh)
    app.logger.setLevel(logging.INFO)
except Exception:
    sh = logging.StreamHandler()
    sh.setLevel(logging.ERROR)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh.setFormatter(fmt)
    app.logger.addHandler(sh)
    app.logger.setLevel(logging.INFO)

VALID_DIRECTIONS = {"Bullish", "Bearish"}
VALID_SESSIONS   = {"Asian", "London", "New York"}
VALID_OUTCOMES   = {"Win", "Loss", "Break-Even"}


# ── Page ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    # Render the UI with initial trades embedded so the dashboard shows
    # existing trades immediately on page load (useful when client-side
    # fetches fail or when the exe environment differs).
    try:
        trades = get_all_trades()
    except Exception:
        trades = []
    return render_template("index.html", initial_trades=json.dumps(trades))


# ── Settings: Pairs ───────────────────────────────────────────────────────────

@app.route("/api/settings/pairs", methods=["GET"])
def api_get_pairs():
    return jsonify(get_pairs())

@app.route("/api/settings/pairs", methods=["POST"])
def api_add_pair():
    name = (request.get_json(force=True) or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "Pair name is required."}), 400
    return jsonify({"pair": add_pair(name)}), 201

@app.route("/api/settings/pairs/<string:name>", methods=["DELETE"])
def api_delete_pair(name):
    ok, err = delete_pair(name)
    if not ok:
        return jsonify({"error": err}), 409
    return jsonify({"deleted": name})


# ── Settings: Timeframes ──────────────────────────────────────────────────────

@app.route("/api/settings/timeframes", methods=["GET"])
def api_get_timeframes():
    return jsonify(get_timeframes())

@app.route("/api/settings/timeframes", methods=["POST"])
def api_add_timeframe():
    name = (request.get_json(force=True) or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "Timeframe name is required."}), 400
    return jsonify({"timeframe": add_timeframe(name)}), 201

@app.route("/api/settings/timeframes/<string:name>", methods=["DELETE"])
def api_delete_timeframe(name):
    ok, err = delete_timeframe(name)
    if not ok:
        return jsonify({"error": err}), 409
    return jsonify({"deleted": name})


# ── Settings: Entry Modules ───────────────────────────────────────────────────

@app.route("/api/settings/modules", methods=["GET"])
def api_get_modules():
    return jsonify(get_entry_modules())

@app.route("/api/settings/modules", methods=["POST"])
def api_add_module():
    name = (request.get_json(force=True) or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "Module name is required."}), 400
    return jsonify({"module": add_entry_module(name)}), 201

@app.route("/api/settings/modules/<int:module_id>", methods=["DELETE"])
def api_delete_module(module_id):
    ok, err = delete_entry_module(module_id)
    if not ok:
        return jsonify({"error": err}), 409
    return jsonify({"deleted": module_id})


# ── Settings: Reversal Levels ─────────────────────────────────────────────────

@app.route("/api/settings/levels", methods=["GET"])
def api_get_levels():
    return jsonify(get_reversal_levels())

@app.route("/api/settings/levels", methods=["POST"])
def api_add_level():
    name = (request.get_json(force=True) or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "Level name is required."}), 400
    return jsonify({"level": add_reversal_level(name)}), 201

@app.route("/api/settings/levels/<int:level_id>", methods=["DELETE"])
def api_delete_level(level_id):
    ok, err = delete_reversal_level(level_id)
    if not ok:
        return jsonify({"error": err}), 409
    return jsonify({"deleted": level_id})


# ── Trades ────────────────────────────────────────────────────────────────────

@app.route("/api/trades", methods=["GET"])
def api_get_trades():
    return jsonify(get_all_trades())

@app.route("/api/trades", methods=["POST"])
def api_add_trade():
    data = request.get_json(force=True)
    errors = validate_trade(data)
    if errors:
        return jsonify({"errors": errors}), 400
    return jsonify({"id": insert_trade(data)}), 201

@app.route("/api/trades/<int:trade_id>", methods=["DELETE"])
def api_delete_trade(trade_id):
    if not get_trade(trade_id):
        abort(404)
    delete_trade(trade_id)
    return jsonify({"deleted": trade_id})


# ── Webhook ───────────────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    raw = request.get_data(as_text=True)
    try:
        payload = json.loads(raw)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400
    queue_webhook(json.dumps(payload))
    return jsonify({"queued": True}), 200

@app.route("/api/webhook/queue", methods=["GET"])
def api_webhook_queue():
    return jsonify(get_pending_webhooks())

@app.route("/api/webhook/dismiss/<int:wid>", methods=["POST"])
def api_webhook_dismiss(wid):
    dismiss_webhook(wid)
    return jsonify({"dismissed": wid})


# Screenshot storage setting (local or remote)
@app.route('/api/settings/screenshot-storage', methods=['GET'])
def api_get_screenshot_storage():
    path = os.path.join(DATA_DIR, 'settings.json')
    mode = 'local'
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as fh:
                j = json.load(fh)
                mode = j.get('screenshot_storage', 'local')
    except Exception:
        mode = 'local'
    return jsonify({'storage': mode})


@app.route('/api/settings/screenshot-storage', methods=['POST'])
def api_set_screenshot_storage():
    data = request.get_json(force=True) or {}
    val = data.get('storage', 'local')
    if val not in ('local', 'remote'):
        return jsonify({'error': 'Invalid storage type.'}), 400
    path = os.path.join(DATA_DIR, 'settings.json')
    try:
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'screenshot_storage': val}, fh)
        return jsonify({'storage': val})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── TradingView CSV Import ────────────────────────────────────────────────────

@app.route("/api/import-tradingview", methods=["POST"])
def api_import_tradingview():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith(".csv"):
        return jsonify({"error": "Only .csv files are accepted."}), 400
    try:
        content = f.read().decode("utf-8-sig")
        inserted, skipped, errors = import_tradingview_csv(content)
        return jsonify({"inserted": inserted, "skipped": skipped, "errors": errors}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── AI Export ─────────────────────────────────────────────────────────────────

@app.route("/api/export", methods=["GET"])
def api_export():
    return jsonify({"payload": generate_ai_export()})


# ── Validation ────────────────────────────────────────────────────────────────

def validate_trade(d):
    errs = []

    # Required core fields
    for f in ("pair", "timeframe", "direction", "outcome",
              "planned_sl_pips", "planned_tp_pips", "planned_rr"):
        if d.get(f) is None or str(d.get(f, "")).strip() == "":
            errs.append(f"'{f}' is required.")

    # 1D timeframe — session not required
    is_daily = str(d.get("timeframe", "")).upper() == "1D"
    if not is_daily:
        if not d.get("session") or str(d.get("session", "")).strip() == "":
            errs.append("'session' is required for intraday timeframes.")

    # Dynamic DB lookups
    if d.get("pair") and d["pair"].upper() not in [p.upper() for p in get_pairs()]:
        errs.append(f"Pair '{d['pair']}' not found. Add it via Settings first.")
    if d.get("timeframe") and d["timeframe"].upper() not in [t.upper() for t in get_timeframes()]:
        errs.append(f"Timeframe '{d['timeframe']}' not found. Add it via Settings first.")

    if d.get("direction") and d["direction"] not in VALID_DIRECTIONS:
        errs.append("Invalid direction.")
    if not is_daily and d.get("session") and d["session"] not in VALID_SESSIONS:
        errs.append("Invalid session.")
    if d.get("outcome") and d["outcome"] not in VALID_OUTCOMES:
        errs.append("Invalid outcome.")

    # Entry modules — at least one required
    submitted_modules = d.get("entry_modules")
    if not isinstance(submitted_modules, list) or len(submitted_modules) == 0:
        errs.append("At least one entry module must be selected.")
    else:
        valid_names = [m["module_name"] for m in get_entry_modules()]
        bad = [m for m in submitted_modules if m not in valid_names]
        if bad:
            errs.append(f"Unknown module(s): {', '.join(bad)}.")

    # dynamic_entry_zones — optional dict; accept dict, null, empty, JSON string, or 'N/A'
    zones = d.get("dynamic_entry_zones")
    if zones is not None and not isinstance(zones, dict):
        if isinstance(zones, str):
            if zones.strip() in ("", "{}", "N/A"):
                # treat as no zones provided
                pass
            else:
                try:
                    parsed = json.loads(zones)
                    if not isinstance(parsed, dict):
                        errs.append("'dynamic_entry_zones' must be an object.")
                except Exception:
                    errs.append("'dynamic_entry_zones' must be valid JSON.")
        else:
            errs.append("'dynamic_entry_zones' must be an object.")

    # MAE/MFE conditional rules
    outcome = d.get("outcome")
    if outcome == "Win" and (d.get("actual_mae_pips") is None or str(d.get("actual_mae_pips", "")).strip() == ""):
        errs.append("Actual MAE is required for a Win trade.")
    if outcome == "Loss" and (d.get("actual_mfe_pips") is None or str(d.get("actual_mfe_pips", "")).strip() == ""):
        errs.append("Actual MFE is required for a Loss trade.")

    # Numeric fields
    for f in ("planned_sl_pips", "planned_tp_pips", "planned_rr",
              "exact_entry_price", "exact_sl_price", "exact_tp_price",
              "actual_mae_pips", "actual_mfe_pips"):
        try:
            if d.get(f) not in (None, ""):
                float(d[f])
        except (ValueError, TypeError):
            errs.append(f"'{f}' must be a number.")

    return errs


# Global exception handler to capture unexpected tracebacks to errors.log
@app.errorhandler(Exception)
def _handle_exception(e):
    # Preserve HTTP exceptions (404, 400, etc.) so they return their proper code.
    if isinstance(e, HTTPException):
        return e

    tb = traceback.format_exc()
    try:
        with open(os.path.join(DATA_DIR, "errors.log"), "a", encoding="utf-8") as ef:
            ef.write("\n\n[{0}] Exception: {1}\n".format(datetime.datetime.utcnow().isoformat(), str(e)))
            ef.write(tb)
    except Exception:
        pass
    app.logger.error("Unhandled exception: %s", str(e))
    return "Internal Server Error", 500


# Shutdown endpoint used by launcher to cleanly stop a running instance.
@app.route('/__shutdown_app', methods=['POST'])
def __shutdown_app():
    # Only allow local requests to shutdown
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return 'Forbidden', 403
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        return 'Not running with the Werkzeug Server', 500
    try:
        func()
        return 'Shutting down', 200
    except Exception:
        return 'Shutdown failed', 500


if __name__ == "__main__":
    init_db()
    # If run directly on desktop, open browser automatically
    def _open():
        try:
            webbrowser.open("http://127.0.0.1:5000")
        except Exception:
            pass

    threading.Thread(target=_open, daemon=True).start()

    # Respect PORT env if set (useful for Render)
    port = int(os.environ.get("PORT", 5000))
    app.run(port=port, debug=False, host="0.0.0.0")
