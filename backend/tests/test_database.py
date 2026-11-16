"""Độ bền của phần CSDL: lỗi không làm chết MQTT, dữ liệu rác, nâng cấp, ghi thẻ nhớ, sao lưu / khôi phục."""
import io
import os
import sqlite3
import time
import types

import pytest

from irhub import backup, migrations
from irhub.db import now_ms
from irhub.transport import MqttTransport


# ---------- 1. Lỗi CSDL trong callback MQTT không được làm chết luồng mạng ----------
def test_mqtt_callback_swallows_db_errors(hub, capsys):
    t = MqttTransport(hub)

    def boom(*a):
        raise sqlite3.OperationalError('database is locked')
    hub.on_slave_status = boom
    msg = types.SimpleNamespace(topic='irhub/slave/esp-x/status', payload=b'{"online": true}')
    t._on_message(None, None, msg)            # không được ném lỗi ra ngoài (paho sẽ dừng luồng mạng)
    assert 'database is locked' in capsys.readouterr().out
    # payload lạ (không phải object JSON, req không băm được) cũng không làm hỏng
    t._on_message(None, None, types.SimpleNamespace(topic='irhub/slave/esp-x/ack', payload=b'[1,2]'))
    t._on_message(None, None, types.SimpleNamespace(topic='irhub/slave/esp-x/ack', payload=b'{"req": [1]}'))


# ---------- 2. Phòng mặc định giọng nói: không nhận rác, đọc rác không lỗi ----------
@pytest.mark.parametrize('bad', ['abc', '1', 1.5, True, 999])
def test_voice_default_room_validated(client, bad):
    r = client.post('/api/voice', json={'default_room_id': bad})
    assert r.status_code == 400 and r.get_json()['error'] == 'default_room'
    assert client.get('/api/voice').status_code == 200


def test_voice_settings_tolerate_garbage_in_db(hub, client):
    hub.db.set_setting('voice.default_room_id', 'abc')
    hub.db.set_setting('voice.sensitivity', '???')
    v = client.get('/api/voice').get_json()
    assert v['default_room_id'] is None and v['sensitivity'] == 'mid'
    assert hub.voice.match('bật tivi phòng khách')['key'] == 'power'


def test_voice_default_room_ok_and_cleared(client):
    assert client.post('/api/voice', json={'default_room_id': 3}).get_json()['default_room_id'] == 3
    assert client.post('/api/voice', json={'default_room_id': None}).get_json()['default_room_id'] is None


# ---------- 3. Nâng cấp: CSDL từ v1 phải có cùng cấu trúc với CSDL mới ----------
def _schema(path):
    c = sqlite3.connect(path)
    try:
        rows = c.execute("SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'").fetchall()
    finally:
        c.close()
    norm = lambda s: ' '.join(s.replace('IF NOT EXISTS ', '').replace('"', '').split())   # noqa: E731
    return {n: norm(s) for n, s in rows}


def test_upgraded_schema_equals_fresh_schema(tmp_path):
    from test_migrations import V1
    old, new = str(tmp_path / 'old.db'), str(tmp_path / 'new.db')
    c = sqlite3.connect(old)
    c.executescript(V1 + "INSERT INTO rooms VALUES (5, 'BẾP', 2), (6, 'bếp', 3), (9, 'Xóa', 4); DELETE FROM rooms WHERE id = 9;")
    c.close()
    migrations.migrate(old, log=lambda *a: None)
    migrations.migrate(new, log=lambda *a: None)
    assert _schema(old) == _schema(new)
    c = sqlite3.connect(old)
    c.execute('PRAGMA foreign_keys = ON')
    assert [r[0] for r in c.execute('SELECT name FROM rooms ORDER BY id')] == ['Phòng khách', 'BẾP', 'bếp (2)']
    assert c.execute('PRAGMA foreign_key_check').fetchall() == []
    # id phòng đã xóa (9) không được dùng lại
    assert c.execute("INSERT INTO rooms (name, created_at) VALUES ('Mới', 1)").lastrowid == 10
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO rooms (name, created_at) VALUES ('   ', 1)")      # CHECK độ dài đã có
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO rooms (name, created_at) VALUES ('phòng khách', 1)")   # UNIQUE NOCASE đã có
    c.close()


# ---------- 4. Kiểu dữ liệu ----------
@pytest.mark.parametrize('rid', ['1', True, 1.0, None])
def test_device_room_id_must_be_int(client, rid):
    assert client.post('/api/devices', json={'name': 'Loa', 'type': 'other', 'room_id': rid}).status_code == 400


@pytest.mark.parametrize('rid', ['2', True, 99])
def test_slave_room_id_must_be_int(client, rid):
    assert client.patch('/api/slaves/esp-0d44', json={'room_id': rid}).status_code == 400


def test_device_slave_id_must_be_string(client):
    assert client.patch('/api/devices/2', json={'slave_id': 123}).status_code == 400


# ---------- 5. Ngữ cảnh trống ----------
def test_schedule_of_empty_scene_is_disabled(client, hub):
    sc = client.post('/api/scenes', json={'name': 'Chỉ tivi', 'steps': [{'command_id': 6}]}).get_json()
    s = client.post('/api/schedules', json={'scene_id': sc['id'], 'at_time': '07:00'}).get_json()
    assert s['scene_steps'] == 1
    client.delete('/api/devices/2')
    assert client.get('/api/schedules').get_json()[0]['scene_steps'] == 0
    now = time.mktime((2026, 11, 16, 7, 0, 5, 0, 0, -1))
    assert hub.run_due_schedules(now) == []
    assert client.get('/api/schedules').get_json()[0]['enabled'] is False


# ---------- 6. Xóa phòng mặc định ----------
def test_deleting_default_room_clears_setting(client):
    client.post('/api/voice', json={'default_room_id': 3})
    client.delete('/api/devices/5')
    assert client.delete('/api/rooms/3').status_code == 200
    assert client.get('/api/voice').get_json()['default_room_id'] is None


# ---------- 7. synchronous=NORMAL ----------
def test_connection_pragmas(hub):
    c = hub.db.connect()
    try:
        assert c.execute('PRAGMA synchronous').fetchone()[0] == 1          # NORMAL
        assert c.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert c.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    finally:
        c.close()


# ---------- 8. Status bộ phát chỉ ghi CSDL khi cần ----------
def _count_slave_writes(hub):
    calls = []
    orig = hub.db.run

    def run(sql, args=()):
        if 'slaves' in sql:
            calls.append(sql)
        return orig(sql, args)
    hub.db.run = run
    return calls


def test_periodic_status_does_not_write_db(hub, client):
    writes = _count_slave_writes(hub)
    for i in range(50):
        hub.on_slave_status('esp-a1f3', {'online': True, 'ip': '192.168.1.51', 'rssi': -50 - i % 7, 'fw': '1.0.2'})
    assert writes == []
    s = next(x for x in client.get('/api/slaves').get_json() if x['id'] == 'esp-a1f3')
    assert s['rssi'] == -50 - 49 % 7 and s['last_seen'] >= now_ms() - 2000      # giao diện vẫn thấy số mới


def test_status_writes_when_something_changes(hub):
    writes = _count_slave_writes(hub)
    hub.on_slave_status('esp-a1f3', {'online': True, 'ip': '192.168.1.99'})       # đổi IP
    hub.on_slave_status('esp-a1f3', {'online': True, 'fw': '2.0.0'})              # đổi firmware
    hub.on_slave_status('esp-a1f3', {'online': False})                            # LWT
    hub.on_slave_status('esp-new1', {'online': True})                             # bộ phát mới
    assert len(writes) == 4
    row = hub.db.one("SELECT * FROM slaves WHERE id = 'esp-a1f3'")
    assert (row['ip'], row['fw'], row['online']) == ('192.168.1.99', '2.0.0', 0)


def test_status_refreshes_db_after_interval(hub):
    hub.cfg.SLAVE_DB_REFRESH_S = 0
    writes = _count_slave_writes(hub)
    hub.on_slave_status('esp-a1f3', {'online': True, 'rssi': -70})
    assert len(writes) == 1 and hub.db.one("SELECT rssi FROM slaves WHERE id = 'esp-a1f3'")['rssi'] == -70


def test_stale_detection_uses_memory(hub):
    hub.on_slave_status('esp-a1f3', {'online': True})
    assert hub.check_stale() == []                                   # vừa gửi status, DB last_seen có thể cũ
    seen = hub._live['esp-a1f3']['last_seen']
    stale = hub.check_stale(now=seen + hub.cfg.SLAVE_STALE_S * 1000 + 1)
    assert 'esp-a1f3' in stale
    row = hub.db.one("SELECT online, last_seen FROM slaves WHERE id = 'esp-a1f3'")
    assert (row['online'], row['last_seen']) == (0, seen)            # ghi đúng thời điểm thấy lần cuối


def test_bad_status_payload_ignored(hub):
    hub.on_slave_status('esp-a1f3', ['not', 'a', 'dict'])
    hub.on_slave_status('esp-a1f3', {'online': True, 'rssi': 'mạnh', 'ip': 123})
    assert hub.db.one("SELECT ip FROM slaves WHERE id = 'esp-a1f3'")['ip'] == '192.168.1.51'


# ---------- 9. Sao lưu tự động ----------
def test_daily_backup_once_per_day_and_pruned(hub):
    d = backup.backup_dir(hub.db.path)
    day = 86400
    t0 = time.mktime((2026, 11, 1, 12, 0, 0, 0, 0, -1))
    for i in range(10):
        assert backup.daily_backup(hub.db, keep=7, now=t0 + i * day, log=lambda *a: None)
    assert backup.daily_backup(hub.db, keep=7, now=t0 + 9 * day, log=lambda *a: None) is None   # cùng ngày: bỏ qua
    files = sorted(os.listdir(d))
    assert files == ['irhub-202611%02d.db' % n for n in range(4, 11)]
    assert backup.check_file(os.path.join(d, files[-1])) == migrations.LATEST
    assert backup.daily_backup(hub.db, keep=0) is None


def test_backups_api_lists_and_downloads(client, hub):
    hub.auto_backup()
    items = client.get('/api/backups').get_json()['items']
    assert len(items) == 1
    r = client.get('/api/backups/' + items[0]['name'])
    assert r.status_code == 200 and r.data[:16] == b'SQLite format 3\x00'
    assert client.get('/api/backups/..%2Firhub.db').status_code == 404
    assert client.get('/api/backups/khong-co.db').status_code == 404


# ---------- 10. Khôi phục ----------
def test_restore_from_uploaded_backup(client, hub):
    secret = hub.db.get_setting('auth.secret')
    data = client.get('/api/backup').data                      # bản sao lúc có 3 phòng
    client.post('/api/rooms', json={'name': 'Bếp'})
    client.delete('/api/devices/1')
    r = client.post('/api/restore', data={'file': (io.BytesIO(data), 'irhub.db')}, content_type='multipart/form-data')
    assert r.status_code == 200, r.get_json()
    safety = r.get_json()['safety_backup']
    assert [x['name'] for x in client.get('/api/rooms').get_json()] == ['Phòng khách', 'Phòng ngủ', 'Phòng họp']
    assert any(d['id'] == 1 for d in client.get('/api/devices').get_json())
    assert hub.db.get_setting('auth.secret') == secret            # không ai bị đăng xuất
    # bản sao an toàn chứa dữ liệu ngay trước khi khôi phục (có phòng Bếp)
    assert safety in [b['name'] for b in client.get('/api/backups').get_json()['items']]
    c = sqlite3.connect(os.path.join(backup.backup_dir(hub.db.path), safety))
    assert ('Bếp',) in c.execute('SELECT name FROM rooms').fetchall()
    c.close()
    # bộ phát giả gửi lại status → vẫn điều khiển được ngay
    assert client.post('/api/send', json={'command_id': 6}).get_json()['status'] == 'ok'


def test_restore_from_auto_backup_by_name(client, hub):
    name = hub.auto_backup()
    client.post('/api/rooms', json={'name': 'Bếp'})
    assert client.post('/api/restore', json={'name': name}).status_code == 200
    assert 'Bếp' not in [x['name'] for x in client.get('/api/rooms').get_json()]
    assert client.post('/api/restore', json={'name': '../irhub.db'}).status_code == 404


def test_restore_upgrades_old_backup(client, tmp_path):
    from test_migrations import V1
    p = str(tmp_path / 'old.db')
    c = sqlite3.connect(p)
    c.executescript(V1)
    c.close()
    with open(p, 'rb') as f:
        r = client.post('/api/restore', data={'file': (io.BytesIO(f.read()), 'old.db')}, content_type='multipart/form-data')
    assert r.status_code == 200
    assert client.get('/api/system').get_json()['db_schema'] == migrations.LATEST
    assert [d['name'] for d in client.get('/api/devices').get_json()] == ['Tivi', 'tivi (2)']


def _upload(client, raw):
    return client.post('/api/restore', data={'file': (io.BytesIO(raw), 'x.db')}, content_type='multipart/form-data')


def test_restore_rejects_bad_files(client, tmp_path):
    assert _upload(client, b'hello world').get_json()['error'] == 'bad_backup'
    # SQLite hợp lệ nhưng không phải CSDL của bộ trung tâm
    p = str(tmp_path / 'other.db')
    c = sqlite3.connect(p)
    c.execute('CREATE TABLE t (x)')
    c.commit()
    c.close()
    with open(p, 'rb') as f:
        assert _upload(client, f.read()).get_json()['error'] == 'bad_backup'
    # bản sao từ phần mềm mới hơn
    data = client.get('/api/backup').data
    p2 = str(tmp_path / 'newer.db')
    with open(p2, 'wb') as f:
        f.write(data)
    c = sqlite3.connect(p2)
    c.execute('PRAGMA user_version = 99')
    c.close()
    with open(p2, 'rb') as f:
        r = _upload(client, f.read())
    assert r.status_code == 400 and 'mới hơn' in r.get_json()['message']
    # dữ liệu hiện tại không bị đụng tới
    assert len(client.get('/api/rooms').get_json()) == 3


def test_system_db_size_counts_wal(hub, client):
    assert client.get('/api/system').get_json()['db_size_kb'] == hub.db.size_bytes() // 1024
