"""
auth_routes.py — Login / Logout endpoints + session guard

Termasuk integrasi SSO dengan central login service (sso-login): cookie
sso_token (JWT ditandatangani SSO_SECRET) di-bootstrap jadi Flask session
di sini, jadi user yang sudah login di sso-login (atau service lain yang
ikut SSO) tidak perlu login ulang.
"""

import os
from functools import wraps
from urllib.parse import quote
import jwt
from flask import Blueprint, request, jsonify, session, redirect, url_for, send_from_directory
import db

auth_bp = Blueprint("auth", __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

PUBLIC_PREFIXES = ("/login", "/api/auth/", "/health", "/static/")

# ─── SSO (Central Login Service) ────────────────────────────────────────
# SSO_SECRET wajib sama persis dengan yang dipakai sso-login. Kalau kosong,
# fitur SSO nonaktif (app ini tetap jalan dengan login lokal seperti biasa).
SSO_SECRET    = os.environ.get("SSO_SECRET", "")
SSO_LOGIN_URL = os.environ.get("SSO_LOGIN_URL", "").rstrip("/")


def _verify_sso_token(token):
    """Verifikasi JWT dari sso-login, return username kalau valid."""
    if not SSO_SECRET or not token:
        return None
    try:
        payload = jwt.decode(token, SSO_SECRET, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def _current_user():
    """Ambil user dari Flask session. Session yang asalnya dari bootstrap SSO
    cuma dianggap valid selama cookie sso_token masih valid & untuk user yang
    sama — supaya logout di central login (atau di service SSO lain) langsung
    berlaku di sini juga, tanpa nunggu session ini kedaluwarsa sendiri."""
    if not session.get("user_id"):
        return None
    if session.get("via_sso"):
        if _verify_sso_token(request.cookies.get("sso_token")) != session.get("username"):
            session.clear()
            return None
    return {"id": session["user_id"], "username": session["username"], "role": session["role"]}


def _bootstrap_sso_session():
    """Kalau ada cookie sso_token valid & user-nya aktif, isi Flask session
    untuk-nya. Return True kalau berhasil bootstrap."""
    username = _verify_sso_token(request.cookies.get("sso_token"))
    if not username:
        return False
    user = db.get_user_by_username(username)
    if not user or not user.get("is_active"):
        return False
    session.permanent   = True
    session["user_id"]  = user["id"]
    session["username"] = user["username"]
    session["role"]     = user["role"]
    session["via_sso"]  = True
    return True


def _sso_login_redirect():
    """URL tujuan redirect kalau user belum login sama sekali."""
    if SSO_LOGIN_URL:
        return f"{SSO_LOGIN_URL}/login?redirect={quote(request.url, safe='')}"
    return "/login"


def _sso_logout_redirect():
    """URL tujuan setelah logout, supaya sesi SSO pusat ikut dihapus."""
    return f"{SSO_LOGIN_URL}/logout" if SSO_LOGIN_URL else "/login"
# ──────────────────────────────────────────────────────────────────────


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not (_current_user() or _bootstrap_sso_session()):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized", "redirect": "/login"}), 401
            return redirect(_sso_login_redirect())
        return f(*args, **kwargs)
    return decorated


@auth_bp.route("/login")
def login_page():
    if _current_user() or _bootstrap_sso_session():
        return redirect("/")
    return send_from_directory(STATIC_DIR, "login.html")


@auth_bp.route("/api/auth/login", methods=["POST"])
def api_login():
    data     = request.json or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or not password:
        return jsonify({"error": "Username dan password wajib diisi"}), 400

    user = db.verify_user(username, password)
    if not user:
        return jsonify({"error": "Username atau password salah"}), 401

    session.permanent = True
    session["user_id"]   = user["id"]
    session["username"]  = user["username"]
    session["role"]      = user["role"]

    return jsonify({"ok": True, "username": user["username"], "role": user["role"]})


@auth_bp.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.clear()
    # redirect: kalau session ini asalnya dari SSO, cookie sso_token (domain-lebar)
    # masih ada dan bikin user auto-login lagi kalau cuma dikirim balik ke /login
    # lokal. Frontend diarahkan ke /logout milik sso-login dulu supaya sesi
    # pusatnya ikut kehapus.
    return jsonify({"ok": True, "redirect": _sso_logout_redirect()})


@auth_bp.route("/api/auth/me")
def api_me():
    user = _current_user()
    if not user:
        return jsonify({"authenticated": False}), 401
    return jsonify({
        "authenticated": True,
        "username": user["username"],
        "role": user["role"],
    })
