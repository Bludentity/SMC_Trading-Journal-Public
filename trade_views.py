import os
import sys
import io
import json
import base64
import mimetypes
from flask import Blueprint, render_template, request, jsonify, send_file, abort, make_response
from werkzeug.utils import secure_filename
from database import (
    get_trade, update_trade, insert_screenshot, get_screenshots, generate_ai_export,
    get_pairs, get_timeframes, get_entry_modules, get_reversal_levels, get_screenshot_blob, insert_screenshot_blob, delete_screenshot_by_id
)

from database import delete_trades_bulk

trade_bp = Blueprint('trades', __name__)

# Data directory for runtime files
smc_base = os.environ.get('SMC_BASE_DIR')
if smc_base:
    DATA_DIR = smc_base
elif getattr(sys, 'frozen', False):
    local = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    DATA_DIR = os.path.join(local, 'SMC_Journal')
else:
    DATA_DIR = os.getcwd()

os.makedirs(DATA_DIR, exist_ok=True)


@trade_bp.route('/trade/<int:trade_id>')
def trade_detail_page(trade_id):
    t = get_trade(trade_id)
    if not t:
        abort(404)
    screenshots = get_screenshots(trade_id)
    pairs = get_pairs()
    tfs = get_timeframes()
    modules = get_entry_modules()
    levels = get_reversal_levels()
    # sessions and outcomes static
    sessions = ["Asian", "London", "New York"]
    outcomes = ["Win", "Loss", "Break-Even"]
    return render_template('trade_details.html', trade=t, screenshots=screenshots, pairs=pairs, timeframes=tfs, modules=modules, levels=levels, sessions=sessions, outcomes=outcomes)


@trade_bp.route('/api/trades/<int:trade_id>', methods=['PUT'])
def api_update_trade(trade_id):
    data = request.get_json(force=True) or {}
    ok = update_trade(trade_id, data)
    if not ok:
        return jsonify({'error': 'No updatable fields provided.'}), 400
    return jsonify({'updated': trade_id}), 200


@trade_bp.route('/api/trades/<int:trade_id>/screenshot', methods=['POST'])
def api_upload_screenshot(trade_id):
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded.'}), 400
    f = request.files['file']
    if f.filename == '':
        return jsonify({'error': 'Empty filename.'}), 400
    filename = secure_filename(f.filename)
    # read storage preference from writable DATA_DIR
    settings_path = os.path.join(DATA_DIR, 'settings.json')
    storage = 'local'
    try:
        if os.path.exists(settings_path):
            with open(settings_path, 'r', encoding='utf-8') as sf:
                s = json.load(sf)
                storage = s.get('screenshot_storage', 'local')
    except Exception:
        storage = 'local'

    import time
    unique_name = f"{trade_id}_{int(time.time())}_{filename}"
    if storage == 'remote':
        # store blob base64 in DB
        data = f.read()
        b64 = base64.b64encode(data).decode('ascii')
        insert_screenshot_blob(trade_id, unique_name, b64)
        return jsonify({'uploaded': unique_name, 'storage': 'remote'}), 201
    else:
        uploads_dir = os.path.join(DATA_DIR, 'uploads')
        os.makedirs(uploads_dir, exist_ok=True)
        dest = os.path.join(uploads_dir, unique_name)
        f.save(dest)
        insert_screenshot(trade_id, unique_name)
        return jsonify({'uploaded': unique_name, 'storage': 'local'}), 201


@trade_bp.route('/api/trades/<int:trade_id>/screenshot/<int:sid>', methods=['DELETE'])
def api_delete_screenshot(trade_id, sid):
    try:
        ok = delete_screenshot_by_id(sid)
        if ok:
            return jsonify({'deleted': sid})
        return jsonify({'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@trade_bp.route('/api/trades/<int:trade_id>/screenshot/<int:sid>', methods=['GET'])
def api_get_screenshot_blob(trade_id, sid):
    # try blob first
    row = get_screenshot_blob(sid)
    if row and int(row.get('trade_id')) == int(trade_id):
        b64 = row.get('data')
        if not b64:
            abort(404)
        data = base64.b64decode(b64)
        buf = io.BytesIO(data)
        mime = mimetypes.guess_type(row.get('filename') or '')[0] or 'application/octet-stream'
        return send_file(buf, mimetype=mime, as_attachment=True, download_name=row.get('filename'))

    # fallback: check local screenshots table for this trade
    shots = get_screenshots(trade_id)
    shot = next((s for s in shots if int(s.get('id')) == int(sid)), None)
    if shot:
        uploads_dir = os.path.join(DATA_DIR, 'uploads')
        path = os.path.join(uploads_dir, shot.get('filename'))
        if not os.path.exists(path):
            abort(404)
        mime = mimetypes.guess_type(shot.get('filename') or '')[0] or 'application/octet-stream'
        return send_file(path, mimetype=mime, as_attachment=True, download_name=shot.get('filename'))

    abort(404)


@trade_bp.route('/api/export/file', methods=['GET'])
def api_export_file():
    ids_q = request.args.get('ids')
    ids = None
    if ids_q:
        try:
            ids = [int(x) for x in ids_q.split(',') if x.strip()]
        except Exception:
            ids = None
    payload = generate_ai_export(ids)
    exports_dir = os.path.join(DATA_DIR, 'exports')
    os.makedirs(exports_dir, exist_ok=True)
    fname = f'ai_export_{int(__import__('time').time())}.txt'
    path = os.path.join(exports_dir, fname)
    header = "AI Analytics Bridge\n" + ("="*40) + "\n"
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(header)
        fh.write(payload)
    return send_file(path, as_attachment=True, download_name=fname)


@trade_bp.route('/api/export/selected', methods=['POST'])
def api_export_selected():
    data = request.get_json(force=True) or {}
    ids = data.get('ids') or []
    try:
        ids = [int(x) for x in ids]
    except Exception:
        return jsonify({'error': 'Invalid ids'}), 400
    payload = generate_ai_export(ids)
    return jsonify({'payload': payload})


@trade_bp.route('/api/trades/bulk-delete', methods=['POST'])
def api_bulk_delete_trades():
    data = request.get_json(force=True) or {}
    ids = data.get('ids') or []
    try:
        ids = [int(x) for x in ids]
    except Exception:
        return jsonify({'error': 'Invalid ids'}), 400
    try:
        deleted_count = delete_trades_bulk(ids)
        return jsonify({'deleted_count': deleted_count, 'requested': len(ids)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
 