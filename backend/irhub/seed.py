"""Dữ liệu mẫu cho chế độ giả lập (chỉ chạy khi CSDL chưa có phòng nào)."""
import json
import random

from . import ir_decode
from .db import now_ms

LABELS = {
    'power': 'Nguồn', 'source': 'Nguồn vào', 'temp_up': 'Nhiệt độ +', 'temp_down': 'Nhiệt độ −', 'mode': 'Chế độ',
    'fan_speed': 'Tốc độ gió', 'swing': 'Đảo gió', 'vol_up': 'Âm lượng +', 'vol_down': 'Âm lượng −', 'ch_up': 'Kênh +',
    'ch_down': 'Kênh −', 'up': 'Lên', 'down': 'Xuống', 'left': 'Trái', 'right': 'Phải', 'ok': 'OK', 'back': 'Quay lại',
    'home': 'Trang chủ', 'mute': 'Tắt tiếng', 'speed': 'Tốc độ', 'cool': 'Làm mát', 'timer': 'Hẹn giờ', 'menu': 'Menu',
    'freeze': 'Dừng hình', 'blank': 'Tắt hình',
}


def seed_demo(db):
    if db.one('SELECT id FROM rooms LIMIT 1'):
        return
    now = now_ms()
    rooms = {}
    for name in ('Phòng khách', 'Phòng ngủ', 'Phòng họp'):
        rooms[name], _ = db.run('INSERT INTO rooms (name, created_at) VALUES (?, ?)', (name, now))
    for sid, name, room in (('esp-a1f3', 'Bộ phát phòng khách', 'Phòng khách'), ('esp-7c20', 'Bộ phát phòng ngủ', 'Phòng ngủ'),
                            ('esp-91be', 'Bộ phát phòng họp', 'Phòng họp')):
        db.run('INSERT INTO slaves (id, name, room_id, online, last_seen) VALUES (?, ?, ?, 0, ?)', (sid, name, rooms[room], now))

    def device(room, type_, name, brand):
        did, _ = db.run('INSERT INTO devices (room_id, type, name, brand, created_at) VALUES (?, ?, ?, ?, ?)', (rooms[room], type_, name, brand, now))
        return did

    def proto(did, keys, protocol, address, custom=None):
        items = [(k, LABELS[k]) for k in keys] + (custom or [])
        for i, (k, label) in enumerate(items):
            fn = ir_decode.samsung_value if protocol == 'SAMSUNG' else ir_decode.nec_value
            v = fn(address, 0x10 + i)
            db.run('INSERT INTO commands (device_id, key, label, kind, protocol, value, address, command, bits, match_pct, created_at, updated_at) '
                   "VALUES (?, ?, ?, 'protocol', ?, ?, ?, ?, 32, 100, ?, ?)",
                   (did, k, label, protocol, '0x%08X' % v, '0x%02X' % address, '0x%02X' % (0x10 + i), now, now))

    def raw(did, keys):
        rnd = random.Random(did)
        for k in keys:
            d = [3500, 1750] + [x for _ in range(64) for x in (430, rnd.choice((430, 1300)))] + [430]
            db.run('INSERT INTO commands (device_id, key, label, kind, raw, carrier_khz, match_pct, created_at, updated_at) '
                   "VALUES (?, ?, ?, 'raw', ?, 38, 97, ?, ?)", (did, k, LABELS[k], json.dumps(d), now, now))

    raw(device('Phòng khách', 'ac', 'Điều hòa', 'Daikin'), ['power', 'temp_up', 'temp_down', 'mode', 'fan_speed'])
    proto(device('Phòng khách', 'tv', 'Tivi', 'Samsung'),
          ['power', 'source', 'vol_up', 'vol_down', 'ch_up', 'ch_down', 'up', 'down', 'left', 'right', 'ok', 'back', 'mute'],
          'SAMSUNG', 0x07, custom=[('custom_1', 'Netflix')])
    raw(device('Phòng ngủ', 'fan', 'Quạt điều hòa', 'Sunhouse'), ['power', 'speed', 'swing'])
    raw(device('Phòng ngủ', 'ac', 'Điều hòa', 'Panasonic'), ['power'])
    proto(device('Phòng họp', 'projector', 'Máy chiếu', 'Epson'), ['power', 'source', 'freeze'], 'NEC', 0x30)
