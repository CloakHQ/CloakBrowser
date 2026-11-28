import re
import shutil
import sqlite3
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from werkzeug.security import generate_password_hash

from cloakbrowser.config import get_binary_path
from control_plane import create_app, utc_now


@pytest.mark.real_browser
def test_real_cloakbrowser_session_stays_on_loopback(tmp_path):
    ldd = shutil.which("ldd")
    if ldd:
        dependencies = subprocess.run([ldd, str(get_binary_path())], capture_output=True, text=True, check=False)
        if "not found" in dependencies.stdout:
            pytest.skip("CloakBrowser system libraries are unavailable on this host; run in Dockerfile.local-browser")
    page_html = b"""<!doctype html><html><head><title>Local test</title>
      <script>document.documentElement.dataset.localReady = 'yes';</script>
      <script src='https://example.com/blocked.js'></script>
      </head><body><h1>Local browser test passed</h1>
      <img src='https://example.com/blocked.png' /></body></html>"""

    class LocalPageHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page_html)))
            self.end_headers()
            self.wfile.write(page_html)

        def log_message(self, *_args):
            return

    local_server = ThreadingHTTPServer(("127.0.0.1", 0), LocalPageHandler)
    server_thread = threading.Thread(target=local_server.serve_forever, daemon=True)
    server_thread.start()
    database_path = tmp_path / "browser-control.sqlite3"
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "local-browser-integration-test-secret",
        "DATABASE_PATH": str(database_path),
        "BOOTSTRAP_ADMIN_USERNAME": "",
        "BOOTSTRAP_ADMIN_PASSWORD": "",
        "LOCAL_BROWSER_ENABLED": True,
        "LOCAL_BROWSER_IDLE_SECONDS": 60,
    })
    connection = sqlite3.connect(database_path)
    connection.execute(
        "INSERT INTO users (username, display_name, password_hash, role, points, status, created_at) "
        "VALUES (?, ?, ?, 'user', 100, 'active', ?)",
        ("local-tester", "本机测试", generate_password_hash("local-browser-test-password"), utc_now()),
    )
    connection.commit()
    connection.close()
    client = app.test_client()
    login_page = client.get("/login")
    csrf = re.search(rb'name="csrf_token" value="([^"]+)"', login_page.data).group(1).decode()
    client.post("/login", data={
        "username": "local-tester",
        "password": "local-browser-test-password",
        "csrf_token": csrf,
    })
    with client.session_transaction() as session:
        csrf = session["csrf_token"]

    try:
        response = client.post("/user/browser/start", data={
            "csrf_token": csrf,
            "url": f"http://127.0.0.1:{local_server.server_port}/test",
            "locale": "zh-CN",
            "timezone": "Asia/Shanghai",
        })
        assert response.status_code == 302
        lab = client.get("/user/browser")
        assert "本机测试会话已启动".encode() in lab.data
        assert "Local test".encode() in lab.data
        screenshot = client.get("/user/browser/screenshot")
        assert screenshot.status_code == 200
        assert screenshot.mimetype == "image/png"
        assert screenshot.data.startswith(b"\x89PNG\r\n\x1a\n")
    finally:
        client.post("/user/browser/stop", data={"csrf_token": csrf})
        local_server.shutdown()
        local_server.server_close()
        server_thread.join(timeout=2)
