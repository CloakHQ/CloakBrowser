import re
import sqlite3

import pytest
from werkzeug.security import generate_password_hash

from control_plane import (
   InsufficientPointsError,
   charge_points,
   create_app,
   is_loopback_url,
   local_only_route,
   utc_now,
)


@pytest.fixture
def app(tmp_path):
   database_path = tmp_path / "control.sqlite3"
   application = create_app({
      "TESTING": True,
      "SECRET_KEY": "test-secret-key",
      "DATABASE_PATH": str(database_path),
      "BOOTSTRAP_ADMIN_USERNAME": "",
      "BOOTSTRAP_ADMIN_PASSWORD": "",
   })
   connection = sqlite3.connect(database_path)
   now = utc_now()
   connection.executemany(
      "INSERT INTO users (username, display_name, password_hash, role, points, status, created_at) "
      "VALUES (?, ?, ?, ?, ?, 'active', ?)",
      [
         ("operator", "运营", generate_password_hash("operator-test-password"), "admin", 0, now),
         ("alice", "甲用户", generate_password_hash("alice-test-password"), "user", 100, now),
         ("bob", "乙用户", generate_password_hash("bob-test-password"), "user", 40, now),
      ],
   )
   connection.commit()
   connection.close()
   application.config["TEST_DATABASE_PATH"] = str(database_path)
   return application


def login(client, username, password):
   response = client.get("/login")
   csrf = re.search(rb'name="csrf_token" value="([^"]+)"', response.data).group(1).decode()
   return client.post("/login", data={"username": username, "password": password, "csrf_token": csrf})


def csrf_for(client):
   response = client.get("/login")
   return re.search(rb'name="csrf_token" value="([^"]+)"', response.data).group(1).decode()


def test_roles_separate_admin_and_user_pages(app):
   client = app.test_client()
   assert client.get("/admin").status_code == 302
   login(client, "alice", "alice-test-password")
   assert client.get("/user").status_code == 200
   assert client.get("/admin").status_code == 403
   assert "浏览器运行时尚未接入".encode() in client.get("/user").data
   assert "运营控制台".encode() not in client.get("/user").data


def test_admin_cannot_open_user_self_service(app):
   client = app.test_client()
   login(client, "operator", "operator-test-password")
   assert client.get("/admin").status_code == 200
   assert client.get("/user").status_code == 403


def test_static_assets_use_the_template_url_prefix(app):
   client = app.test_client()
   login_page = client.get("/login")
   assert b"/static/control.css" in login_page.data
   assert client.get("/static/control.css").status_code == 200


@pytest.mark.parametrize("url", [
   "http://localhost:8000/test",
   "https://localhost",
   "http://127.0.0.1:8080",
   "http://127.22.1.9:9000",
   "http://[::1]:8080",
])
def test_local_browser_target_allows_loopback(url):
   assert is_loopback_url(url)


@pytest.mark.parametrize("url", [
   "https://example.com",
   "http://localhost.example.com",
   "http://127.0.0.1.example.com",
   "http://192.168.1.2",
   "http://user:pass@localhost:8080",
   "file:///etc/passwd",
   "javascript:alert(1)",
   "http://localhost:99999",
])
def test_local_browser_target_rejects_non_loopback_and_ambiguous_urls(url):
   assert not is_loopback_url(url)


def test_browser_lab_is_disabled_by_default(app):
   client = app.test_client()
   login(client, "alice", "alice-test-password")
   assert client.get("/user/browser").status_code == 404


def test_local_browser_session_is_isolated_loopback_only_and_stoppable(app, monkeypatch):
   import cloakbrowser

   app.config["LOCAL_BROWSER_ENABLED"] = True

   class FakeRoute:
      def __init__(self, url):
         self.request = type("Request", (), {"url": url})()
         self.result = None

      def continue_(self):
         self.result = "continued"

      def abort(self, reason):
         self.result = reason

   class FakePage:
      url = "about:blank"

      def goto(self, url, **_kwargs):
         self.url = url

      def title(self):
         return "本机测试页面"

      def screenshot(self, **_kwargs):
         return b"local-screenshot"

   class FakeContext:
      def __init__(self):
         self.page = FakePage()
         self.route_handler = None
         self.websocket_handler = None

      def route(self, _pattern, handler):
         self.route_handler = handler

      def route_web_socket(self, _pattern, handler):
         self.websocket_handler = handler

      def new_page(self):
         return self.page

   class FakeBrowser:
      def __init__(self):
         self.context = FakeContext()
         self.closed = False

      def new_context(self, **_kwargs):
         return self.context

      def close(self):
         self.closed = True

   browser = FakeBrowser()
   monkeypatch.setattr(cloakbrowser, "launch", lambda **_kwargs: browser)
   client = app.test_client()
   login(client, "alice", "alice-test-password")
   with client.session_transaction() as session:
      csrf = session["csrf_token"]

   assert client.get("/user/browser").status_code == 200
   response = client.post("/user/browser/start", data={
      "csrf_token": csrf,
      "url": "http://127.0.0.1:3000/test",
      "locale": "zh-CN",
      "timezone": "Asia/Shanghai",
   })
   assert response.status_code == 302
   assert client.get("/user/browser/screenshot").data == b"local-screenshot"
   route = FakeRoute("http://localhost:3000/style.css")
   browser.context.route_handler(route)
   assert route.result == "continued"
   external_route = FakeRoute("https://example.com/redirected-resource")
   browser.context.route_handler(external_route)
   assert external_route.result == "blockedbyclient"

   other_client = app.test_client()
   login(other_client, "bob", "bob-test-password")
   with other_client.session_transaction() as session:
      other_csrf = session["csrf_token"]
   assert other_client.get("/user/browser/screenshot").status_code == 404
   assert other_client.post("/user/browser/stop", data={"csrf_token": other_csrf}).status_code == 302
   assert not browser.closed

   assert client.post("/user/browser/navigate", data={
      "csrf_token": csrf,
      "url": "http://localhost:8080/next",
   }).status_code == 302
   assert browser.context.page.url == "http://localhost:8080/next"
   assert client.post("/user/browser/stop", data={"csrf_token": csrf}).status_code == 302
   assert browser.closed


def test_points_adjustment_is_atomic_and_never_negative(app):
   client = app.test_client()
   login(client, "operator", "operator-test-password")
   with client.session_transaction() as session:
      csrf = session["csrf_token"]
   response = client.post("/admin/users/2/points", data={"csrf_token": csrf, "delta": "25", "reason": "测试补偿"})
   assert response.status_code == 302
   connection = sqlite3.connect(app.config["TEST_DATABASE_PATH"])
   assert connection.execute("SELECT points FROM users WHERE id = 2").fetchone()[0] == 125
   assert connection.execute("SELECT delta, balance_after, reason FROM points_ledger WHERE user_id = 2").fetchone() == (25, 125, "测试补偿")
   response = client.post("/admin/users/2/points", data={"csrf_token": csrf, "delta": "-126", "reason": "超额扣减"})
   assert response.status_code == 302
   assert connection.execute("SELECT points FROM users WHERE id = 2").fetchone()[0] == 125
   assert connection.execute("SELECT COUNT(*) FROM points_ledger WHERE user_id = 2").fetchone()[0] == 1
   connection.close()


def test_recharge_requires_admin_approval_and_cannot_be_credited_twice(app):
   admin_client = app.test_client()
   login(admin_client, "operator", "operator-test-password")
   with admin_client.session_transaction() as session:
      admin_csrf = session["csrf_token"]
   assert admin_client.post("/admin/settings/packages", data={
      "csrf_token": admin_csrf,
      "packages_json": '{"standard":{"points":1200,"amount_cents":10000}}',
   }).status_code == 302

   user_client = app.test_client()
   login(user_client, "alice", "alice-test-password")
   with user_client.session_transaction() as session:
      user_csrf = session["csrf_token"]
   assert user_client.post("/user/recharges", data={"csrf_token": user_csrf, "package": "standard"}).status_code == 302
   connection = sqlite3.connect(app.config["TEST_DATABASE_PATH"])
   assert connection.execute("SELECT points FROM users WHERE id = 2").fetchone()[0] == 100
   order_id = connection.execute("SELECT id FROM recharge_orders").fetchone()[0]
   connection.close()

   endpoint = f"/admin/recharges/{order_id}/review"
   payload = {"csrf_token": admin_csrf, "action": "approve"}
   assert admin_client.post(endpoint, data=payload).status_code == 302
   assert admin_client.post(endpoint, data=payload).status_code == 302

   connection = sqlite3.connect(app.config["TEST_DATABASE_PATH"])
   assert connection.execute("SELECT points FROM users WHERE id = 2").fetchone()[0] == 1300
   assert connection.execute("SELECT status FROM recharge_orders WHERE id = ?", (order_id,)).fetchone()[0] == "approved"
   assert connection.execute("SELECT COUNT(*) FROM points_ledger WHERE user_id = 2").fetchone()[0] == 1
   connection.close()


def test_ticket_visibility_is_user_scoped_and_admin_reply_is_visible(app):
   user_client = app.test_client()
   login(user_client, "alice", "alice-test-password")
   with user_client.session_transaction() as session:
      user_csrf = session["csrf_token"]
   assert user_client.post("/user/tickets", data={"csrf_token": user_csrf, "subject": "充值问题", "message": "请帮忙确认订单"}).status_code == 302
   assert "充值问题".encode() in user_client.get("/user").data

   other_client = app.test_client()
   login(other_client, "bob", "bob-test-password")
   assert "充值问题".encode() not in other_client.get("/user").data
   with other_client.session_transaction() as session:
      other_csrf = session["csrf_token"]

   admin_client = app.test_client()
   login(admin_client, "operator", "operator-test-password")
   with admin_client.session_transaction() as session:
      admin_csrf = session["csrf_token"]
   connection = sqlite3.connect(app.config["TEST_DATABASE_PATH"])
   ticket_id = connection.execute("SELECT id FROM support_tickets").fetchone()[0]
   connection.close()
   assert admin_client.post(
      f"/admin/tickets/{ticket_id}/reply",
      data={"csrf_token": admin_csrf, "status": "closed", "response": "问题已处理"},
   ).status_code == 302
   response = user_client.get("/user")
   assert "问题已处理".encode() in response.data
   assert "已关闭".encode() in response.data
   assert other_client.post(
      f"/user/tickets/{ticket_id}/messages",
      data={"csrf_token": other_csrf, "message": "越权回复"},
   ).status_code == 404
   assert user_client.post(
      f"/user/tickets/{ticket_id}/messages",
      data={"csrf_token": user_csrf, "message": "补充订单截图信息"},
   ).status_code == 302
   reopened = user_client.get("/user")
   assert "问题已处理".encode() in reopened.data
   assert "补充订单截图信息".encode() in reopened.data
   assert "待处理".encode() in reopened.data


def test_support_link_validation_and_csrf_protection(app):
   client = app.test_client()
   login(client, "operator", "operator-test-password")
   with client.session_transaction() as session:
      csrf = session["csrf_token"]
   assert client.post("/admin/settings/support", data={"csrf_token": csrf, "telegram_support_url": "https://example.com"}).status_code == 302
   response = client.get("/admin")
   assert "客服入口配置已保存".encode() not in response.data
   assert client.post("/admin/settings/support", data={"csrf_token": csrf, "telegram_support_url": "https://t.me/support_team"}).status_code == 302
   with client.session_transaction() as session:
      assert session["csrf_token"] == csrf
   connection = sqlite3.connect(app.config["TEST_DATABASE_PATH"])
   assert connection.execute("SELECT value FROM settings WHERE key = 'telegram_support_url'").fetchone()[0] == "https://t.me/support_team"
   connection.close()
   assert client.post("/admin/settings/support", data={"telegram_support_url": "https://t.me/without-csrf"}).status_code == 400


def test_login_rejects_bad_credentials(app):
   client = app.test_client()
   response = client.post("/login", data={"username": "alice", "password": "incorrect", "csrf_token": csrf_for(client)})
   assert response.status_code == 302
   assert client.get("/user").status_code == 302


def test_login_rate_limited_after_repeated_failures(app):
   client = app.test_client()
   csrf = csrf_for(client)
   for _ in range(5):
      response = client.post("/login", data={"username": "alice", "password": "incorrect", "csrf_token": csrf})
      assert response.status_code == 302
   followup = client.get("/login")
   assert "登录失败次数过多".encode() in followup.data
   response = client.post("/login", data={"username": "alice", "password": "alice-test-password", "csrf_token": csrf})
   assert response.status_code == 302
   assert client.get("/user").status_code == 302


def test_recharge_packages_are_validated_and_required(app):
   client = app.test_client()
   login(client, "operator", "operator-test-password")
   with client.session_transaction() as session:
      csrf = session["csrf_token"]
   invalid_response = client.post("/admin/settings/packages", data={
      "csrf_token": csrf,
      "packages_json": '{"free":{"points":100,"amount_cents":0}}',
   })
   assert invalid_response.status_code == 302
   user_client = app.test_client()
   login(user_client, "alice", "alice-test-password")
   with user_client.session_transaction() as session:
      user_csrf = session["csrf_token"]
   user_client.post("/user/recharges", data={"csrf_token": user_csrf, "package": "anything"})
   connection = sqlite3.connect(app.config["TEST_DATABASE_PATH"])
   assert connection.execute("SELECT COUNT(*) FROM recharge_orders").fetchone()[0] == 0
   connection.close()


def test_production_requires_a_stable_secret_key(tmp_path, monkeypatch):
   monkeypatch.delenv("SECRET_KEY", raising=False)
   with pytest.raises(RuntimeError, match="SECRET_KEY"):
      create_app({
         "TESTING": True,
         "APP_ENV": "production",
         "SECRET_KEY": "",
         "DATABASE_PATH": str(tmp_path / "production.sqlite3"),
         "BOOTSTRAP_ADMIN_USERNAME": "",
         "BOOTSTRAP_ADMIN_PASSWORD": "",
      })


def test_production_requires_secure_cookies_and_bootstrap_admin(tmp_path):
   config = {
      "TESTING": True,
      "APP_ENV": "production",
      "SECRET_KEY": "x" * 48,
      "COOKIE_SECURE": False,
      "DATABASE_PATH": str(tmp_path / "production.sqlite3"),
      "BOOTSTRAP_ADMIN_USERNAME": "",
      "BOOTSTRAP_ADMIN_PASSWORD": "",
   }
   with pytest.raises(RuntimeError, match="COOKIE_SECURE"):
      create_app(config)
   config["COOKIE_SECURE"] = True
   with pytest.raises(RuntimeError, match="bootstrap administrator"):
      create_app(config)


def test_production_bootstraps_admin_with_secure_session_cookie(tmp_path):
   application = create_app({
      "TESTING": True,
      "APP_ENV": "production",
      "SECRET_KEY": "production-test-secret-key-at-least-32-chars",
      "COOKIE_SECURE": True,
      "DATABASE_PATH": str(tmp_path / "production.sqlite3"),
      "BOOTSTRAP_ADMIN_USERNAME": "first-admin",
      "BOOTSTRAP_ADMIN_PASSWORD": "first-admin-test-password",
   })
   client = application.test_client()
   response = login(client, "first-admin", "first-admin-test-password")
   assert response.status_code == 302
   cookie = response.headers["Set-Cookie"]
   assert "Secure" in cookie
   assert "HttpOnly" in cookie
   assert "SameSite=Lax" in cookie


def test_production_refuses_local_browser_runtime(tmp_path):
   with pytest.raises(RuntimeError, match="must not be enabled in production"):
      create_app({
         "TESTING": True,
         "APP_ENV": "production",
         "SECRET_KEY": "production-test-secret-key-at-least-32-chars",
         "COOKIE_SECURE": True,
         "LOCAL_BROWSER_ENABLED": True,
         "DATABASE_PATH": str(tmp_path / "production.sqlite3"),
         "BOOTSTRAP_ADMIN_USERNAME": "",
         "BOOTSTRAP_ADMIN_PASSWORD": "",
      })


def test_existing_database_gets_session_version_migration(tmp_path):
   database_path = tmp_path / "legacy.sqlite3"
   connection = sqlite3.connect(database_path)
   connection.execute(
      "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, "
      "display_name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, "
      "points INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL)"
   )
   connection.commit()
   connection.close()

   create_app({
      "TESTING": True,
      "SECRET_KEY": "test-secret-key",
      "DATABASE_PATH": str(database_path),
      "BOOTSTRAP_ADMIN_USERNAME": "",
      "BOOTSTRAP_ADMIN_PASSWORD": "",
   })
   connection = sqlite3.connect(database_path)
   columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
   connection.close()
   assert "session_version" in columns


def test_usage_charge_is_idempotent_and_rolls_back_on_insufficient_balance(app):
   connection = sqlite3.connect(app.config["TEST_DATABASE_PATH"])
   connection.row_factory = sqlite3.Row
   assert charge_points(connection, 2, 30, "browser session usage", "session:alpha") == 70
   assert charge_points(connection, 2, 30, "browser session usage", "session:alpha") == 70
   with pytest.raises(ValueError, match="different charge"):
      charge_points(connection, 2, 31, "browser session usage", "session:alpha")
   with pytest.raises(InsufficientPointsError):
      charge_points(connection, 2, 100, "browser session usage", "session:beta")
   assert connection.execute("SELECT points FROM users WHERE id = 2").fetchone()[0] == 70
   assert connection.execute("SELECT COUNT(*) FROM points_ledger WHERE user_id = 2").fetchone()[0] == 1
   connection.close()


def test_password_change_verifies_old_password_and_revokes_other_sessions(app):
   first_client = app.test_client()
   login(first_client, "alice", "alice-test-password")
   second_client = app.test_client()
   login(second_client, "alice", "alice-test-password")
   with first_client.session_transaction() as session:
      csrf = session["csrf_token"]

   response = first_client.post("/account/password", data={
      "csrf_token": csrf,
      "current_password": "alice-test-password",
      "new_password": "alice-new-test-password",
   })
   assert response.status_code == 302
   assert first_client.get("/user").status_code == 200
   assert second_client.get("/user").status_code == 302

   new_client = app.test_client()
   login(new_client, "alice", "alice-new-test-password")
   assert new_client.get("/user").status_code == 200


def test_admin_creates_and_suspends_user_accounts(app):
   client = app.test_client()
   login(client, "operator", "operator-test-password")
   with client.session_transaction() as session:
      csrf = session["csrf_token"]
   response = client.post("/admin/users", data={
      "csrf_token": csrf,
      "username": "new-customer",
      "display_name": "新用户",
      "password": "new-customer-test-password",
   })
   assert response.status_code == 302
   connection = sqlite3.connect(app.config["TEST_DATABASE_PATH"])
   user_id = connection.execute("SELECT id FROM users WHERE username = 'new-customer'").fetchone()[0]
   connection.close()
   assert client.post(f"/admin/users/{user_id}/status", data={"csrf_token": csrf, "status": "suspended"}).status_code == 302
   user_client = app.test_client()
   login(user_client, "new-customer", "new-customer-test-password")
   assert user_client.get("/user").status_code == 302
