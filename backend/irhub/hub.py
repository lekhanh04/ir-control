"""Bộ điều phối trung tâm: nối CSDL, kênh MQTT, mắt thu IR, học mã, giọng nói và sự kiện."""
import json
import re
import threading
import time

from . import backup
from .db import Database, now_ms
from .events import EventBus
from .learn import LearnManager
from .voice import VoiceService

SLAVE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,32}$')
TEMP_MIN, TEMP_MAX = 16, 30
TEMP_STEP = {'temp_up': 1, 'temp_down': -1}


def public_slave(row):
    if not row:
        return None
    return dict(row, online=bool(row['online']))


def _as_int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


class Hub:
    def __init__(self, cfg):
        self.cfg = cfg
        self.started_at = time.time()
        self.db = Database(cfg.DB_PATH)
        self.events = EventBus()
        self.sim_fail_ack = False          # chỉ dùng ở chế độ giả lập
        self._slave_locks = {}
        self._locks_guard = threading.Lock()
        # Trạng thái bộ phát mới nhất trong bộ nhớ: sid → {last_seen, rssi, db_at}. Giảm ghi thẻ nhớ (xem on_slave_status).
        self._live = {}
        self._live_lock = threading.Lock()

        if cfg.SIMULATE:
            from .transport import SimTransport
            from .ir_receiver import SimReceiver
            self.transport = SimTransport(self)
            self.receiver = SimReceiver()
        else:
            from .transport import MqttTransport
            from .ir_receiver import PigpioReceiver
            self.transport = MqttTransport(self)
            try:
                self.receiver = PigpioReceiver(cfg.IR_GPIO)
            except Exception as e:  # vẫn cho điều khiển được dù mắt thu lỗi
                print('[IR] Mắt thu không hoạt động:', e)
                self.receiver = None

        self.learn = LearnManager(self)
        self.voice = VoiceService(self)

    def start(self):
        if self.cfg.SEED_DEMO:
            from .seed import seed_demo
            seed_demo(self.db)
        # Sau khi khởi động lại, chưa biết bộ phát nào còn sống: chờ status mới
        self.db.run('UPDATE slaves SET online = 0')
        self.cleanup_history()
        self.auto_backup()
        self.transport.start()
        threading.Thread(target=self._stale_watch, daemon=True).start()
        threading.Thread(target=self._schedule_loop, daemon=True).start()

    # ---------- Bộ phát ESP8266 ----------
    def on_slave_status(self, sid, data):
        """Gọi khi nhận irhub/slave/<id>/status (định kỳ 30 s, retained; LWT = online:false).

        Mỗi lần nhận chỉ cập nhật bộ nhớ (last_seen, rssi). Chỉ ghi CSDL khi bộ phát mới xuất hiện, đổi trạng thái
        hoạt động / IP / firmware, hoặc đã quá SLAVE_DB_REFRESH_S giây kể từ lần ghi trước — đỡ hao thẻ nhớ."""
        if not SLAVE_ID_RE.match(sid or '') or not isinstance(data, dict):
            return
        online = 1 if data.get('online') else 0
        ip = data.get('ip') if isinstance(data.get('ip'), str) else None
        fw = data.get('fw') if isinstance(data.get('fw'), str) else None
        rssi = _as_int(data.get('rssi'))
        now = now_ms()
        row = self.db.one('SELECT * FROM slaves WHERE id = ?', (sid,))
        live = self._live.get(sid) or {}
        if rssi is None:
            rssi = live.get('rssi')
        changed = not row or bool(row['online']) != bool(online) or bool(ip and ip != row['ip']) or bool(fw and fw != row['fw'])
        due = online and now - live.get('db_at', 0) >= self.cfg.SLAVE_DB_REFRESH_S * 1000
        wrote = False
        if not row:
            self.db.run('INSERT INTO slaves (id, name, online, ip, rssi, fw, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (sid, 'ESP8266 %s' % sid[-4:], online, ip, rssi, fw, now))
            wrote = True
        elif changed or due:
            last_seen = now if online else (live.get('last_seen') or row['last_seen'] or now)
            self.db.run('UPDATE slaves SET online = ?, ip = COALESCE(?, ip), rssi = COALESCE(?, rssi), fw = COALESCE(?, fw), '
                        'last_seen = ? WHERE id = ?', (online, ip, rssi, fw, last_seen, sid))
            wrote = True
        with self._live_lock:
            if online:
                self._live[sid] = {'last_seen': now, 'rssi': rssi, 'db_at': now if wrote else live.get('db_at', 0)}
            else:
                self._live.pop(sid, None)
        if changed or online:
            self.events.publish('slave', self.slave_view(self.db.one('SELECT * FROM slaves WHERE id = ?', (sid,))))

    def slave_view(self, row):
        """Dòng slaves gửi cho giao diện, ghép last_seen / rssi mới nhất trong bộ nhớ."""
        out = public_slave(row)
        if out and out['online']:
            live = self._live.get(out['id'])
            if live:
                out['last_seen'] = live['last_seen']
                if live.get('rssi') is not None:
                    out['rssi'] = live['rssi']
        return out

    def check_stale(self, now=None):
        """Bộ phát quá SLAVE_STALE_S giây không gửi status → mất kết nối (ghi CSDL kèm thời điểm thấy lần cuối)."""
        limit = (now or now_ms()) - self.cfg.SLAVE_STALE_S * 1000
        out = []
        for s in self.db.all('SELECT * FROM slaves WHERE online = 1'):
            seen = (self._live.get(s['id']) or {}).get('last_seen') or s['last_seen'] or 0
            if seen < limit:
                with self._live_lock:
                    live = self._live.pop(s['id'], None) or {}
                self.db.run('UPDATE slaves SET online = 0, last_seen = ?, rssi = COALESCE(?, rssi) WHERE id = ?',
                            (seen, live.get('rssi'), s['id']))
                self.events.publish('slave', public_slave(dict(s, online=0, last_seen=seen)))
                out.append(s['id'])
        return out

    def _stale_watch(self):
        """Mỗi 15 giây kiểm tra bộ phát mất kết nối. Mỗi giờ dọn lịch sử cũ và tạo bản sao lưu hằng ngày (nếu chưa có)."""
        last_hourly = time.time()
        while True:
            time.sleep(15)
            try:
                if time.time() - last_hourly > 3600:
                    last_hourly = time.time()
                    self.cleanup_history()
                    self.auto_backup()
                self.check_stale()
            except Exception as e:      # lỗi CSDL tạm thời không được làm dừng hẳn luồng theo dõi
                print('[Theo dõi] Lỗi:', e)

    # ---------- Sao lưu / khôi phục ----------
    def auto_backup(self):
        try:
            return backup.daily_backup(self.db, self.cfg.BACKUP_KEEP)
        except Exception as e:
            print('[Sao lưu] Không tạo được bản sao lưu:', e)
            return None

    def restore(self, src_path):
        """Khôi phục CSDL rồi làm mới trạng thái bộ phát. Ném backup.BadBackup nếu file không dùng được."""
        safety = backup.restore(self.db, src_path)
        with self._live_lock:
            self._live.clear()
        self.db.run('UPDATE slaves SET online = 0')
        self.transport.resync()      # nhận lại status (retained) của các bộ phát đang chạy
        return safety

    def slave_for_device(self, dev):
        """Bộ phát dùng cho thiết bị: bộ được gán riêng (devices.slave_id) nếu có,
        nếu không thì một bộ phát của phòng — ưu tiên bộ đang trực tuyến."""
        if dev.get('slave_id'):
            row = self.db.one('SELECT * FROM slaves WHERE id = ?', (dev['slave_id'],))
            if row:
                return row
        return self.db.one('SELECT * FROM slaves WHERE room_id = ? ORDER BY online DESC, last_seen DESC, id LIMIT 1',
                           (dev['room_id'],))

    # ---------- Lịch sử ----------
    def retention_days(self):
        try:
            return max(0, int(self.db.get_setting('history.retention_days', '90')))
        except (TypeError, ValueError):
            return 90

    def cleanup_history(self):
        """Xoá lịch sử cũ hơn N ngày (0 = giữ mãi)."""
        days = self.retention_days()
        if not days:
            return 0
        _, n = self.db.run('DELETE FROM history WHERE at < ?', (now_ms() - days * 86400000,))
        if n:
            print('[DB] Đã dọn %d dòng lịch sử cũ hơn %d ngày' % (n, days))
        return n

    def log_voice_miss(self, text):
        """Ghi lại câu nói không hiểu để xem lại và thêm từ khoá."""
        entry = {'at': now_ms(), 'device_id': None, 'room_name': None, 'device_name': None, 'key': None, 'label': None,
                 'source': 'voice', 'text': text, 'slave_id': None, 'status': 'not_understood', 'latency_ms': None}
        entry['id'], _ = self.db.run('INSERT INTO history (at, source, text, status) VALUES (?, ?, ?, ?)',
                                     (entry['at'], 'voice', text, 'not_understood'))
        self.events.publish('history', entry)
        return entry

    def _slave_lock(self, sid):
        with self._locks_guard:
            return self._slave_locks.setdefault(sid, threading.Lock())

    # ---------- Phát IR ----------
    @staticmethod
    def ir_payload(cmd):
        """Nội dung gửi tới ESP8266 cho một lệnh (dòng commands hoặc kết quả học mã)."""
        if cmd['kind'] == 'protocol':
            return {'type': 'protocol', 'protocol': cmd['protocol'], 'value': cmd['value'], 'bits': cmd['bits']}
        raw = cmd['raw'] if isinstance(cmd['raw'], list) else json.loads(cmd['raw'])
        return {'type': 'raw', 'freq': cmd.get('carrier_khz') or 38, 'data': raw}

    def deliver(self, slave, ir):
        """Gửi tới ESP8266 và chờ ACK. Trả (status, latency_ms): ok | timeout | offline | error | busy."""
        if not slave or not slave['online']:
            return 'offline', None
        lock = self._slave_lock(slave['id'])
        if not lock.acquire(timeout=1.0):   # mỗi bộ phát xử lý một lệnh một lúc
            return 'busy', None
        try:
            t0 = time.monotonic()
            ack = self.transport.send(slave['id'], ir, self.cfg.ACK_TIMEOUT_S)
            ms = int((time.monotonic() - t0) * 1000)
        finally:
            lock.release()
        if ack is None:
            return 'timeout', None
        return ('ok', ms) if ack.get('ok') else ('error', None)

    # ---------- Ngữ cảnh ----------
    def run_scene(self, scene_id, source='scene', text=None):
        """Phát lần lượt các nút của ngữ cảnh, chờ delay_ms sau mỗi bước.
        Trả {scene_id, name, status: ok|partial|error, results: [{command_id, label, device_name, status, latency_ms}]} hoặc None."""
        scene = self.db.one('SELECT * FROM scenes WHERE id = ?', (scene_id,))
        if not scene:
            return None
        steps = self.db.all('SELECT s.command_id, s.delay_ms, c.label, d.name AS device_name FROM scene_steps s '
                            'JOIN commands c ON c.id = s.command_id JOIN devices d ON d.id = c.device_id '
                            'WHERE s.scene_id = ? ORDER BY s.position, s.id', (scene_id,))
        results = []
        for i, st in enumerate(steps):
            res = self.send_command(st['command_id'], source=source, text=text or scene['name'])
            status, ms = (res[0], res[1]) if res else ('error', None)
            results.append({'command_id': st['command_id'], 'label': st['label'], 'device_name': st['device_name'],
                            'status': status, 'latency_ms': ms})
            if i < len(steps) - 1 and st['delay_ms']:
                time.sleep(st['delay_ms'] / 1000.0)
        ok = sum(1 for r in results if r['status'] == 'ok')
        status = 'ok' if results and ok == len(results) else 'partial' if ok else 'error'
        return {'scene_id': scene_id, 'name': scene['name'], 'status': status, 'results': results}

    # ---------- Hẹn giờ ----------
    def _schedule_loop(self):
        while True:
            try:
                self.run_due_schedules()
            except Exception as e:   # không để lỗi một lần làm dừng hẳn bộ hẹn giờ
                print('[Hẹn giờ] Lỗi:', e)
            time.sleep(15)

    def run_due_schedules(self, now=None):
        """Chạy các hẹn giờ đến hạn trong phút hiện tại (giờ địa phương của Pi). Trả danh sách id đã chạy."""
        now = now or time.time()
        lt = time.localtime(now)
        hhmm = '%02d:%02d' % (lt.tm_hour, lt.tm_min)
        minute_start = (int(now) - lt.tm_sec) * 1000
        due = self.db.all('SELECT * FROM schedules WHERE enabled = 1 AND at_time = ? AND (days & ?) <> 0 '
                          'AND (last_run IS NULL OR last_run < ?)', (hhmm, 1 << lt.tm_wday, minute_start))
        ran = []
        for sc in due:
            if sc['scene_id'] and not self.db.one('SELECT 1 FROM scene_steps WHERE scene_id = ? LIMIT 1', (sc['scene_id'],)):
                # Ngữ cảnh mất hết bước (thiết bị/nút đã bị xóa): tắt hẹn giờ thay vì mỗi ngày chạy mà không làm gì
                self.db.run('UPDATE schedules SET enabled = 0, last_run = ? WHERE id = ?', (int(now * 1000), sc['id']))
                self._record_run(sc['id'], 'skipped', 0, 0)
                print('[Hẹn giờ] Tắt hẹn giờ %s lúc %s: ngữ cảnh không còn bước nào' % (sc['id'], sc['at_time']))
                continue
            self.db.run('UPDATE schedules SET last_run = ? WHERE id = ?', (int(now * 1000), sc['id']))
            threading.Thread(target=self._run_schedule, args=(sc,), daemon=True).start()
            ran.append(sc['id'])
        return ran

    def _run_schedule(self, sc):
        text = 'Hẹn giờ %s' % sc['at_time']
        if sc['scene_id']:
            res = self.run_scene(sc['scene_id'], source='schedule', text=text)
            ok = sum(1 for r in res['results'] if r['status'] == 'ok') if res else 0
            self._record_run(sc['id'], res['status'] if res else 'error', ok, len(res['results']) if res else 0)
        else:
            res = self.send_command(sc['command_id'], source='schedule', text=text)
            good = bool(res) and res[0] == 'ok'
            self._record_run(sc['id'], 'ok' if good else 'error', 1 if good else 0, 1)

    def _record_run(self, schedule_id, status, ok, total):
        try:
            self.db.run('INSERT OR REPLACE INTO schedule_runs (schedule_id, at, status, ok, total) VALUES (?, ?, ?, ?, ?)',
                        (schedule_id, now_ms(), status, ok, total))
        except Exception as e:      # hẹn giờ có thể vừa bị xóa
            print('[Hẹn giờ] Không ghi được kết quả:', e)

    @staticmethod
    def next_run(at_time, days, enabled, now=None):
        """Thời điểm (ms) chạy kế tiếp theo giờ địa phương của Pi, hoặc None nếu đang tắt."""
        if not enabled:
            return None
        now = now or time.time()
        hh, mm = (int(x) for x in at_time.split(':'))
        lt = time.localtime(now)
        for d in range(8):
            t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + d, hh, mm, 0, 0, 0, -1))
            if t > now and days & (1 << time.localtime(t).tm_wday):
                return int(t * 1000)
        return None

    # ---------- Nhiệt độ ước tính ----------
    def set_temp(self, device_id, temp):
        if temp is None:
            self.db.run('DELETE FROM device_state WHERE device_id = ?', (device_id,))
        else:
            self.db.run('INSERT INTO device_state (device_id, temp, updated_at) VALUES (?, ?, ?) '
                        'ON CONFLICT(device_id) DO UPDATE SET temp = excluded.temp, updated_at = excluded.updated_at',
                        (device_id, temp, now_ms()))
        self.events.publish('device_state', {'device_id': device_id, 'temp': temp})

    def _bump_temp(self, device_id, key):
        st = self.db.one('SELECT temp FROM device_state WHERE device_id = ?', (device_id,))
        if st and st['temp'] is not None:
            self.set_temp(device_id, max(TEMP_MIN, min(TEMP_MAX, st['temp'] + TEMP_STEP[key])))

    def send_command(self, command_id, source='web', text=None):
        """Tra mã → gửi qua MQTT → chờ ACK → ghi lịch sử. Trả (status, latency_ms, entry) hoặc None."""
        cmd = self.db.one('SELECT c.*, d.name AS device_name, d.room_id, d.slave_id, r.name AS room_name FROM commands c '
                          'JOIN devices d ON d.id = c.device_id JOIN rooms r ON r.id = d.room_id WHERE c.id = ?', (command_id,))
        if not cmd:
            return None
        slave = self.slave_for_device(cmd)
        status, ms = self.deliver(slave, self.ir_payload(cmd))
        if status == 'busy':
            return status, None, None
        entry = {'at': now_ms(), 'device_id': cmd['device_id'], 'room_name': cmd['room_name'], 'device_name': cmd['device_name'],
                 'key': cmd['key'], 'label': cmd['label'], 'source': source, 'text': text,
                 'slave_id': slave['id'] if slave else None, 'status': status, 'latency_ms': ms}
        entry['id'], _ = self.db.run('INSERT INTO history (at, device_id, room_name, device_name, key, label, source, text, slave_id, status, latency_ms) '
                                     'VALUES (:at, :device_id, :room_name, :device_name, :key, :label, :source, :text, :slave_id, :status, :latency_ms)', entry)
        self.events.publish('history', entry)
        if status == 'ok' and cmd['key'] in TEMP_STEP:
            self._bump_temp(cmd['device_id'], cmd['key'])
        return status, ms, entry
