"""Nâng cấp một file CSDL kiểu cũ (v1, chưa đánh số) lên phiên bản mới nhất mà không mất dữ liệu."""
import glob
import sqlite3

import pytest

from irhub import migrations

V1 = """
CREATE TABLE rooms (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, created_at INTEGER NOT NULL);
CREATE TABLE slaves (id TEXT PRIMARY KEY, name TEXT NOT NULL, room_id INTEGER UNIQUE REFERENCES rooms(id),
  online INTEGER NOT NULL DEFAULT 0, ip TEXT, rssi INTEGER, fw TEXT, last_seen INTEGER);
CREATE TABLE devices (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id INTEGER NOT NULL REFERENCES rooms(id),
  type TEXT NOT NULL CHECK (type IN ('ac','tv','fan','projector','other')), name TEXT NOT NULL, brand TEXT, created_at INTEGER NOT NULL);
CREATE TABLE commands (id INTEGER PRIMARY KEY AUTOINCREMENT, device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  key TEXT NOT NULL, label TEXT NOT NULL, kind TEXT NOT NULL, protocol TEXT, value TEXT, address TEXT, command TEXT, bits INTEGER,
  carrier_khz INTEGER, raw TEXT, match_pct INTEGER, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, device_id INTEGER, room_name TEXT, device_name TEXT,
  key TEXT, label TEXT, source TEXT NOT NULL, text TEXT, slave_id TEXT, status TEXT NOT NULL, latency_ms INTEGER);
CREATE INDEX idx_history_at ON history (at DESC);

INSERT INTO rooms VALUES (1, 'Phòng khách', 1);
INSERT INTO slaves VALUES ('esp-1', 'Bộ phát', 1, 1, '1.2.3.4', -50, '1.0', 5);
INSERT INTO devices VALUES (1, 1, 'tv', 'Tivi', 'Sony', 1), (2, 1, 'tv', 'tivi', '', 2);
INSERT INTO commands VALUES (1, 1, 'power', 'Nguồn', 'protocol', 'NEC', '0x1', '0x00', '0x01', 32, 38, NULL, 100, 1, 1),
                            (2, 1, 'mute', 'nguồn', 'protocol', 'NEC', '0x2', '0x00', '0x02', 32, 38, NULL, 100, 1, 1),
                            (3, 2, 'power', 'Nguồn', 'raw', NULL, NULL, NULL, NULL, NULL, 38, 'không phải json', 90, 1, 1);
INSERT INTO history VALUES (1, 10, 1, 'Phòng khách', 'Tivi', 'power', 'Nguồn', 'web', NULL, 'esp-1', 'ok', 120);
"""


@pytest.fixture
def v1_db(tmp_path):
    path = str(tmp_path / 'irhub.db')
    c = sqlite3.connect(path)
    c.executescript(V1)
    c.close()
    return path


def q(path, sql):
    c = sqlite3.connect(path)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


def test_upgrade_v1_to_latest(v1_db):
    logs = []
    assert migrations.migrate(v1_db, log=logs.append) == migrations.LATEST == 5
    assert q(v1_db, 'PRAGMA user_version')[0][0] == 5
    assert glob.glob(v1_db + '.bak-v1-*'), 'phải có bản sao lưu trước khi nâng cấp'
    # tên trùng (không phân biệt hoa thường) được đổi
    assert [r[0] for r in q(v1_db, 'SELECT name FROM devices ORDER BY id')] == ['Tivi', 'tivi (2)']
    assert [r[0] for r in q(v1_db, 'SELECT label FROM commands ORDER BY id')] == ['Nguồn', 'nguồn (2)']
    # mã RAW hỏng bị bỏ, dữ liệu khác giữ nguyên
    assert q(v1_db, 'SELECT COUNT(*) FROM commands')[0][0] == 2
    assert q(v1_db, 'SELECT source, status, latency_ms FROM history') == [('web', 'ok', 120)]
    assert q(v1_db, 'SELECT id, room_id FROM slaves') == [('esp-1', 1)]
    # bảng mới của v3 có mặt (v4 không thêm bảng), history nhận nguồn 'scene'
    tables = {r[0] for r in q(v1_db, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {'scenes', 'scene_steps', 'schedules', 'device_types'} <= tables
    c = sqlite3.connect(v1_db)
    c.execute("INSERT INTO history (at, device_name, source, text, status) VALUES (1, 'Tivi', 'scene', 'Đi ngủ', 'ok')")
    c.commit()
    c.close()
    idx = {r[0] for r in q(v1_db, "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'history'")}
    assert {'idx_history_at', 'idx_history_device'} <= idx


def test_latest_is_noop(v1_db):
    migrations.migrate(v1_db, log=lambda *_: None)
    assert migrations.migrate(v1_db, log=lambda *_: None) == 5
    assert len(glob.glob(v1_db + '.bak-*')) == 1


def test_newer_db_is_refused(tmp_path):
    path = str(tmp_path / 'new.db')
    migrations.migrate(path)
    c = sqlite3.connect(path)
    c.execute('PRAGMA user_version = 99')
    c.close()
    with pytest.raises(RuntimeError):
        migrations.migrate(path)


def test_fresh_db(tmp_path):
    path = str(tmp_path / 'fresh.db')
    assert migrations.migrate(path) == 5
    assert q(path, "SELECT value FROM settings WHERE key = 'history.retention_days'") == [('90',)]
