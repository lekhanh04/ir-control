"""Cấu hình chung cho kiểm thử: mỗi test dùng một CSDL tạm, chế độ giả lập, dữ liệu mẫu.

Dữ liệu mẫu (seed.py) — id cố định vì CSDL luôn mới:
  Phòng: 1 Phòng khách, 2 Phòng ngủ, 3 Phòng họp
  Thiết bị: 1 Điều hòa (P.khách, RAW: nút 1–5), 2 Tivi (P.khách, SAMSUNG: nút 6–19, 19 = custom_1 "Netflix"),
            3 Quạt điều hòa (P.ngủ: 20–22), 4 Điều hòa (P.ngủ: 23 power), 5 Máy chiếu (P.họp, NEC: 24–26)
  Bộ phát: esp-a1f3 (P.khách, bật), esp-7c20 (P.ngủ, bật), esp-91be (P.họp, mất kết nối), esp-0d44 (chưa gán, bật)
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from irhub import create_app  # noqa: E402
from irhub.config import Config  # noqa: E402
from irhub.seed import seed_demo  # noqa: E402


@pytest.fixture
def make_app(tmp_path):
    def make(**over):
        attrs = dict(DB_PATH=str(tmp_path / 'test.db'), SIMULATE=True, SEED_DEMO=True, PIN='', ACK_TIMEOUT_S=0.3)
        attrs.update(over)
        cfg = type('TestConfig', (Config,), attrs)
        app, hub = create_app(cfg)
        app.config['TESTING'] = True
        if cfg.SEED_DEMO:
            seed_demo(hub.db)
        hub.transport.start()      # bộ phát giả gửi status → online
        return app, hub
    return make


@pytest.fixture
def app_hub(make_app):
    return make_app()


@pytest.fixture
def hub(app_hub):
    return app_hub[1]


@pytest.fixture
def client(app_hub):
    return app_hub[0].test_client()
