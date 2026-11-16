"""Bộ điều phối trung tâm: nối CSDL, kênh MQTT, mắt thu IR, học mã, giọng nói và sự kiện."""
import json
import re
import threading
import time

from .db import Database, now_ms
from .events import EventBus
from .learn import LearnManager
from .voice import VoiceService

SLAVE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,32}$')


def public_slave(row):
    if not row:
        return None
    return dict(row, online=bool(row['online']))


class Hub:
    def __init__(self, cfg):
        self.cfg = cfg
        self.started_at = time.time()
        self.db = Database(cfg.DB_PATH)
        self.events = EventBus()
        self.sim_fail_ack = False          # chỉ dùng ở chế độ giả lập
        self._slave_locks = {}
        self._locks_guard = threading.Lock()

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
        self.transport.start()
        threading.Thread(target=self._stale_watch, daemon=True).start()
        threading.Thread(target=self._schedule_loop, daemon=True).start()

    # ---------- Bộ phát ESP8266 ----------
    def on_slave_status(self, sid, data):
        """Gọi khi nhận irhub/slave/<id>/status (định kỳ 30 s, retained; LWT = online:false)."""
        if not SLAVE_ID_RE.match(sid or ''):
            return
        online = 1 if data.get('online') else 0
        now = now_ms()
        row = self.db.one('SELECT * FROM slaves WHERE id = ?', (sid,))
        if not row:
            self.db.run('INSERT INTO slaves (id, name, online, ip, rssi, fw, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (sid, 'ESP8266 %s' % sid[-4:], online, data.get('ip'), data.get('rssi'), data.get('fw'), now))
        else:
            self.db.run('UPDATE slaves SET online = ?, ip = COALESCE(?, ip), rssi = COALESCE(?, rssi), fw = COALESCE(?, fw), '
                        'last_seen = CASE WHEN ? THEN ? ELSE COALESCE(last_seen, ?) END WHERE id = ?',
                        (online, data.get('ip'), data.get('rssi'), data.get('fw'), online, now, now, sid))
        changed = public_slave(self.db.one('SELECT * FROM slaves WHERE id = ?', (sid,)))
        if not row or bool(row['online']) != bool(online) or online:
            self.events.publish('slave', changed)

    def _stale_watch(self):
        """ESP8266 gửi status 30 s/lần. Quá SLAVE_STALE_S giây không thấy → đánh dấu mất kết nối.
        Mỗi giờ dọn lịch sử cũ một lần."""
        last_clean = time.time()
        while True:
            time.sleep(15)
            if time.time() - last_clean > 3600:
                last_clean = time.time()
                self.cleanup_history()
            limit = now_ms() - self.cfg.SLAVE_STALE_S * 1000
            stale = self.db.all('SELECT * FROM slaves WHERE online = 1 AND last_seen < ?', (limit,))
            for s in stale:
                self.db.run('UPDATE slaves SET online = 0 WHERE id = ?', (s['id'],))
                self.events.publish('slave', public_slave(dict(s, online=0)))

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
        for sc in due:
            self.db.run('UPDATE schedules SET last_run = ? WHERE id = ?', (int(now * 1000), sc['id']))
            threading.Thread(target=self._run_schedule, args=(sc,), daemon=True).start()
        return [sc['id'] for sc in due]

    def _run_schedule(self, sc):
        text = 'Hẹn giờ %s' % sc['at_time']
        if sc['scene_id']:
            self.run_scene(sc['scene_id'], source='schedule', text=text)
        else:
            self.send_command(sc['command_id'], source='schedule', text=text)

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
        return status, ms, entry
