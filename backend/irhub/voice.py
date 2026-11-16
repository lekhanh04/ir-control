"""Giọng nói: module thu giọng nói gửi câu đã nhận dạng lên MQTT, Pi hiểu câu, tra mã và phát.

Module gửi:   irhub/voice/status    {"online": true}           (retained, LWT online:false)
              irhub/voice/listening {}                          khi phát hiện tiếng nói
              irhub/voice/result    {"text": "bật tivi phòng khách"}
Pi gửi:       irhub/voice/config    {"enabled": true, "sensitivity": "mid"}   (retained)
"""
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


def normalize(text):
    t = unicodedata.normalize('NFC', (text or '').lower().strip())
    return t.replace('hoà', 'hòa').replace('  ', ' ')


class VoiceService:
    def __init__(self, hub):
        self.hub = hub
        self.module_online = bool(hub.cfg.SIMULATE)

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
        if sub == 'status':
            self.module_online = bool(data.get('online'))
        elif sub == 'listening' and self.settings()['enabled']:
            self.hub.events.publish('voice', {'state': 'listening'})
        elif sub == 'result':
            self.handle_text(data.get('text', ''))

    def handle_text(self, text):
        if not self.settings()['enabled'] or not text:
            return
        cmd = self.match(text)
        if not cmd:
            self.hub.log_voice_miss(text)
            self.hub.events.publish('voice', {'state': 'result', 'text': text, 'ok': False})
            return
        res = self.hub.send_command(cmd['id'], source='voice', text=text)
        status = res[0] if res else 'error'
        self.hub.events.publish('voice', {'state': 'result', 'text': text, 'ok': True, 'device_id': cmd['device_id'],
                                          'key': cmd['key'], 'label': cmd['label'], 'status': status})

    def match(self, text):
        """Tìm (phòng, thiết bị, nút) trong câu nói. Trả dòng commands hoặc None."""
        db = self.hub.db
        t = normalize(text)
        rooms = sorted(db.all('SELECT * FROM rooms'), key=lambda r: -len(r['name']))
        room = next((r for r in rooms if normalize(r['name']) in t), None)
        devices = db.all('SELECT * FROM devices')

        def mentions(d):
            return normalize(d['name']) in t or any(w in t for w in TYPE_WORDS.get(d['type'], []))

        cands = [d for d in devices if mentions(d)]
        if not cands:
            # Không nhắc tên thiết bị: thử khớp tên nút tự tạo ("mở netflix") trên mọi thiết bị
            customs = db.all("SELECT c.id, c.device_id, c.key, c.label, d.room_id FROM commands c JOIN devices d ON d.id = c.device_id "
                             "WHERE c.key LIKE 'custom\\_%' ESCAPE '\\'")
            hits = [c for c in customs if normalize(c['label']) in t and (not room or c['room_id'] == room['id'])]
            return hits[0] if len(hits) == 1 else None
        if room:
            cands = [d for d in cands if d['room_id'] == room['id']]
        elif len(cands) > 1:
            default = self.settings()['default_room_id']
            in_default = [d for d in cands if d['room_id'] == default]
            cands = in_default or cands
        if len(cands) != 1:
            return None
        dev = cands[0]
        cmds = db.all('SELECT id, device_id, key, label FROM commands WHERE device_id = ?', (dev['id'],))
        # Nút tự tạo: khớp theo tên nút ("mở netflix")
        for c in sorted(cmds, key=lambda c: -len(c['label'])):
            if c['key'].startswith('custom_') and normalize(c['label']) in t:
                return c
        by_key = {c['key']: c for c in cmds}
        for phrase, key in KEY_RULES:
            if phrase in t and key in by_key:
                return by_key[key]
        return None
