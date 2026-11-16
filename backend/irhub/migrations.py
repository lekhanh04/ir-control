"""Tạo mới hoặc nâng cấp cấu trúc CSDL mà không mất dữ liệu.

Phiên bản cấu trúc lưu trong PRAGMA user_version:
    0/1  bản đầu tiên (chưa đánh số): mỗi phòng một bộ phát, loại thiết bị cố định trong CHECK
    2    nhiều bộ phát mỗi phòng + devices.slave_id, bảng device_types, tên không trùng,
         history.status 'not_understood', chỉ mục, thời gian giữ lịch sử
    3    ngữ cảnh (scenes, scene_steps), hẹn giờ (schedules), history.source thêm 'scene', 'schedule'
    4    dựng lại bảng rooms theo đúng schema.sql (CSDL nâng cấp từ v1 còn giữ bảng rooms cũ:
         thiếu CHECK độ dài, UNIQUE không NOCASE)
    5    bảng device_state (nhiệt độ ước tính), schedule_runs (kết quả hẹn giờ), ui_order (thứ tự sắp xếp)

Quy trình khi đổi cấu trúc về sau:
    1. Sửa schema.sql cho đúng cấu trúc mới (dùng khi tạo CSDL mới).
    2. Viết hàm _vN_to_vN+1(c, json_ok) bên dưới, thêm vào STEPS, tăng LATEST.
Trước khi nâng cấp, file CSDL được sao lưu thành irhub.db.bak-v<cũ>-<thời gian>.
"""
import json
import os
import re
import sqlite3
import time

LATEST = 5
SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')


def json_supported(c):
    try:
        c.execute("SELECT json_valid('[]')")
        return True
    except sqlite3.OperationalError:
        return False


def schema_statements(json_ok):
    """Tách schema.sql thành từng câu lệnh (để chạy trong một transaction)."""
    with open(SCHEMA, encoding='utf-8') as f:
        text = f.read()
    if not json_ok:   # SQLite quá cũ, không có hàm JSON
        text = re.sub(r'/\*JSON_CHECK\*/.*?/\*END_JSON_CHECK\*/', '', text, flags=re.S)
    out, buf = [], ''
    for line in text.splitlines():
        if line.strip().startswith('--'):
            continue
        buf += line + '\n'
        if sqlite3.complete_statement(buf):
            out.append(buf.strip())
            buf = ''
    return out


def _rows(c, sql, args=()):
    cur = c.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _unique(name, seen, maxlen):
    """Đổi tên bị trùng (không phân biệt hoa thường) thành "Tên (2)", "Tên (3)"…"""
    base = (name or '').strip() or 'Không tên'
    cand, n = base[:maxlen], 2
    while cand.casefold() in seen:
        suffix = ' (%d)' % n
        cand = base[:maxlen - len(suffix)] + suffix
        n += 1
    seen.add(cand.casefold())
    return cand


def _v1_to_v2(c, json_ok, log):
    c.execute('DROP INDEX IF EXISTS idx_history_at')
    for t in ('slaves', 'devices', 'commands', 'history'):
        c.execute('ALTER TABLE %s RENAME TO %s_v1' % (t, t))
    for s in schema_statements(json_ok):
        c.execute(s)

    c.execute('INSERT INTO slaves (id, name, room_id, online, ip, rssi, fw, last_seen) '
              'SELECT id, name, room_id, online, ip, rssi, fw, last_seen FROM slaves_v1')

    names = {}
    for d in _rows(c, 'SELECT * FROM devices_v1 ORDER BY id'):
        name = _unique(d['name'], names.setdefault(d['room_id'], set()), 30)
        if name != d['name']:
            log('  đổi tên thiết bị trùng: "%s" → "%s"' % (d['name'], name))
        c.execute('INSERT INTO devices (id, room_id, type, name, brand, slave_id, created_at) VALUES (?, ?, ?, ?, ?, NULL, ?)',
                  (d['id'], d['room_id'], d['type'], name, d['brand'] or '', d['created_at']))

    labels = {}
    for m in _rows(c, 'SELECT * FROM commands_v1 ORDER BY id'):
        if m['kind'] == 'raw':
            try:
                if not isinstance(json.loads(m['raw']), list):
                    raise ValueError
            except (TypeError, ValueError):
                log('  bỏ nút hỏng (mã RAW không hợp lệ): id=%s' % m['id'])
                continue
        label = _unique(m['label'], labels.setdefault(m['device_id'], set()), 20)
        if label != m['label']:
            log('  đổi tên nút trùng: "%s" → "%s"' % (m['label'], label))
        c.execute('INSERT INTO commands (id, device_id, key, label, kind, protocol, value, address, command, bits, carrier_khz, raw, match_pct, created_at, updated_at) '
                  'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                  (m['id'], m['device_id'], m['key'], label, m['kind'], m['protocol'], m['value'], m['address'], m['command'],
                   m['bits'], m['carrier_khz'] or 38, m['raw'], m['match_pct'], m['created_at'], m['updated_at']))

    c.execute('INSERT INTO history (id, at, device_id, room_name, device_name, key, label, source, text, slave_id, status, latency_ms) '
              'SELECT id, at, device_id, room_name, device_name, key, label, source, text, slave_id, status, latency_ms FROM history_v1')

    for t in ('history', 'commands', 'devices', 'slaves'):
        c.execute('DROP TABLE %s_v1' % t)


def _v2_to_v3(c, json_ok, log):
    # Bảng mới được tạo bởi schema.sql (CREATE IF NOT EXISTS). Riêng history phải dựng lại để đổi CHECK của source.
    c.execute('DROP INDEX IF EXISTS idx_history_at')
    c.execute('DROP INDEX IF EXISTS idx_history_device')
    c.execute('ALTER TABLE history RENAME TO history_v2')
    for s in schema_statements(json_ok):
        c.execute(s)
    c.execute('INSERT INTO history (id, at, device_id, room_name, device_name, key, label, source, text, slave_id, status, latency_ms) '
              'SELECT id, at, device_id, room_name, device_name, key, label, source, text, slave_id, status, latency_ms FROM history_v2')
    c.execute('DROP TABLE history_v2')


def _rooms_sql(json_ok):
    return next(s for s in schema_statements(json_ok) if s.startswith('CREATE TABLE IF NOT EXISTS rooms '))


def _v3_to_v4(c, json_ok, log):
    # Quy trình SQLite khuyên dùng khi đổi định nghĩa bảng có khóa ngoại trỏ tới (foreign_keys đang OFF):
    # tạo bảng mới → chép → xóa bảng cũ → đổi tên bảng mới. KHÔNG đổi tên bảng cũ trước, vì SQLite sẽ sửa
    # theo tham chiếu REFERENCES rooms trong devices/slaves sang tên mới.
    seq = c.execute("SELECT seq FROM sqlite_sequence WHERE name = 'rooms'").fetchone()
    c.execute(_rooms_sql(json_ok).replace('CREATE TABLE IF NOT EXISTS rooms ', 'CREATE TABLE rooms_new ', 1))
    seen = set()
    for r in _rows(c, 'SELECT id, name, created_at FROM rooms ORDER BY id'):
        name = _unique(r['name'], seen, 24)
        if name != r['name']:
            log('  đổi tên phòng không hợp lệ/trùng: "%s" → "%s"' % (r['name'], name))
        c.execute('INSERT INTO rooms_new (id, name, created_at) VALUES (?, ?, ?)', (r['id'], name, r['created_at']))
    c.execute('DROP TABLE rooms')
    c.execute('ALTER TABLE rooms_new RENAME TO rooms')
    if seq:   # giữ bộ đếm AUTOINCREMENT: id phòng đã xóa không được dùng lại
        c.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'rooms'", (seq[0],))


def _v4_to_v5(c, json_ok, log):
    for s in schema_statements(json_ok):     # chỉ thêm bảng mới (CREATE ... IF NOT EXISTS)
        c.execute(s)


STEPS = {1: _v1_to_v2, 2: _v2_to_v3, 3: _v3_to_v4, 4: _v4_to_v5}


def migrate(path, log=print):
    """Gọi khi khởi động. Trả về phiên bản cấu trúc hiện tại."""
    c = sqlite3.connect(path, isolation_level=None)   # tự quản lý BEGIN/COMMIT
    try:
        c.execute('PRAGMA journal_mode=WAL')
        json_ok = json_supported(c)
        ver = c.execute('PRAGMA user_version').fetchone()[0]
        has_tables = c.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rooms'").fetchone()

        if not has_tables:                               # CSDL mới
            c.execute('BEGIN')
            for s in schema_statements(json_ok):
                c.execute(s)
            c.execute('PRAGMA user_version = %d' % LATEST)
            c.execute('COMMIT')
            return LATEST

        ver = ver or 1                                   # bản đầu tiên chưa đánh số
        if ver > LATEST:
            raise RuntimeError('CSDL ở phiên bản %d, mới hơn phần mềm (%d). Hãy cập nhật phần mềm.' % (ver, LATEST))
        if ver == LATEST:
            return ver

        backup = '%s.bak-v%d-%s' % (path, ver, time.strftime('%Y%m%d-%H%M%S'))
        dst = sqlite3.connect(backup)
        c.backup(dst)
        dst.close()
        log('[CSDL] Nâng cấp cấu trúc v%d → v%d. Bản sao lưu: %s' % (ver, LATEST, os.path.basename(backup)))

        c.execute('PRAGMA foreign_keys = OFF')           # bắt buộc khi dựng lại bảng
        try:
            c.execute('BEGIN')
            while ver < LATEST:
                STEPS[ver](c, json_ok, log)
                ver += 1
                c.execute('PRAGMA user_version = %d' % ver)
            bad = c.execute('PRAGMA foreign_key_check').fetchall()
            if bad:
                raise RuntimeError('Dữ liệu vi phạm khóa ngoại sau nâng cấp: %r' % bad[:5])
            c.execute('COMMIT')
        except Exception:
            c.execute('ROLLBACK')
            log('[CSDL] Nâng cấp thất bại, dữ liệu giữ nguyên như trước.')
            raise
        finally:
            c.execute('PRAGMA foreign_keys = ON')
        log('[CSDL] Nâng cấp xong.')
        return ver
    finally:
        c.close()
