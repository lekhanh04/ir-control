"""REST API cho giao diện Web. Danh sách đầy đủ: docs/api.md."""
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time

from flask import Blueprint, Response, after_this_request, current_app, jsonify, request, send_file

from . import backup as backups
from .db import now_ms
from .learn import ReceiverBusy

bp = Blueprint('api', __name__, url_prefix='/api')
KEY_RE = re.compile(r'^[a-z0-9_]{1,20}$')
TIME_RE = re.compile(r'^([01][0-9]|2[0-3]):[0-5][0-9]$')
MAX_SCENE_STEPS = 30


def hub():
    return current_app.extensions['irhub']


def auth():
    return current_app.extensions['irhub_auth']


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def err(status, code, message):
    return jsonify(error=code, message=message), status


def body():
    return request.get_json(silent=True) or {}


def ci_taken(rows, field, value, skip_id=None):
    """So trùng không phân biệt hoa thường, đúng cả chữ có dấu (NOCASE của SQLite chỉ xử lý A–Z)."""
    v = value.casefold()
    return any(r[field].casefold() == v and r['id'] != skip_id for r in rows)


def text(v, lo, hi):
    v = (v or '').strip() if isinstance(v, str) else ''
    return v if lo <= len(v) <= hi else None


@bp.errorhandler(sqlite3.IntegrityError)
def _integrity(e):
    return err(409, 'conflict', 'Dữ liệu bị trùng hoặc đang được dùng')


# ---------- Đăng nhập (PIN) ----------
@bp.get('/auth')
def auth_status():
    return jsonify(auth().status())


@bp.post('/login')
def login():
    ok, e = auth().login(body().get('pin'))
    return jsonify(auth().status()) if ok else err(*e)


@bp.post('/logout')
def logout():
    auth().logout()
    return jsonify(auth().status())


# ---------- Hệ thống ----------
@bp.get('/system')
def system():
    h = hub()
    try:
        with open('/proc/uptime') as f:
            uptime = int(float(f.read().split()[0]))
    except OSError:
        uptime = int(time.time() - h.started_at)
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            cpu = round(int(f.read()) / 1000.0, 1)
    except (OSError, ValueError):
        cpu = None
    du = shutil.disk_usage(os.path.dirname(os.path.abspath(h.cfg.DB_PATH)))
    return jsonify(uptime_s=uptime, cpu_temp_c=cpu, disk_used_mb=du.used // 2**20, disk_total_mb=du.total // 2**20,
                   db_size_kb=h.db.size_bytes() // 1024, db_schema=h.db.version, mqtt='ok' if h.transport.healthy() else 'error',
                   ir_receiver='ok' if h.receiver and h.receiver.healthy() else 'error', version=h.cfg.VERSION, simulate=h.cfg.SIMULATE)


@bp.get('/backup')
def backup():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    hub().db.backup_to(path)

    @after_this_request
    def _cleanup(resp):
        try:
            os.remove(path)
        except OSError:
            pass
        return resp
    return send_file(path, as_attachment=True, download_name=time.strftime('irhub-backup-%Y%m%d-%H%M.db'))


@bp.get('/backups')
def backups_list():
    """Bản sao lưu tự động hằng ngày và bản sao an toàn tạo trước mỗi lần khôi phục."""
    return jsonify(keep=hub().cfg.BACKUP_KEEP, items=backups.list_backups(hub().cfg.DB_PATH))


@bp.get('/backups/<name>')
def backups_download(name):
    p = backups.backup_path(hub().cfg.DB_PATH, name)
    if not p:
        return err(404, 'not_found', 'Không có bản sao lưu này')
    return send_file(p, as_attachment=True, download_name=name)


@bp.post('/restore')
def restore():
    """Khôi phục từ file tải lên (multipart, trường "file") hoặc từ bản sao lưu trên Pi ({"name": "..."})."""
    h = hub()
    up = request.files.get('file')
    tmp = None
    try:
        if up:
            fd, tmp = tempfile.mkstemp(suffix='.db', dir=os.path.dirname(os.path.abspath(h.cfg.DB_PATH)))
            os.close(fd)
            up.save(tmp)
            src = tmp
        else:
            src = backups.backup_path(h.cfg.DB_PATH, body().get('name'))
            if not src:
                return err(404, 'not_found', 'Không có bản sao lưu này')
        safety = h.restore(src)
    except backups.BadBackup as e:
        return err(400, 'bad_backup', str(e))
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    return jsonify(ok=True, safety_backup=safety)


@bp.get('/events')
def events():
    return Response(hub().events.stream(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# ---------- Cài đặt chung ----------
@bp.get('/settings')
def settings_get():
    return jsonify(history_retention_days=hub().retention_days())


@bp.patch('/settings')
def settings_set():
    b = body()
    if 'history_retention_days' in b:
        v = b['history_retention_days']
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 3650:
            return err(400, 'retention', 'Số ngày lưu lịch sử từ 0 (giữ mãi) đến 3650')
        hub().db.set_setting('history.retention_days', str(v))
        hub().cleanup_history()
    return settings_get()


# ---------- Loại thiết bị ----------
@bp.get('/device-types')
def device_types():
    return jsonify(hub().db.all('SELECT code, label FROM device_types ORDER BY sort_order, label'))


# ---------- Phòng ----------
@bp.get('/rooms')
def rooms_list():
    return jsonify(hub().db.all('SELECT id, name FROM rooms ORDER BY id'))


@bp.post('/rooms')
def rooms_create():
    name = text(body().get('name'), 1, 24)
    if not name:
        return err(400, 'name', 'Tên phòng từ 1 đến 24 ký tự')
    db = hub().db
    if ci_taken(db.all('SELECT id, name FROM rooms'), 'name', name):
        return err(409, 'exists', 'Đã có phòng tên này')
    rid, _ = db.run('INSERT INTO rooms (name, created_at) VALUES (?, ?)', (name, now_ms()))
    return jsonify(id=rid, name=name), 201


@bp.patch('/rooms/<int:rid>')
def rooms_update(rid):
    name = text(body().get('name'), 1, 24)
    if not name:
        return err(400, 'name', 'Tên phòng từ 1 đến 24 ký tự')
    db = hub().db
    if ci_taken(db.all('SELECT id, name FROM rooms'), 'name', name, rid):
        return err(409, 'exists', 'Đã có phòng tên này')
    _, n = db.run('UPDATE rooms SET name = ? WHERE id = ?', (name, rid))
    return jsonify(id=rid, name=name) if n else err(404, 'not_found', 'Không tìm thấy phòng')


@bp.delete('/rooms/<int:rid>')
def rooms_delete(rid):
    db = hub().db
    if db.one('SELECT id FROM devices WHERE room_id = ? LIMIT 1', (rid,)):
        return err(409, 'not_empty', 'Phòng còn thiết bị')
    _, n = db.run('DELETE FROM rooms WHERE id = ?', (rid,))
    if n and db.get_setting('voice.default_room_id') == str(rid):
        db.set_setting('voice.default_room_id', '')    # phòng mặc định của giọng nói không còn
    return jsonify(ok=True) if n else err(404, 'not_found', 'Không tìm thấy phòng')


# ---------- Thiết bị ----------
@bp.get('/devices')
def devices_list():
    return jsonify(hub().db.all('SELECT d.id, d.room_id, d.type, d.name, d.brand, d.slave_id, '
                                '(SELECT COUNT(*) FROM commands c WHERE c.device_id = d.id) AS command_count '
                                'FROM devices d ORDER BY d.room_id, d.id'))


def _device_body(b, partial=False, current=None):
    """Kiểm tra dữ liệu thiết bị. current = dòng hiện tại khi sửa."""
    db, out = hub().db, {}
    if not partial or 'name' in b:
        out['name'] = text(b.get('name'), 1, 30)
        if not out['name']:
            return None, 'Tên thiết bị từ 1 đến 30 ký tự'
    if not partial or 'type' in b:
        if not isinstance(b.get('type'), str) or not db.one('SELECT code FROM device_types WHERE code = ?', (b['type'],)):
            return None, 'Loại thiết bị không hợp lệ'
        out['type'] = b['type']
    if not partial or 'room_id' in b:
        if not is_int(b.get('room_id')) or not db.one('SELECT id FROM rooms WHERE id = ?', (b['room_id'],)):
            return None, 'Phòng không tồn tại'
        out['room_id'] = b['room_id']
    if 'brand' in b:
        out['brand'] = (b.get('brand') or '').strip()[:24]
    room_id = out.get('room_id', current['room_id'] if current else None)
    if 'slave_id' in b:
        sid = b.get('slave_id') or None
        if sid is not None and not isinstance(sid, str):
            return None, 'Bộ phát không hợp lệ'
        if sid and not db.one('SELECT id FROM slaves WHERE id = ? AND room_id = ?', (sid, room_id)):
            return None, 'Bộ phát phải thuộc cùng phòng với thiết bị'
        out['slave_id'] = sid
    elif current and room_id != current['room_id']:
        out['slave_id'] = None   # đổi phòng → bộ phát gán riêng không còn hợp lệ
    return out, None


def _name_taken(room_id, name, did=None):
    return ci_taken(hub().db.all('SELECT id, name FROM devices WHERE room_id = ?', (room_id,)), 'name', name, did)


@bp.post('/devices')
def devices_create():
    d, e = _device_body(body())
    if e:
        return err(400, 'invalid', e)
    if _name_taken(d['room_id'], d['name']):
        return err(409, 'name_exists', 'Phòng này đã có thiết bị cùng tên')
    did, _ = hub().db.run('INSERT INTO devices (room_id, type, name, brand, slave_id, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                          (d['room_id'], d['type'], d['name'], d.get('brand', ''), d.get('slave_id'), now_ms()))
    return jsonify(dict(d, id=did, slave_id=d.get('slave_id'), command_count=0)), 201


@bp.patch('/devices/<int:did>')
def devices_update(did):
    cur = hub().db.one('SELECT * FROM devices WHERE id = ?', (did,))
    if not cur:
        return err(404, 'not_found', 'Không tìm thấy thiết bị')
    d, e = _device_body(body(), partial=True, current=cur)
    if e:
        return err(400, 'invalid', e)
    if ('name' in d or 'room_id' in d) and _name_taken(d.get('room_id', cur['room_id']), d.get('name', cur['name']), did):
        return err(409, 'name_exists', 'Phòng này đã có thiết bị cùng tên')
    if d:
        sets = ', '.join('%s = ?' % k for k in d)
        _, n = hub().db.run('UPDATE devices SET %s WHERE id = ?' % sets, tuple(d.values()) + (did,))
        if not n:
            return err(404, 'not_found', 'Không tìm thấy thiết bị')
    return jsonify(hub().db.one('SELECT * FROM devices WHERE id = ?', (did,)))


@bp.delete('/devices/<int:did>')
def devices_delete(did):
    _, n = hub().db.run('DELETE FROM devices WHERE id = ?', (did,))
    return jsonify(ok=True) if n else err(404, 'not_found', 'Không tìm thấy thiết bị')


# ---------- Lệnh (nút) ----------
@bp.get('/devices/<int:did>/commands')
def commands_list(did):
    rows = hub().db.all('SELECT id, device_id, key, label, kind, protocol, value, address, command, bits, carrier_khz, raw, match_pct '
                        'FROM commands WHERE device_id = ? ORDER BY id', (did,))
    for r in rows:
        r['raw_len'] = len(json.loads(r.pop('raw'))) if r.get('raw') else None
    return jsonify(rows)


@bp.patch('/commands/<int:cid>')
def commands_update(cid):
    label = text(body().get('label'), 1, 20)
    if not label:
        return err(400, 'label', 'Tên nút từ 1 đến 20 ký tự')
    db = hub().db
    c = db.one('SELECT device_id FROM commands WHERE id = ?', (cid,))
    if not c:
        return err(404, 'not_found', 'Không tìm thấy nút')
    if ci_taken(db.all('SELECT id, label FROM commands WHERE device_id = ?', (c['device_id'],)), 'label', label, cid):
        return err(409, 'label_exists', 'Thiết bị đã có nút cùng tên')
    db.run('UPDATE commands SET label = ?, updated_at = ? WHERE id = ?', (label, now_ms(), cid))
    return jsonify(id=cid, label=label)


@bp.delete('/commands/<int:cid>')
def commands_delete(cid):
    _, n = hub().db.run('DELETE FROM commands WHERE id = ?', (cid,))
    return jsonify(ok=True) if n else err(404, 'not_found', 'Không tìm thấy nút')


SEND_ERRORS = {
    'offline': (503, 'slave_offline', 'Bộ phát của thiết bị đang mất kết nối'),
    'timeout': (504, 'no_ack', 'Bộ phát không xác nhận'),
    'error': (502, 'slave_error', 'Bộ phát báo lỗi khi phát'),
    'busy': (429, 'busy', 'Bộ phát đang bận'),
}


@bp.post('/send')
def send():
    res = hub().send_command(body().get('command_id'), source='web')
    if not res:
        return err(404, 'not_found', 'Không tìm thấy lệnh')
    status, ms, entry = res
    if status != 'ok':
        return err(*SEND_ERRORS[status])
    return jsonify(status='ok', latency_ms=ms, history_id=entry['id'])


# ---------- Học mã ----------
@bp.post('/learn')
def learn_start():
    b = body()
    dev = hub().db.one('SELECT * FROM devices WHERE id = ?', (b.get('device_id'),))
    if not dev:
        return err(404, 'not_found', 'Không tìm thấy thiết bị')
    if not KEY_RE.match(b.get('key') or ''):
        return err(400, 'key', 'Mã nút không hợp lệ')
    try:
        s = hub().learn.start(dev, b['key'], force=bool(b.get('force')))
    except ReceiverBusy:
        return err(409, 'receiver_busy', 'Mắt thu đang được dùng để học một nút khác')
    except RuntimeError:
        return err(503, 'ir_receiver', 'Mắt thu IR không hoạt động')
    return jsonify(session=s.id, captures=s.captures, timeout_s=s.timeout_s)


def _session(sid):
    return hub().learn.get(sid)


@bp.get('/learn/<sid>')
def learn_status(sid):
    s = _session(sid)
    return jsonify(s.public()) if s else err(404, 'not_found', 'Phiên học đã kết thúc')


@bp.post('/learn/<sid>/test')
def learn_test(sid):
    s = _session(sid)
    if not s or s.state != 'done':
        return err(409, 'not_ready', 'Chưa có mã để phát thử')
    status, ms = hub().learn.test(s)
    return jsonify(status='ok', latency_ms=ms) if status == 'ok' else err(*SEND_ERRORS[status])


@bp.post('/learn/<sid>/save')
def learn_save(sid):
    s, b = _session(sid), body()
    if not s or s.state != 'done':
        return err(409, 'not_ready', 'Chưa có mã để lưu')
    label = text(b.get('label'), 1, 20)
    if not label:
        return err(400, 'label', 'Tên nút từ 1 đến 20 ký tự')
    cid, why = hub().learn.save(s, label, replace=bool(b.get('replace')))
    if why == 'exists':
        return err(409, 'exists', 'Nút đã có mã')
    if why == 'label_exists':
        return err(409, 'label_exists', 'Thiết bị đã có nút cùng tên')
    return jsonify(id=cid, key=s.key, label=label)


@bp.delete('/learn/<sid>')
def learn_cancel(sid):
    hub().learn.cancel(sid)
    return jsonify(ok=True)


# ---------- Ngữ cảnh (macro) ----------
def _scenes(scene_id=None):
    db = hub().db
    where, args = ('WHERE id = ?', (scene_id,)) if scene_id else ('', ())
    scenes = db.all('SELECT id, name FROM scenes %s ORDER BY id' % where, args)
    steps = db.all('SELECT s.scene_id, s.command_id, s.delay_ms, c.key, c.label, c.device_id, d.name AS device_name, r.name AS room_name '
                   'FROM scene_steps s JOIN commands c ON c.id = s.command_id JOIN devices d ON d.id = c.device_id '
                   'JOIN rooms r ON r.id = d.room_id ORDER BY s.scene_id, s.position, s.id')
    for sc in scenes:
        sc['steps'] = [{k: v for k, v in st.items() if k != 'scene_id'} for st in steps if st['scene_id'] == sc['id']]
    return scenes


def _scene_body(b, sid=None):
    """Trả (name, [(command_id, delay_ms)], None) hoặc (None, None, (status, code, message))."""
    db = hub().db
    name = text(b.get('name'), 1, 30)
    if not name:
        return None, None, (400, 'name', 'Tên ngữ cảnh từ 1 đến 30 ký tự')
    if ci_taken(db.all('SELECT id, name FROM scenes'), 'name', name, sid):
        return None, None, (409, 'exists', 'Đã có ngữ cảnh tên này')
    steps = b.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_SCENE_STEPS:
        return None, None, (400, 'steps', 'Ngữ cảnh cần từ 1 đến %d bước' % MAX_SCENE_STEPS)
    out = []
    for st in steps:
        st = st if isinstance(st, dict) else {}
        cid, delay = st.get('command_id'), st.get('delay_ms', 500)
        if not is_int(cid) or not db.one('SELECT id FROM commands WHERE id = ?', (cid,)):
            return None, None, (400, 'steps', 'Có bước dùng nút không tồn tại')
        if not is_int(delay) or not 0 <= delay <= 60000:
            return None, None, (400, 'steps', 'Thời gian chờ từ 0 đến 60000 ms')
        out.append((cid, delay))
    return name, out, None


def _save_scene(name, steps, sid=None):
    c = hub().db.connect()
    try:
        with c:   # một giao dịch: lỗi giữa chừng thì không đổi gì
            if sid:
                c.execute('UPDATE scenes SET name = ? WHERE id = ?', (name, sid))
                c.execute('DELETE FROM scene_steps WHERE scene_id = ?', (sid,))
            else:
                sid = c.execute('INSERT INTO scenes (name, created_at) VALUES (?, ?)', (name, now_ms())).lastrowid
            c.executemany('INSERT INTO scene_steps (scene_id, position, command_id, delay_ms) VALUES (?, ?, ?, ?)',
                          [(sid, i, cid, delay) for i, (cid, delay) in enumerate(steps)])
    finally:
        c.close()
    return sid


@bp.get('/scenes')
def scenes_list():
    return jsonify(_scenes())


@bp.post('/scenes')
def scenes_create():
    name, steps, e = _scene_body(body())
    if e:
        return err(*e)
    return jsonify(_scenes(_save_scene(name, steps))[0]), 201


@bp.put('/scenes/<int:sid>')
def scenes_update(sid):
    if not hub().db.one('SELECT id FROM scenes WHERE id = ?', (sid,)):
        return err(404, 'not_found', 'Không tìm thấy ngữ cảnh')
    name, steps, e = _scene_body(body(), sid)
    if e:
        return err(*e)
    _save_scene(name, steps, sid)
    return jsonify(_scenes(sid)[0])


@bp.delete('/scenes/<int:sid>')
def scenes_delete(sid):
    _, n = hub().db.run('DELETE FROM scenes WHERE id = ?', (sid,))
    return jsonify(ok=True) if n else err(404, 'not_found', 'Không tìm thấy ngữ cảnh')


@bp.post('/scenes/<int:sid>/run')
def scenes_run(sid):
    res = hub().run_scene(sid, source='scene')
    return jsonify(res) if res else err(404, 'not_found', 'Không tìm thấy ngữ cảnh')


# ---------- Hẹn giờ ----------
def _schedules(sched_id=None):
    where, args = ('WHERE s.id = ?', (sched_id,)) if sched_id else ('', ())
    rows = hub().db.all('SELECT s.id, s.scene_id, s.command_id, s.at_time, s.days, s.enabled, s.last_run, '
                        '(SELECT COUNT(*) FROM scene_steps st WHERE st.scene_id = s.scene_id) AS scene_steps, '
                        'sc.name AS scene_name, c.label AS command_label, c.device_id, d.name AS device_name, r.name AS room_name '
                        'FROM schedules s LEFT JOIN scenes sc ON sc.id = s.scene_id LEFT JOIN commands c ON c.id = s.command_id '
                        'LEFT JOIN devices d ON d.id = c.device_id LEFT JOIN rooms r ON r.id = d.room_id '
                        '%s ORDER BY s.at_time, s.id' % where, args)
    for r in rows:
        r['enabled'] = bool(r['enabled'])
    return rows


def _schedule_body(b, cur=None):
    """Trả (các cột cần ghi, None) hoặc (None, thông báo lỗi)."""
    db, out = hub().db, {}
    if not cur or 'scene_id' in b or 'command_id' in b:
        scene_id, command_id = b.get('scene_id') or None, b.get('command_id') or None
        if (scene_id is None) == (command_id is None):
            return None, 'Chọn một ngữ cảnh hoặc một nút'
        if scene_id is not None and not (is_int(scene_id) and db.one('SELECT id FROM scenes WHERE id = ?', (scene_id,))):
            return None, 'Ngữ cảnh không tồn tại'
        if command_id is not None and not (is_int(command_id) and db.one('SELECT id FROM commands WHERE id = ?', (command_id,))):
            return None, 'Nút không tồn tại'
        out.update(scene_id=scene_id, command_id=command_id)
    if not cur or 'at_time' in b:
        if not isinstance(b.get('at_time'), str) or not TIME_RE.match(b['at_time']):
            return None, 'Giờ phải có dạng HH:MM (00:00 đến 23:59)'
        out['at_time'] = b['at_time']
        out['last_run'] = None     # đổi giờ → được chạy ngay trong phút mới
    if not cur or 'days' in b:
        days = b.get('days', 127)
        if not is_int(days) or not 1 <= days <= 127:
            return None, 'Chọn ít nhất một ngày trong tuần'
        out['days'] = days
    if 'enabled' in b:
        out['enabled'] = 1 if b['enabled'] else 0
    return out, None


@bp.get('/schedules')
def schedules_list():
    return jsonify(_schedules())


@bp.post('/schedules')
def schedules_create():
    d, e = _schedule_body(body())
    if e:
        return err(400, 'invalid', e)
    d.setdefault('enabled', 1)
    d['created_at'] = now_ms()
    sql = 'INSERT INTO schedules (%s) VALUES (%s)' % (', '.join(d), ', '.join(['?'] * len(d)))
    sid, _ = hub().db.run(sql, tuple(d.values()))
    return jsonify(_schedules(sid)[0]), 201


@bp.patch('/schedules/<int:sid>')
def schedules_update(sid):
    cur = hub().db.one('SELECT * FROM schedules WHERE id = ?', (sid,))
    if not cur:
        return err(404, 'not_found', 'Không tìm thấy hẹn giờ')
    d, e = _schedule_body(body(), cur)
    if e:
        return err(400, 'invalid', e)
    if d:
        hub().db.run('UPDATE schedules SET %s WHERE id = ?' % ', '.join('%s = ?' % k for k in d), tuple(d.values()) + (sid,))
    return jsonify(_schedules(sid)[0])


@bp.delete('/schedules/<int:sid>')
def schedules_delete(sid):
    _, n = hub().db.run('DELETE FROM schedules WHERE id = ?', (sid,))
    return jsonify(ok=True) if n else err(404, 'not_found', 'Không tìm thấy hẹn giờ')


# ---------- Bộ phát ESP8266 ----------
@bp.get('/slaves')
def slaves_list():
    return jsonify([hub().slave_view(r) for r in hub().db.all('SELECT * FROM slaves ORDER BY room_id IS NULL DESC, id')])


@bp.patch('/slaves/<sid>')
def slaves_update(sid):
    b, db = body(), hub().db
    if not db.one('SELECT id FROM slaves WHERE id = ?', (sid,)):
        return err(404, 'not_found', 'Không tìm thấy bộ phát')
    if 'name' in b:
        name = text(b.get('name'), 1, 30)
        if not name:
            return err(400, 'name', 'Tên từ 1 đến 30 ký tự')
        db.run('UPDATE slaves SET name = ? WHERE id = ?', (name, sid))
    if 'room_id' in b:
        rid = b['room_id']
        if rid is not None and not (is_int(rid) and db.one('SELECT id FROM rooms WHERE id = ?', (rid,))):
            return err(400, 'room', 'Phòng không tồn tại')
        # Một phòng có thể có nhiều bộ phát. Thiết bị phòng khác đang gán riêng bộ này → về "Tự động"
        db.run('UPDATE devices SET slave_id = NULL WHERE slave_id = ? AND room_id IS NOT ?', (sid, rid))
        db.run('UPDATE slaves SET room_id = ? WHERE id = ?', (rid, sid))
    return jsonify(hub().slave_view(db.one('SELECT * FROM slaves WHERE id = ?', (sid,))))


@bp.delete('/slaves/<sid>')
def slaves_delete(sid):
    db = hub().db
    s = db.one('SELECT * FROM slaves WHERE id = ?', (sid,))
    if not s:
        return err(404, 'not_found', 'Không tìm thấy bộ phát')
    if s['online']:
        return err(409, 'online', 'Chỉ xoá được bộ phát đang mất kết nối')
    db.run('DELETE FROM slaves WHERE id = ?', (sid,))   # devices.slave_id tự về NULL
    return jsonify(ok=True)


@bp.post('/slaves/<sid>/identify')
def slaves_identify(sid):
    s = hub().db.one('SELECT * FROM slaves WHERE id = ?', (sid,))
    if not s:
        return err(404, 'not_found', 'Không tìm thấy bộ phát')
    if not s['online']:
        return err(503, 'slave_offline', 'Bộ phát mất kết nối')
    hub().transport.identify(sid)
    return jsonify(ok=True)


# ---------- Lịch sử, giọng nói ----------
@bp.get('/history')
def history_list():
    limit = min(max(request.args.get('limit', 60, type=int), 1), 500)
    return jsonify(hub().db.all('SELECT * FROM history ORDER BY at DESC LIMIT ?', (limit,)))


@bp.get('/voice')
def voice_get():
    return jsonify(hub().voice.public())


@bp.post('/voice')
def voice_set():
    b = body()
    if 'sensitivity' in b and b['sensitivity'] not in ('low', 'mid', 'high'):
        return err(400, 'sensitivity', 'Độ nhạy không hợp lệ')
    rid = b.get('default_room_id')
    if rid is not None and not (is_int(rid) and hub().db.one('SELECT id FROM rooms WHERE id = ?', (rid,))):
        return err(400, 'default_room', 'Phòng không tồn tại')
    hub().voice.update(b)
    return jsonify(hub().voice.public())


# ---------- Chỉ có khi IRHUB_SIMULATE=1: điều khiển thiết bị giả để thử ----------
dev = Blueprint('dev', __name__, url_prefix='/api/dev')


@dev.post('/voice')
def dev_voice():
    h = hub()
    h.events.publish('voice', {'state': 'listening'})
    h.voice.handle_text(body().get('text', ''))
    return jsonify(ok=True)


@dev.post('/slaves/<sid>')
def dev_slave(sid):
    hub().transport.set_online(sid, bool(body().get('online')))
    return jsonify(ok=True)


@dev.post('/sim')
def dev_sim():
    """{"ir": "ok|mismatch|timeout", "ack": "ok|fail", "voice_module": true|false}"""
    h, b = hub(), body()
    if b.get('ir') in ('ok', 'mismatch', 'timeout'):
        h.receiver.mode = b['ir']
    if b.get('ack') in ('ok', 'fail'):
        h.sim_fail_ack = b['ack'] == 'fail'
    if 'voice_module' in b:
        h.voice.module_online = bool(b['voice_module'])
    return jsonify(ir=h.receiver.mode, ack='fail' if h.sim_fail_ack else 'ok', voice_module=h.voice.module_online)
