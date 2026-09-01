"""
rate_limit.py — Shared Flask-Limiter instance.

Modul terpisah (bukan didefinisikan langsung di app.py) supaya blueprint
(custom_chart_routes.py dll) bisa import `limiter` untuk decorate route-nya
sendiri tanpa circular import dengan app.py (yang meng-import blueprint itu).
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
