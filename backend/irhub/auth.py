"""Đăng nhập bằng mã PIN (đặt IRHUB_PIN trong backend/.env; để trống = không cần đăng nhập).

- Đăng nhập đúng → cookie phiên ký bằng khóa bí mật lưu trong CSDL (settings 'auth.secret'), nhớ 1 năm.
- Đổi PIN → mọi trình duyệt đã đăng nhập phải nhập lại (cookie lưu dấu của PIN cũ).
- Sai 5 lần liên tiếp từ một địa chỉ IP → khóa 60 giây.
- Mọi đường dẫn /api/... (trừ /api/auth, /api/login, /api/logout) đều cần đăng nhập. Trang web tĩnh thì không.
"""
import datetime
import hashlib
import hmac
import secrets
import threading
import time

from flask import jsonify, request, session

OPEN_PATHS = ('/api/auth', '/api/login', '/api/logout')
MAX_FAILS = 5
LOCK_S = 60


class Auth:
    def __init__(self, app, hub):
        self.hub = hub
        self.pin = hub.cfg.PIN
        self._fails = {}           # ip → (số lần sai, khóa tới thời điểm)
        self._lock = threading.Lock()
        secret = hub.db.get_setting('auth.secret')
        if not secret:
            secret = secrets.token_hex(32)
            hub.db.set_setting('auth.secret', secret)
        app.secret_key = secret
        app.config.update(SESSION_COOKIE_NAME='irhub', SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                          PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=365))
        self._mark = hashlib.sha256((secret + ':' + self.pin).encode()).hexdigest()[:16]
        app.before_request(self._guard)

    @property
    def required(self):
        return bool(self.pin)

    def ok(self):
        return not self.required or session.get('pin') == self._mark

    def _guard(self):
        p = request.path
        if self.required and p.startswith('/api/') and p not in OPEN_PATHS and not self.ok():
            return jsonify(error='auth', message='Cần nhập mã PIN'), 401
        return None

    def status(self):
        return {'required': self.required, 'ok': self.ok()}

    def login(self, pin):
        """Trả (True, None) hoặc (False, (http_status, code, message))."""
        if not self.required:
            return True, None
        ip = request.remote_addr or '?'
        now = time.time()
        with self._lock:
            fails, until = self._fails.get(ip, (0, 0))
            if until > now:
                return False, (429, 'locked', 'Nhập sai nhiều lần. Thử lại sau %d giây' % int(until - now + 1))
            if isinstance(pin, str) and hmac.compare_digest(pin.strip().encode(), self.pin.encode()):
                self._fails.pop(ip, None)
                session.permanent = True
                session['pin'] = self._mark
                return True, None
            fails += 1
            self._fails[ip] = (0, now + LOCK_S) if fails >= MAX_FAILS else (fails, 0)
        return False, (401, 'bad_pin', 'Mã PIN không đúng')

    def logout(self):
        session.pop('pin', None)
