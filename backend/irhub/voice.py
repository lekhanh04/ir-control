"""Giọng nói: module thu giọng nói gửi câu đã nhận dạng lên MQTT, Pi hiểu câu, tra mã và phát.

Module gửi:   irhub/voice/status    {"online": true}           (retained, LWT online:false)
              irhub/voice/listening {}                          khi phát hiện tiếng nói
              irhub/voice/result    {"text": "bật tivi phòng khách"}
Pi gửi:       irhub/voice/config    {"enabled": true, "sensitivity": "mid"}   (retained)

Cách hiểu câu:
- So khớp KHÔNG phân biệt dấu ("bat tivi phong khach" cũng hiểu), theo ranh giới từ.
- Tìm phòng, ngữ cảnh, thiết bị (theo tên, hoặc theo loại: "điều hòa", "tivi"…).
  Nếu cụm khớp của thiết bị này nằm gọn trong cụm khớp của thiết bị khác thì chọn cụm dài hơn:
  "quạt điều hòa" là thiết bị Quạt điều hòa, không phải Điều hòa.
- Sau khi bỏ tên phòng/thiết bị khỏi câu, tìm hành động theo KEY_RULES.

Câu nói được xử lý ở một luồng riêng: hàm nhận MQTT phải trả về ngay, nếu không
ACK của ESP8266 (cũng đi qua luồng MQTT đó) không thể tới được trong lúc đang chờ.
"""
import queue
import re
import threading
import unicodedata

TYPE_WORDS = {
    'ac': ['điều hòa', 'máy lạnh'],
    'tv': ['tivi', 'ti vi', 'tv'],
    'fan': ['quạt'],
    'projector': ['máy chiếu'],
}

# Thứ tự quan trọng: cụm dài trước cụm ngắn ("tắt tiếng" trước "tắt").
KEY_RULES = [
    ('tắt tiếng', 'mute'), ('tăng âm lượng', 'vol_up'), ('to lên', 'vol_up'), ('giảm âm lượng', 'vol_down'), ('nhỏ lại', 'vol_down'),
    ('tăng nhiệt độ', 'temp_up'), ('giảm nhiệt độ', 'temp_down'), ('kênh tiếp', 'ch_up'), ('kênh sau', 'ch_up'), ('kênh trước', 'ch_down'),
    ('nguồn vào', 'source'), ('chuyển nguồn', 'source'), ('tốc độ gió', 'fan_speed'), ('đảo gió', 'swing'), ('chế độ', 'mode'),
    ('hẹn giờ', 'timer'), ('dừng hình', 'freeze'), ('tắt hình', 'blank'),
    ('bật', 'power'), ('tắt', 'power'), ('mở', 'power'),   # IR thường chỉ có một nút nguồn bật/tắt luân phiên
]

SENSITIVITY = ('low', 'mid', 'high')


def fold(text):
    """Chữ thường, bỏ dấu, đ → d, ký tự khác chữ/số → khoảng trắng. "Điều-hoà" → "dieu hoa"."""
    t = unicodedata.normalize('NFD', (text or '').lower())
    t = ''.join(ch for ch in t if unicodedata.category(ch) != 'Mn').replace('đ', 'd')
    return ' '.join(re.sub(r'[^\w]+', ' ', t).split())


def find(phrase, t):
    """Vị trí (đầu, cuối) của cụm từ trong câu đã fold, đúng ranh giới từ; None nếu không có."""
    p = fold(phrase)
    if not p:
        return None
    m = re.search(r'(?<!\w)' + re.escape(p) + r'(?!\w)', t)
    return m.span() if m else None


def _inside(a, b):
    """Đoạn a nằm gọn trong đoạn b và ngắn hơn b."""
    return b[0] <= a[0] and a[1] <= b[1] and (b[1] - b[0]) > (a[1] - a[0])


def _blank(t, spans):
    for a, b in spans:
        t = t[:a] + ' ' * (b - a) + t[b:]
    return t


class VoiceService:
    def __init__(self, hub):
        self.hub = hub
        self.module_online = bool(hub.cfg.SIMULATE)
        self._jobs = queue.Queue(maxsize=20)
        threading.Thread(target=self._worker, daemon=True).start()

    # ---------- cài đặt ----------
    def settings(self):
        db = self.hub.db
        room = db.get_setting('voice.default_room_id')
        return {
            'enabled': db.get_setting('voice.enabled', '1') == '1',
            'sensitivity': db.get_setting('voice.sensitivity', 'mid'),
            'default_room_id': int(room) if room else None,
        }

    def public(self):
        return dict(self.settings(), module='ok' if self.module_online else 'missing')

    def update(self, body):
        db = self.hub.db
        if 'enabled' in body:
            db.set_setting('voice.enabled', '1' if body['enabled'] else '0')
        if body.get('sensitivity') in SENSITIVITY:
            db.set_setting('voice.sensitivity', body['sensitivity'])
        if 'default_room_id' in body:
            db.set_setting('voice.default_room_id', body['default_room_id'] or '')
        self.push_config()

    def push_config(self):
        s = self.settings()
        self.hub.transport.publish('voice/config', {'enabled': s['enabled'], 'sensitivity': s['sensitivity']}, retain=True)

    # ---------- nhận từ module ----------
    def on_message(self, sub, data):
        """Gọi từ luồng MQTT: chỉ ghi nhận rồi trả về ngay."""
        if sub == 'status':
            self.module_online = bool(data.get('online'))
        elif sub == 'listening' and self.settings()['enabled']:
            self.hub.events.publish('voice', {'state': 'listening'})
        elif sub == 'result':
            try:
                self._jobs.put_nowait(data.get('text', ''))
            except queue.Full:
                print('[Giọng nói] Hàng đợi đầy, bỏ câu:', data.get('text'))

    def _worker(self):
        while True:
            text = self._jobs.get()
            try:
                self.handle_text(text)
            except Exception as e:
                print('[Giọng nói] Lỗi khi xử lý "%s": %s' % (text, e))

    def handle_text(self, text):
        """Hiểu câu và phát lệnh (chạy đồng bộ). Trả sự kiện voice đã gửi lên giao diện, hoặc None nếu đang tắt."""
        if not self.settings()['enabled'] or not (text or '').strip():
            return None
        hit = self.match(text)
        if not hit:
            self.hub.log_voice_miss(text)
            ev = {'state': 'result', 'text': text, 'ok': False}
        elif 'scene' in hit:
            res = self.hub.run_scene(hit['scene']['id'], source='voice', text=text)
            ev = {'state': 'result', 'text': text, 'ok': True, 'scene': hit['scene']['name'],
                  'status': res['status'] if res else 'error'}
        else:
            res = self.hub.send_command(hit['id'], source='voice', text=text)
            ev = {'state': 'result', 'text': text, 'ok': True, 'device_id': hit['device_id'],
                  'key': hit['key'], 'label': hit['label'], 'status': res[0] if res else 'error'}
        self.hub.events.publish('voice', ev)
        return ev

    def match(self, text):
        """Tìm lệnh trong câu nói. Trả dòng commands (id, device_id, key, label), {'scene': dòng scenes} hoặc None."""
        db = self.hub.db
        t = fold(text)

        room, room_span = None, None
        for r in db.all('SELECT * FROM rooms'):
            sp = find(r['name'], t)
            if sp and (not room_span or sp[1] - sp[0] > room_span[1] - room_span[0]):
                room, room_span = r, sp

        # Thiết bị được nhắc tới: lấy cụm khớp dài nhất (tên hoặc loại) của mỗi thiết bị
        cands = []
        for d in db.all('SELECT * FROM devices'):
            spans = [sp for sp in [find(d['name'], t)] + [find(w, t) for w in TYPE_WORDS.get(d['type'], [])] if sp]
            if spans:
                cands.append((d, max(spans, key=lambda sp: sp[1] - sp[0])))
        cands = [c for c in cands if not any(_inside(c[1], o[1]) for o in cands)]

        # Ngữ cảnh: thắng khi không nhắc thiết bị nào, hoặc tên ngữ cảnh bao trùm mọi thiết bị được nhắc
        scene, scene_span = None, None
        for sc in db.all('SELECT * FROM scenes'):
            sp = find(sc['name'], t)
            if sp and (not scene_span or sp[1] - sp[0] > scene_span[1] - scene_span[0]):
                scene, scene_span = sc, sp
        if scene and all(scene_span[0] <= c[1][0] and c[1][1] <= scene_span[1] for c in cands):
            return {'scene': scene}

        if not cands:
            # Không nhắc tên thiết bị: thử khớp tên nút tự tạo ("mở netflix") trên mọi thiết bị
            customs = db.all("SELECT c.id, c.device_id, c.key, c.label, d.room_id FROM commands c JOIN devices d ON d.id = c.device_id "
                             "WHERE c.key LIKE 'custom\\_%' ESCAPE '\\'")
            hits = [c for c in customs if find(c['label'], t) and (not room or c['room_id'] == room['id'])]
            return hits[0] if len(hits) == 1 else None

        if room:
            cands = [c for c in cands if c[0]['room_id'] == room['id']]
        elif len(cands) > 1:
            default = self.settings()['default_room_id']
            cands = [c for c in cands if c[0]['room_id'] == default] or cands
        if len(cands) != 1:
            return None
        dev, dev_span = cands[0]

        cmds = db.all('SELECT id, device_id, key, label FROM commands WHERE device_id = ?', (dev['id'],))
        # Nút tự tạo: khớp theo tên nút ("mở netflix")
        for c in sorted(cmds, key=lambda c: -len(c['label'])):
            if c['key'].startswith('custom_') and find(c['label'], t):
                return c
        rest = _blank(t, [sp for sp in (room_span, dev_span) if sp])   # bỏ tên phòng/thiết bị trước khi tìm hành động
        by_key = {c['key']: c for c in cmds}
        for phrase, key in KEY_RULES:
            sp = find(phrase, rest)
            if sp:
                if key in by_key:
                    return by_key[key]
                # Cụm đã khớp nhưng thiết bị chưa học nút này: xóa cụm đi để "tắt tiếng" không bị hiểu thành "tắt"
                rest = _blank(rest, [sp])
        return None
