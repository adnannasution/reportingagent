"""
auth_routes.py — Login / Logout endpoints + session guard
"""

import os
from functools import wraps
from flask import Blueprint, request, jsonify, session, redirect, url_for, send_from_directory
import db

auth_bp = Blueprint("auth", __name__)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

PUBLIC_PREFIXES = ("/login", "/api/auth/", "/health", "/static/")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized", "redirect": "/login"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


@auth_bp.route("/login")
def login_page():
    if session.get("user_id"):
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
    return jsonify({"ok": True})


@auth_bp.route("/api/auth/me")
def api_me():
    if not session.get("user_id"):
        return jsonify({"authenticated": False}), 401
    return jsonify({
        "authenticated": True,
        "username": session["username"],
        "role": session["role"],
    })
