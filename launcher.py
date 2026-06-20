import threading
import webbrowser
import time
import socket
import sys
import urllib.request
import urllib.error
import os

# Defer imports that rely on local modules until runtime to avoid
# frozen-executable import errors (ModuleNotFoundError for 'database').
def _import_app_and_db():
    # When frozen, ensure the executable directory is on sys.path
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        # Ensure exe_dir is importable so packaged modules resolve.
        if exe_dir not in sys.path:
            sys.path.insert(0, exe_dir)
        # Use a writable DATA_DIR as the current working directory so any
        # relative file operations write to a safe location instead of
        # Program Files (avoids PermissionError on startup).
        smc_base = os.environ.get('SMC_BASE_DIR')
        if smc_base:
            data_dir = smc_base
        else:
            local = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
            data_dir = os.path.join(local, 'SMC_Journal')
        try:
            os.makedirs(data_dir, exist_ok=True)
        except Exception:
            pass
        try:
            os.chdir(data_dir)
        except Exception:
            # If we cannot chdir to data_dir, fall back to exe_dir to preserve behavior.
            try:
                os.chdir(exe_dir)
            except Exception:
                pass
    # local import
    from app import app
    from database import init_db
    return app, init_db

PORT = 5000


def port_in_use():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def open_browser():
    time.sleep(1.5)
    webbrowser.open(f"http://127.0.0.1:{PORT}")


if __name__ == "__main__":
    # import at runtime
    import os
    app, init_db = _import_app_and_db()

    if port_in_use():
        # attempt to ask the previous instance to shutdown cleanly
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/__shutdown_app", method='POST')
            with urllib.request.urlopen(req, timeout=2) as resp:
                pass
            # give the old server a moment to free the port
            time.sleep(1.5)
        except Exception:
            # couldn't shutdown previous server; open browser and exit
            webbrowser.open(f"http://127.0.0.1:{PORT}")
            sys.exit(0)

    init_db()
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(port=PORT, debug=False, use_reloader=False)
