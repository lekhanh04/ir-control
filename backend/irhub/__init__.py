"""Bộ trung tâm điều khiển hồng ngoại: Flask + SQLite + MQTT."""
import os

from flask import Flask, jsonify, send_from_directory

from .config import Config
from .hub import Hub


def create_app(cfg=Config):
    app = Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False
    hub = Hub(cfg)
    app.extensions['irhub'] = hub

    from .api import bp, dev
    app.register_blueprint(bp)
    if cfg.SIMULATE:
        app.register_blueprint(dev)

    @app.route('/api/<path:path>', methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
    def api_not_found(path):
        # Đường dẫn /api/... không tồn tại: trả JSON thay vì trang web, để dễ dò lỗi
        return jsonify(error='not_found', message='Không có API /api/%s' % path), 404

    @app.get('/')
    def index():
        return send_from_directory(cfg.WEB_DIR, 'index.html')

    @app.get('/<path:path>')
    def static_files(path):
        if os.path.isfile(os.path.join(cfg.WEB_DIR, path)):
            return send_from_directory(cfg.WEB_DIR, path)
        return send_from_directory(cfg.WEB_DIR, 'index.html')

    @app.after_request
    def no_cache_js(resp):
        # Tránh trình duyệt điện thoại giữ bản JS cũ khi bạn đang sửa code
        if resp.mimetype in ('text/javascript', 'application/javascript', 'text/css', 'text/html'):
            resp.headers['Cache-Control'] = 'no-cache'
        return resp

    return app, hub
