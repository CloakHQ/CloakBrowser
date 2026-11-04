#!/usr/bin/env python3
"""Standalone account and operations control plane for CloakBrowser."""

from datetime import datetime, timedelta, timezone
from atexit import register
from functools import wraps
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, Response, abort, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent


def create_app(test_config=None):
    configured_secret = os.environ.get("SECRET_KEY")
    if test_config and test_config.get("SECRET_KEY"):
        configured_secret = test_config["SECRET_KEY"]
    app = Flask(__name__, template_folder="templates/control", static_folder="static/control", static_url_path="/static")
    app.config.from_mapping(
        SECRET_KEY=configured_secret or secrets.token_hex(32),
        DATABASE_PATH=os.environ.get("DATABASE_PATH", str(BASE_DIR / "data" / "saas_accounts.sqlite3")),
        APP_NAME=os.environ.get("APP_NAME", "发大财"),
        APP_ENV=os.environ.get("APP_ENV", "development"),
        COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=1_048_576,
        BOOTSTRAP_ADMIN_USERNAME=os.environ.get("BOOTSTRAP_ADMIN_USERNAME", ""),
        BOOTSTRAP_ADMIN_PASSWORD=os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", ""),
        RECHARGE_PACKAGES_JSON=os.environ.get("RECHARGE_PACKAGES_JSON", "{}"),
        LOGIN_ATTEMPT_LIMIT=int(os.environ.get("LOGIN_ATTEMPT_LIMIT", "5")),
        LOGIN_ATTEMPT_WINDOW_SECONDS=int(os.environ.get("LOGIN_ATTEMPT_WINDOW_SECONDS", "300")),
        LOCAL_BROWSER_ENABLED=os.environ.get("LOCAL_BROWSER_ENABLED", "0") == "1",
        LOCAL_BROWSER_MAX_SESSIONS=1,
        LOCAL_BROWSER_IDLE_SECONDS=900,
    )
    if test_config:
        app.config.update(test_config)
    if app.config["APP_ENV"] == "production" and (not configured_secret or len(configured_secret) < 32):
        raise RuntimeError("A stable SECRET_KEY of at least 32 characters must be configured in production")
    if app.config["APP_ENV"] == "production" and not app.config["COOKIE_SECURE"]:
        raise RuntimeError("COOKIE_SECURE must be enabled in production")
    if app.config["APP_ENV"] == "production" and app.config["LOCAL_BROWSER_ENABLED"]:
        raise RuntimeError("Local browser sessions must not be enabled in production")
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be configured")
    if bool(app.config["BOOTSTRAP_ADMIN_USERNAME"]) != bool(app.config["BOOTSTRAP_ADMIN_PASSWORD"]):
        raise RuntimeError("Configure both bootstrap admin username and password, or neither")
    app.config["DEFAULT_RECHARGE_PACKAGES"] = parse_recharge_packages(app.config["RECHARGE_PACKAGES_JSON"])
    app.config["SESSION_COOKIE_SECURE"] = app.config["COOKIE_SECURE"]

    database_path = Path(app.config["DATABASE_PATH"])
    database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    initialize_database(app)
    os.chmod(database_path, 0o600)
    app.extensions["local_browser_sessions"] = {}
    app.extensions["local_browser_lock"] = threading.RLock()
    app.extensions["login_attempts"] = {}
    app.extensions["login_attempts_lock"] = threading.RLock()
    register(close_all_local_browsers, app)

    def login_attempt_bucket(username, ip_address):
        value = (ip_address or "unknown").strip() + "|" + (username or "").strip().lower()
        return value if value else "unknown|unknown"

    def is_login_rate_limited(username, ip_address):
        bucket = login_attempt_bucket(username, ip_address)
        now = time.monotonic()
        window = app.config["LOGIN_ATTEMPT_WINDOW_SECONDS"]
        limit = max(1, app.config["LOGIN_ATTEMPT_LIMIT"])
        attempts = app.extensions["login_attempts"]
        lock = app.extensions["login_attempts_lock"]
        with lock:
            values = attempts.setdefault(bucket, [])
            values[:] = [ts for ts in values if now - ts < window]
            return len(values) >= limit

    def record_login_failure(username, ip_address):
        bucket = login_attempt_bucket(username, ip_address)
        now = time.monotonic()
        window = app.config["LOGIN_ATTEMPT_WINDOW_SECONDS"]
        attempts = app.extensions["login_attempts"]
        lock = app.extensions["login_attempts_lock"]
        with lock:
            values = attempts.setdefault(bucket, [])
            values[:] = [ts for ts in values if now - ts < window]
            values.append(now)

    def clear_login_attempts(username, ip_address):
        bucket = login_attempt_bucket(username, ip_address)
        attempts = app.extensions["login_attempts"]
        lock = app.extensions["login_attempts_lock"]
        with lock:
            attempts.pop(bucket, None)

    register(close_all_local_browsers, app)

    @app.before_request
    def open_database_and_check_csrf():
        g.db = sqlite3.connect(app.config["DATABASE_PATH"], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        if request.method == "POST":
            expected = session.get("csrf_token", "")
            supplied = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
            if not expected or not secrets.compare_digest(expected, supplied):
                abort(400, "Invalid CSRF token")

    @app.teardown_appcontext
    def close_database(_error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.context_processor
    def inject_template_values():
        return {
            "app_name": app.config["APP_NAME"],
            "csrf_token": csrf_token,
            "local_browser_enabled": app.config["LOCAL_BROWSER_ENABLED"],
        }

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; "
            "form-action 'self'; base-uri 'self'; frame-ancestors 'none'; object-src 'none'",
        )
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                return redirect(url_for("login", next=request.path))
            if user["status"] != "active":
                session.clear()
                flash("账户已停用，请联系管理员。", "error")
                return redirect(url_for("login"))
            if not secrets.compare_digest(user["session_version"], session.get("session_version", "")):
                session.clear()
                flash("登录状态已更新，请重新登录。", "error")
                return redirect(url_for("login"))
            g.current_user = user
            return view(*args, **kwargs)
        return wrapped

    def admin_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.current_user["role"] != "admin":
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    def user_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.current_user["role"] != "user":
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    @app.get("/healthz")
    def health():
        g.db.execute("SELECT 1").fetchone()
        return {"status": "ok", "service": "cloakbrowser-control-plane"}

    @app.get("/")
    def index():
        user = current_user()
        if user is None:
            return redirect(url_for("login"))
        return redirect(url_for("admin_dashboard" if user["role"] == "admin" else "user_dashboard"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            session.setdefault("csrf_token", secrets.token_urlsafe(32))
            return render_template("login.html")
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip_address = request.remote_addr or "unknown"

        if is_login_rate_limited(username, ip_address):
            flash(f"登录失败次数过多，请 {app.config['LOGIN_ATTEMPT_WINDOW_SECONDS'] // 60} 分钟后再试。", "error")
            return redirect(url_for("login"))

        user = g.db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password) or user["status"] != "active":
            record_login_failure(username, ip_address)
            if is_login_rate_limited(username, ip_address):
                flash(f"登录失败次数过多，请 {app.config['LOGIN_ATTEMPT_WINDOW_SECONDS'] // 60} 分钟后再试。", "error")
            else:
                flash("账号或密码不正确。", "error")
            return redirect(url_for("login"))
        clear_login_attempts(username, ip_address)
        session.clear()
        session["user_id"] = user["id"]
        session["session_version"] = user["session_version"]
        session["csrf_token"] = secrets.token_urlsafe(32)
        session.permanent = True
        return redirect(url_for("admin_dashboard" if user["role"] == "admin" else "user_dashboard"))

    @app.post("/logout")
    @login_required
    def logout():
        stop_local_browser_session(g.current_user["id"], app)
        session.clear()
        return redirect(url_for("login"))

    @app.get("/admin")
    @admin_required
    def admin_dashboard():
        db = g.db
        totals = db.execute(
            "SELECT COUNT(*) AS users, "
            "SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_users, "
            "COALESCE(SUM(points), 0) AS points FROM users WHERE role = 'user'"
        ).fetchone()
        month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")
        stats = {
            "users": totals["users"],
            "active_users": totals["active_users"] or 0,
            "points": totals["points"],
            "revenue_cents": db.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM recharge_orders "
                "WHERE status = 'approved' AND created_at LIKE ?", (month_prefix + "%",)
            ).fetchone()[0],
        }
        users = db.execute("SELECT * FROM users WHERE role = 'user' ORDER BY id DESC").fetchall()
        recharges = db.execute(
            "SELECT r.*, u.username FROM recharge_orders r JOIN users u ON u.id = r.user_id "
            "ORDER BY r.id DESC LIMIT 50"
        ).fetchall()
        tickets = db.execute(
            "SELECT t.*, u.username FROM support_tickets t JOIN users u ON u.id = t.user_id "
            "ORDER BY CASE t.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, t.id DESC LIMIT 50"
        ).fetchall()
        ticket_messages = load_ticket_messages(db, [ticket["id"] for ticket in tickets])
        support_url = setting(db, "telegram_support_url")
        packages_json = setting(db, "recharge_packages", app.config["RECHARGE_PACKAGES_JSON"])
        return render_template("admin.html", stats=stats, users=users, recharges=recharges, tickets=tickets,
                               ticket_messages=ticket_messages, support_url=support_url,
                               current_user=g.current_user, packages_json=packages_json)

    @app.post("/admin/users")
    @admin_required
    def create_user():
        username = request.form.get("username", "").strip()
        display_name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "")
        if not username or len(username) > 64 or len(display_name) > 100:
            flash("请填写有效的用户名和显示名称。", "error")
            return redirect(url_for("admin_dashboard") + "#users")
        if len(password) < 12:
            flash("初始密码至少需要 12 个字符。", "error")
            return redirect(url_for("admin_dashboard") + "#users")
        try:
            g.db.execute(
                "INSERT INTO users (username, display_name, password_hash, role, points, status, created_at) "
                "VALUES (?, ?, ?, 'user', 0, 'active', ?)",
                (username, display_name or username, generate_password_hash(password), utc_now()),
            )
            g.db.commit()
            flash(f"用户 {username} 已创建。请通过安全渠道交付初始密码。", "success")
        except sqlite3.IntegrityError:
            g.db.rollback()
            flash("用户名已存在。", "error")
        return redirect(url_for("admin_dashboard") + "#users")

    @app.post("/admin/users/<int:user_id>/points")
    @admin_required
    def adjust_points(user_id):
        try:
            delta = int(request.form.get("delta", ""))
        except ValueError:
            abort(400, "积分变动必须是整数")
        reason = request.form.get("reason", "").strip()
        if delta == 0 or abs(delta) > 1_000_000 or not reason or len(reason) > 200:
            abort(400, "积分变动或原因无效")
        db = g.db
        try:
            db.execute("BEGIN IMMEDIATE")
            user = db.execute("SELECT points FROM users WHERE id = ? AND role = 'user'", (user_id,)).fetchone()
            if user is None:
                db.rollback()
                abort(404)
            balance = user["points"] + delta
            if balance < 0:
                db.rollback()
                flash("积分不足，不能扣至负数。", "error")
                return redirect(url_for("admin_dashboard") + "#users")
            db.execute("UPDATE users SET points = ? WHERE id = ?", (balance, user_id))
            db.execute(
                "INSERT INTO points_ledger (user_id, actor_id, delta, balance_after, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, g.current_user["id"], delta, balance, reason, utc_now()),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        flash("积分调整已入账并记录。", "success")
        return redirect(url_for("admin_dashboard") + "#users")

    @app.post("/admin/users/<int:user_id>/status")
    @admin_required
    def set_user_status(user_id):
        status = request.form.get("status")
        if status not in {"active", "suspended"}:
            abort(400)
        cursor = g.db.execute("UPDATE users SET status = ? WHERE id = ? AND role = 'user'", (status, user_id))
        g.db.commit()
        if cursor.rowcount == 0:
            abort(404)
        if status == "suspended":
            stop_local_browser_session(user_id, app)
        flash("用户状态已更新。", "success")
        return redirect(url_for("admin_dashboard") + "#users")

    @app.post("/admin/recharges/<int:order_id>/review")
    @admin_required
    def review_recharge(order_id):
        action = request.form.get("action")
        if action not in {"approve", "reject"}:
            abort(400)
        db = g.db
        try:
            db.execute("BEGIN IMMEDIATE")
            order = db.execute("SELECT * FROM recharge_orders WHERE id = ?", (order_id,)).fetchone()
            if order is None:
                db.rollback()
                abort(404)
            if order["status"] != "pending":
                db.rollback()
                flash("该订单已处理，不能重复审核。", "error")
                return redirect(url_for("admin_dashboard") + "#recharges")
            new_status = "approved" if action == "approve" else "rejected"
            db.execute(
                "UPDATE recharge_orders SET status = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ? AND status = 'pending'",
                (new_status, g.current_user["id"], utc_now(), order_id),
            )
            if action == "approve":
                db.execute("UPDATE users SET points = points + ? WHERE id = ?", (order["points"], order["user_id"]))
                new_balance = db.execute("SELECT points FROM users WHERE id = ?", (order["user_id"],)).fetchone()[0]
                db.execute(
                    "INSERT INTO points_ledger (user_id, actor_id, delta, balance_after, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (order["user_id"], g.current_user["id"], order["points"], new_balance,
                     f"充值订单 {order['order_ref']} 审核通过", utc_now()),
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        flash("充值审核已完成。", "success")
        return redirect(url_for("admin_dashboard") + "#recharges")

    @app.post("/admin/tickets/<int:ticket_id>/reply")
    @admin_required
    def reply_ticket(ticket_id):
        status = request.form.get("status")
        response_text = request.form.get("response", "").strip()
        if status not in {"open", "in_progress", "closed"} or len(response_text) > 2000:
            abort(400)
        cursor = g.db.execute("SELECT id FROM support_tickets WHERE id = ?", (ticket_id,)).fetchone()
        if cursor is None:
            abort(404)
        now = utc_now()
        if response_text:
            g.db.execute(
                "INSERT INTO support_messages (ticket_id, author_id, author_role, body, created_at) "
                "VALUES (?, ?, 'admin', ?, ?)",
                (ticket_id, g.current_user["id"], response_text, now),
            )
        g.db.execute(
            "UPDATE support_tickets SET status = ?, admin_response = ?, updated_at = ? WHERE id = ?",
            (status, response_text, now, ticket_id),
        )
        g.db.commit()
        flash("工单回复和状态已更新。", "success")
        return redirect(url_for("admin_dashboard") + "#tickets")

    @app.post("/admin/settings/support")
    @admin_required
    def update_support_url():
        support_url = request.form.get("telegram_support_url", "").strip()
        if support_url and not is_telegram_url(support_url):
            flash("请输入 https://t.me/ 或 https://telegram.me/ 下的有效链接。", "error")
            return redirect(url_for("admin_dashboard") + "#settings")
        set_setting(g.db, "telegram_support_url", support_url)
        g.db.commit()
        flash("客服入口配置已保存。", "success")
        return redirect(url_for("admin_dashboard") + "#settings")

    @app.post("/admin/settings/packages")
    @admin_required
    def update_recharge_packages():
        packages_json = request.form.get("packages_json", "").strip()
        try:
            packages = parse_recharge_packages(packages_json)
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("admin_dashboard") + "#settings")
        set_setting(g.db, "recharge_packages", packages_json or "{}")
        g.db.commit()
        flash(f"充值套餐已更新，共 {len(packages)} 个可用套餐。", "success")
        return redirect(url_for("admin_dashboard") + "#settings")

    @app.get("/user")
    @user_required
    def user_dashboard():
        db = g.db
        account = db.execute("SELECT * FROM users WHERE id = ?", (g.current_user["id"],)).fetchone()
        packages_json = setting(db, "recharge_packages", app.config["RECHARGE_PACKAGES_JSON"])
        packages = list(parse_recharge_packages(packages_json).values())
        ledger = db.execute(
            "SELECT * FROM points_ledger WHERE user_id = ? ORDER BY id DESC LIMIT 30", (account["id"],)
        ).fetchall()
        recharges = db.execute(
            "SELECT * FROM recharge_orders WHERE user_id = ? ORDER BY id DESC LIMIT 20", (account["id"],)
        ).fetchall()
        tickets = db.execute(
            "SELECT * FROM support_tickets WHERE user_id = ? ORDER BY id DESC LIMIT 20", (account["id"],)
        ).fetchall()
        ticket_messages = load_ticket_messages(db, [ticket["id"] for ticket in tickets])
        pending_recharges = db.execute(
            "SELECT COUNT(*) FROM recharge_orders WHERE user_id = ? AND status = 'pending'", (account["id"],)
        ).fetchone()[0]
        open_tickets = db.execute(
            "SELECT COUNT(*) FROM support_tickets WHERE user_id = ? AND status != 'closed'", (account["id"],)
        ).fetchone()[0]
        return render_template("portal.html", account=account, ledger=ledger, recharges=recharges,
                               tickets=tickets, pending_recharges=pending_recharges, open_tickets=open_tickets,
                               ticket_messages=ticket_messages, packages=packages,
                               support_url=setting(db, "telegram_support_url"),
                               current_user=g.current_user)

    @app.get("/user/browser")
    @user_required
    def local_browser_lab():
        if not app.config["LOCAL_BROWSER_ENABLED"]:
            abort(404)
        browser_session = get_local_browser_session(g.current_user["id"])
        return render_template("local_browser.html", browser_session=browser_session,
                               current_user=g.current_user)

    @app.post("/user/browser/start")
    @user_required
    def start_local_browser():
        if not app.config["LOCAL_BROWSER_ENABLED"]:
            abort(404)
        target_url = request.form.get("url", "").strip()
        locale = request.form.get("locale", "zh-CN").strip()
        timezone_name = request.form.get("timezone", "Asia/Shanghai").strip()
        if not is_loopback_url(target_url):
            flash("本机浏览器只允许访问 http(s)://localhost、127.0.0.1 或 ::1。", "error")
            return redirect(url_for("local_browser_lab"))
        if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}", locale):
            flash("语言格式无效，例如 zh-CN 或 en-US。", "error")
            return redirect(url_for("local_browser_lab"))
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            flash("时区无效，请使用 IANA 时区，例如 Asia/Shanghai。", "error")
            return redirect(url_for("local_browser_lab"))

        sessions = app.extensions["local_browser_sessions"]
        lock = app.extensions["local_browser_lock"]
        user_id = g.current_user["id"]
        with lock:
            if user_id in sessions:
                flash("你已有一个本机测试会话，请先停止或在当前会话中导航。", "error")
                return redirect(url_for("local_browser_lab"))
            if len(sessions) >= app.config["LOCAL_BROWSER_MAX_SESSIONS"]:
                flash("本机测试运行器当前只允许一个活动会话。", "error")
                return redirect(url_for("local_browser_lab"))
            browser = None
            try:
                from cloakbrowser import launch

                browser = launch(headless=True, locale=locale, timezone=timezone_name)
                context = browser.new_context(locale=locale, timezone_id=timezone_name, service_workers="block")
                context.route("**/*", local_only_route)
                if hasattr(context, "route_web_socket"):
                    context.route_web_socket("**/*", local_only_websocket_route)
                page = context.new_page()
                page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                browser_session = {
                    "browser": browser,
                    "context": context,
                    "page": page,
                    "url": page.url,
                    "title": page.title(),
                    "locale": locale,
                    "timezone": timezone_name,
                    "last_activity": time.monotonic(),
                    "timer": None,
                }
                sessions[user_id] = browser_session
                schedule_local_session_expiry(user_id, browser_session, app)
            except Exception:
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:
                        pass
                current_app.logger.exception("Local browser launch failed")
                flash("本机浏览器启动失败。请确认 CloakBrowser 二进制和系统依赖已就绪。", "error")
                return redirect(url_for("local_browser_lab"))
        flash("本机测试会话已启动；非本机网络请求会被拦截。", "success")
        return redirect(url_for("local_browser_lab"))

    @app.post("/user/browser/navigate")
    @user_required
    def navigate_local_browser():
        if not app.config["LOCAL_BROWSER_ENABLED"]:
            abort(404)
        target_url = request.form.get("url", "").strip()
        if not is_loopback_url(target_url):
            flash("导航目标必须是本机 loopback 地址。", "error")
            return redirect(url_for("local_browser_lab"))
        browser_session = get_local_browser_session(g.current_user["id"])
        if browser_session is None:
            flash("当前没有运行中的本机浏览器会话。", "error")
            return redirect(url_for("local_browser_lab"))
        try:
            browser_session["page"].goto(target_url, wait_until="domcontentloaded", timeout=15000)
            browser_session["url"] = browser_session["page"].url
            browser_session["title"] = browser_session["page"].title()
            touch_local_session(g.current_user["id"], browser_session, app)
        except Exception:
            current_app.logger.exception("Local browser navigation failed")
            flash("本机页面无法打开；会话保持在受限模式。", "error")
        return redirect(url_for("local_browser_lab"))

    @app.get("/user/browser/screenshot")
    @user_required
    def local_browser_screenshot():
        if not app.config["LOCAL_BROWSER_ENABLED"]:
            abort(404)
        browser_session = get_local_browser_session(g.current_user["id"])
        if browser_session is None:
            abort(404)
        try:
            image = browser_session["page"].screenshot(type="png", full_page=False)
            touch_local_session(g.current_user["id"], browser_session, app)
        except Exception:
            abort(404)
        return Response(image, mimetype="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/user/browser/stop")
    @user_required
    def stop_local_browser():
        if not app.config["LOCAL_BROWSER_ENABLED"]:
            abort(404)
        stop_local_browser_session(g.current_user["id"], app)
        flash("本机测试会话已停止。", "success")
        return redirect(url_for("local_browser_lab"))

    @app.post("/account/password")
    @login_required
    def change_password():
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        if not check_password_hash(g.current_user["password_hash"], current_password):
            flash("当前密码不正确。", "error")
            destination = "admin_dashboard" if g.current_user["role"] == "admin" else "user_dashboard"
            return redirect(url_for(destination) + "#security")
        if len(new_password) < 12 or len(new_password) > 256:
            flash("新密码长度需要为 12 至 256 个字符。", "error")
            destination = "admin_dashboard" if g.current_user["role"] == "admin" else "user_dashboard"
            return redirect(url_for(destination) + "#security")
        new_session_version = secrets.token_urlsafe(24)
        g.db.execute(
            "UPDATE users SET password_hash = ?, session_version = ? WHERE id = ?",
            (generate_password_hash(new_password), new_session_version, g.current_user["id"]),
        )
        g.db.commit()
        session.clear()
        session["user_id"] = g.current_user["id"]
        session["session_version"] = new_session_version
        session["csrf_token"] = secrets.token_urlsafe(32)
        session.permanent = True
        flash("密码已更新，其他登录状态已失效。", "success")
        destination = "admin_dashboard" if g.current_user["role"] == "admin" else "user_dashboard"
        return redirect(url_for(destination) + "#security")

    @app.post("/user/recharges")
    @user_required
    def create_recharge():
        package_id = request.form.get("package", "")
        packages_json = setting(g.db, "recharge_packages", app.config["RECHARGE_PACKAGES_JSON"])
        package = parse_recharge_packages(packages_json).get(package_id)
        if package is None:
            flash("充值套餐尚未配置或已失效，请联系管理员。", "error")
            return redirect(url_for("user_dashboard") + "#recharges")
        points = package["points"]
        amount_cents = package["amount_cents"]
        order_ref = "RC-" + uuid.uuid4().hex[:12].upper()
        g.db.execute(
            "INSERT INTO recharge_orders (order_ref, user_id, points, amount_cents, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (order_ref, g.current_user["id"], points, amount_cents, utc_now()),
        )
        g.db.commit()
        flash(f"充值申请 {order_ref} 已提交，到账前需等待客服确认收款。", "success")
        return redirect(url_for("user_dashboard") + "#recharges")

    @app.post("/user/tickets")
    @user_required
    def create_ticket():
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        if not subject or len(subject) > 120 or not message or len(message) > 4000:
            flash("请填写工单主题和问题描述（主题不超过 120 字，描述不超过 4000 字）。", "error")
            return redirect(url_for("user_dashboard") + "#tickets")
        g.db.execute(
            "INSERT INTO support_tickets (user_id, subject, message, status, admin_response, created_at, updated_at) "
            "VALUES (?, ?, ?, 'open', '', ?, ?)",
            (g.current_user["id"], subject, message, utc_now(), utc_now()),
        )
        g.db.commit()
        flash("工单已提交，客服处理后会在此回复。", "success")
        return redirect(url_for("user_dashboard") + "#tickets")

    @app.post("/user/tickets/<int:ticket_id>/messages")
    @user_required
    def reply_to_ticket(ticket_id):
        message = request.form.get("message", "").strip()
        if not message or len(message) > 4000:
            flash("回复内容不能为空且不能超过 4000 字。", "error")
            return redirect(url_for("user_dashboard") + "#tickets")
        ticket = g.db.execute(
            "SELECT id, status FROM support_tickets WHERE id = ? AND user_id = ?",
            (ticket_id, g.current_user["id"]),
        ).fetchone()
        if ticket is None:
            abort(404)
        now = utc_now()
        g.db.execute(
            "INSERT INTO support_messages (ticket_id, author_id, author_role, body, created_at) "
            "VALUES (?, ?, 'user', ?, ?)",
            (ticket_id, g.current_user["id"], message, now),
        )
        status = "open" if ticket["status"] == "closed" else ticket["status"]
        g.db.execute("UPDATE support_tickets SET status = ?, updated_at = ? WHERE id = ?", (status, now, ticket_id))
        g.db.commit()
        flash("工单回复已发送。", "success")
        return redirect(url_for("user_dashboard") + "#tickets")

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", code=403, message="你没有权限访问此页面。"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", code=404, message="没有找到该记录或页面。"), 404

    return app


def initialize_database(app):
    db = sqlite3.connect(app.config["DATABASE_PATH"])
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
            points INTEGER NOT NULL DEFAULT 0 CHECK (points >= 0),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
            session_version TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS points_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            actor_id INTEGER REFERENCES users(id),
            delta INTEGER NOT NULL CHECK (delta != 0),
            balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
            reason TEXT NOT NULL,
            idempotency_key TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS recharge_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_ref TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            points INTEGER NOT NULL CHECK (points > 0),
            amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
            status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
            reviewed_by INTEGER REFERENCES users(id),
            reviewed_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            subject TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('open', 'in_progress', 'closed')),
            admin_response TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
            author_id INTEGER NOT NULL REFERENCES users(id),
            author_role TEXT NOT NULL CHECK (author_role IN ('admin', 'user')),
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ledger_user_id ON points_ledger(user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_recharges_status ON recharge_orders(status, id DESC);
        CREATE INDEX IF NOT EXISTS idx_tickets_status ON support_tickets(status, id DESC);
        CREATE INDEX IF NOT EXISTS idx_ticket_messages ON support_messages(ticket_id, id);
        """
    )
    user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
    if "session_version" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN session_version TEXT NOT NULL DEFAULT ''")
    ledger_columns = {row[1] for row in db.execute("PRAGMA table_info(points_ledger)")}
    if "idempotency_key" not in ledger_columns:
        db.execute("ALTER TABLE points_ledger ADD COLUMN idempotency_key TEXT")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_idempotency_key ON points_ledger(idempotency_key)")
    db.execute(
        "INSERT INTO support_messages (ticket_id, author_id, author_role, body, created_at) "
        "SELECT t.id, t.user_id, 'admin', t.admin_response, t.updated_at FROM support_tickets t "
        "WHERE t.admin_response != '' AND NOT EXISTS (SELECT 1 FROM support_messages m "
        "WHERE m.ticket_id = t.id AND m.author_role = 'admin' AND m.body = t.admin_response)"
    )
    username = app.config.get("BOOTSTRAP_ADMIN_USERNAME", "").strip()
    password = app.config.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    if username and password:
        if len(password) < 12:
            db.close()
            raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters")
        db.execute(
            "INSERT OR IGNORE INTO users (username, display_name, password_hash, role, created_at) VALUES (?, ?, ?, 'admin', ?)",
            (username, username, generate_password_hash(password), utc_now()),
        )
        db.commit()
    if app.config["APP_ENV"] == "production":
        admin_count = db.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]
        if admin_count == 0:
            db.close()
            raise RuntimeError("A bootstrap administrator is required for the first production start")
    db.close()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return g.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def csrf_token():
    token = session.get("csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def setting(db, key, default=""):
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def load_ticket_messages(db, ticket_ids):
    if not ticket_ids:
        return {}
    placeholders = ",".join("?" for _ in ticket_ids)
    rows = db.execute(
        f"SELECT * FROM support_messages WHERE ticket_id IN ({placeholders}) ORDER BY id", ticket_ids
    ).fetchall()
    messages = {ticket_id: [] for ticket_id in ticket_ids}
    for row in rows:
        messages[row["ticket_id"]].append(row)
    return messages


def is_loopback_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return False
        return hostname == "localhost" or ipaddress.ip_address(hostname).is_loopback
    except (ValueError, TypeError):
        return False


def local_only_route(route):
    if is_loopback_url(route.request.url):
        route.continue_()
    else:
        route.abort("blockedbyclient")


def local_only_websocket_route(websocket):
    if is_loopback_url(websocket.url):
        websocket.connect_to_server()
    else:
        websocket.close(code=1008, reason="Local-only browser session")


def set_setting(db, key, value):
    db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def get_local_browser_session(user_id):
    app = current_app._get_current_object()
    sessions = app.extensions["local_browser_sessions"]
    lock = app.extensions["local_browser_lock"]
    with lock:
        browser_session = sessions.get(user_id)
        if browser_session is None:
            return None
        if time.monotonic() - browser_session["last_activity"] >= app.config["LOCAL_BROWSER_IDLE_SECONDS"]:
            stop_local_browser_session(user_id, app)
            return None
        return browser_session


def touch_local_session(user_id, browser_session, app):
    browser_session["last_activity"] = time.monotonic()
    schedule_local_session_expiry(user_id, browser_session, app)


def schedule_local_session_expiry(user_id, browser_session, app):
    lock = app.extensions["local_browser_lock"]
    previous_timer = browser_session.get("timer")
    if previous_timer is not None:
        previous_timer.cancel()

    def expire():
        with lock:
            sessions = app.extensions["local_browser_sessions"]
            if sessions.get(user_id) is not browser_session:
                return
            if time.monotonic() - browser_session["last_activity"] < app.config["LOCAL_BROWSER_IDLE_SECONDS"]:
                schedule_local_session_expiry(user_id, browser_session, app)
                return
            sessions.pop(user_id, None)
            close_local_browser(browser_session)

    timer = threading.Timer(app.config["LOCAL_BROWSER_IDLE_SECONDS"], expire)
    timer.daemon = True
    browser_session["timer"] = timer
    timer.start()


def stop_local_browser_session(user_id, app):
    lock = app.extensions.get("local_browser_lock")
    sessions = app.extensions.get("local_browser_sessions")
    if lock is None or sessions is None:
        return
    with lock:
        browser_session = sessions.pop(user_id, None)
        if browser_session is not None:
            close_local_browser(browser_session)


def close_local_browser(browser_session):
    timer = browser_session.get("timer")
    if timer is not None:
        timer.cancel()
    try:
        browser_session["browser"].close()
    except Exception:
        pass


def close_all_local_browsers(app):
    sessions = app.extensions.get("local_browser_sessions", {})
    lock = app.extensions.get("local_browser_lock")
    if lock is None:
        return
    with lock:
        active_sessions = list(sessions.values())
        sessions.clear()
        for browser_session in active_sessions:
            close_local_browser(browser_session)


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class InsufficientPointsError(ValueError):
    pass


def charge_points(db, user_id, amount, reason, idempotency_key):
    db.row_factory = sqlite3.Row
    if type(amount) is not int or not 1 <= amount <= 1_000_000:
        raise ValueError("amount must be a positive integer within the usage limit")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 200:
        raise ValueError("reason must contain 1 to 200 characters")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 128:
        raise ValueError("idempotency_key must contain 1 to 128 characters")
    db.execute("BEGIN IMMEDIATE")
    existing = db.execute("SELECT * FROM points_ledger WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
    if existing is not None:
        if existing["user_id"] != user_id or existing["delta"] != -amount or existing["reason"] != reason.strip():
            db.rollback()
            raise ValueError("idempotency key was already used for a different charge")
        db.commit()
        return existing["balance_after"]
    user = db.execute("SELECT points FROM users WHERE id = ? AND role = 'user'", (user_id,)).fetchone()
    if user is None:
        db.rollback()
        raise ValueError("user not found")
    balance = user["points"] - amount
    if balance < 0:
        db.rollback()
        raise InsufficientPointsError("insufficient points")
    db.execute("UPDATE users SET points = ? WHERE id = ?", (balance, user_id))
    db.execute(
        "INSERT INTO points_ledger (user_id, delta, balance_after, reason, idempotency_key, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, -amount, balance, reason.strip(), idempotency_key, utc_now()),
    )
    db.commit()
    return balance


def parse_recharge_packages(raw):
    if not isinstance(raw, str) or len(raw) > 10000:
        raise ValueError("套餐配置过大或格式错误。")
    try:
        payload = json.loads(raw or "{}")
    except (ValueError, TypeError):
        raise ValueError("套餐配置必须是有效的 JSON 对象。") from None
    if not isinstance(payload, dict) or len(payload) > 20:
        raise ValueError("套餐配置必须是最多 20 项的 JSON 对象。")
    result = {}
    for package_id, package in payload.items():
        if (not isinstance(package_id, str) or not package_id.isascii()
                or not package_id.replace("-", "").replace("_", "").isalnum()
                or len(package_id) > 32 or not isinstance(package, dict)):
            raise ValueError("套餐编号只允许使用英文字母、数字、短横线或下划线。")
        points = package.get("points")
        amount_cents = package.get("amount_cents")
        if (type(points) is not int or type(amount_cents) is not int
                or not 1 <= points <= 1_000_000_000
                or not 1 <= amount_cents <= 100_000_000):
            raise ValueError("每个套餐的积分和金额（分）都必须是正整数且不超过上限。")
        result[package_id] = {
            "id": package_id,
            "points": points,
            "amount_cents": amount_cents,
        }
    return result


def is_telegram_url(value):
    if not isinstance(value, str) or len(value) > 500:
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and parsed.hostname in {"t.me", "telegram.me"}
                and parsed.port in (None, 443) and parsed.username is None and parsed.password is None
                and bool(parsed.path.strip("/")))
    except ValueError:
        return False


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=False)
