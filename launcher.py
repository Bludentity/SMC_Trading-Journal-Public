import threading
import webbrowser
import time
import socket
import sys
from app import app
from database import init_db

PORT = 5000


def port_in_use():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def open_browser():
    time.sleep(1.5)
    webbrowser.open(f"http://127.0.0.1:{PORT}")


if __name__ == "__main__":
    if port_in_use():
        webbrowser.open(f"http://127.0.0.1:{PORT}")
        sys.exit(0)

    init_db()
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(port=PORT, debug=False, use_reloader=False)
