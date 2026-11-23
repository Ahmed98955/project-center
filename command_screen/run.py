"""Start the Commander Screen: local server + open the browser."""
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from app import config


def _port_free(host, port):
    with socket.socket() as s:
        return s.connect_ex((host, port)) != 0


def main():
    host, port = config.HOST, config.PORT
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}/"
    if not _port_free("127.0.0.1", port):
        print(f"شاشة القائد تعمل بالفعل — جاري فتح {url}")
        webbrowser.open(url)
        return
    if "--no-browser" not in sys.argv:
        threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
    print("=" * 60)
    print(" شاشة القائد — نظام إدارة العمليات والمشروعات")
    print(f" العنوان: {url}")
    print(" لإيقاف البرنامج: أغلق هذه النافذة أو اضغط Ctrl+C")
    print("=" * 60)
    uvicorn.run("app.main:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
