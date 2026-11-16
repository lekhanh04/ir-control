"""Học mã IR: thu nhiều lần từ mắt thu trên Pi, so sánh, nhận dạng giao thức hoặc lưu RAW."""
import json
import threading
import time
import uuid

from . import ir_decode
from .db import now_ms


class LearnSession:
    def __init__(self, device, key, captures, timeout_s):
        self.id = 's' + uuid.uuid4().hex[:10]
        self.device = device
        self.key = key
        self.captures = captures
        self.timeout_s = timeout_s
        self.started = time.time()
        self.frames = []
        self.state = 'waiting'        # waiting | done | mismatch | timeout | cancelled
        self.match_pct = None
        self.decoded = None
        self.raw = None

    def public(self):
        if self.state == 'waiting' and time.time() - self.started > self.timeout_s:
            self.state = 'timeout'
        out = {'session': self.id, 'state': self.state, 'count': len(self.frames), 'captures': self.captures}
        if self.state in ('done', 'mismatch'):
            out['match_pct'] = self.match_pct
        if self.state == 'done':
            out['decoded'] = self.decoded
            out['raw_len'] = len(self.raw)
            out['carrier_khz'] = 38   # mắt thu đã lọc sóng mang; giả định 38 kHz phổ biến
        return out


class LearnManager:
    """Mỗi lúc chỉ một phiên học (một mắt thu). Phiên mới thay phiên cũ."""

    def __init__(self, hub):
        self.hub = hub
        self.session = None
        self._lock = threading.Lock()
        if hub.receiver:
            hub.receiver.on_frame = self._on_frame

    def start(self, device, key):
        if not self.hub.receiver:
            raise RuntimeError('ir_receiver')
        cfg = self.hub.cfg
        with self._lock:
            s = LearnSession(device, key, cfg.LEARN_CAPTURES, cfg.LEARN_TIMEOUT_S)
            self.session = s
        self.hub.receiver.arm({'device_id': device['id'], 'type': device['type'], 'key': key})
        return s

    def get(self, sid):
        s = self.session
        return s if s and s.id == sid else None

    def cancel(self, sid):
        with self._lock:
            if self.session and self.session.id == sid:
                self.session.state = 'cancelled'
                self.session = None

    def _on_frame(self, frame):
        with self._lock:
            s = self.session
            if not s or s.state != 'waiting':
                return
            s.frames.append(frame)
            if len(s.frames) < s.captures:
                return
            pct, avg = ir_decode.compare_frames(s.frames)
            s.match_pct = pct
            if pct < self.hub.cfg.LEARN_MIN_MATCH:
                s.state = 'mismatch'
                return
            s.raw = avg
            s.decoded = ir_decode.decode(avg)
            s.state = 'done'

    def _as_command(self, s):
        if s.decoded:
            return dict(s.decoded, kind='protocol')
        return {'kind': 'raw', 'raw': s.raw, 'carrier_khz': 38}

    def test(self, s):
        """Phát thử qua bộ phát của thiết bị (gán riêng hoặc của phòng)."""
        slave = self.hub.slave_for_device(s.device)
        return self.hub.deliver(slave, self.hub.ir_payload(self._as_command(s)))

    def save(self, s, label, replace=False):
        """Trả (command_id, None) hoặc (None, 'exists' | 'label_exists')."""
        c = self._as_command(s)
        now = now_ms()
        exists = self.hub.db.one('SELECT id FROM commands WHERE device_id = ? AND key = ?', (s.device['id'], s.key))
        if exists and not replace:
            return None, 'exists'
        others = self.hub.db.all('SELECT label FROM commands WHERE device_id = ? AND key <> ?', (s.device['id'], s.key))
        if any(o['label'].casefold() == label.casefold() for o in others):
            return None, 'label_exists'
        row = (label, c['kind'], c.get('protocol'), c.get('value'), c.get('address'), c.get('command'), c.get('bits'),
               c.get('carrier_khz', 38), json.dumps(c['raw']) if c['kind'] == 'raw' else None, s.match_pct, now)
        if exists:
            self.hub.db.run('UPDATE commands SET label=?, kind=?, protocol=?, value=?, address=?, command=?, bits=?, carrier_khz=?, raw=?, match_pct=?, updated_at=? WHERE id=?',
                            row + (exists['id'],))
            cid = exists['id']
        else:
            cid, _ = self.hub.db.run('INSERT INTO commands (label, kind, protocol, value, address, command, bits, carrier_khz, raw, match_pct, updated_at, device_id, key, created_at) '
                                     'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', row + (s.device['id'], s.key, now))
        with self._lock:
            if self.session is s:
                self.session = None
        return cid, None
