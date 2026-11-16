import queue
import threading
import time
import uuid

import pytest

from irhub.voice import fold


def keyof(hit):
    return hit and (hit['device_id'], hit['key'])


@pytest.mark.parametrize('text,expected', [
    ('bật quạt điều hòa phòng ngủ', (3, 'power')),     # trước đây bị coi là không hiểu (trùng "điều hòa")
    ('tắt điều hòa phòng ngủ', (4, 'power')),
    ('bật tivi phòng khách', (2, 'power')),
    ('bat tivi phong khach', (2, 'power')),            # không dấu
    ('TĂNG ÂM LƯỢNG TIVI', (2, 'vol_up')),
    ('Điều hoà phòng khách tăng nhiệt độ', (1, 'temp_up')),   # "hoà" kiểu dấu cũ
    ('tắt tiếng tivi', (2, 'mute')),
    ('mở netflix', (2, 'custom_1')),
    ('bật quạt', (3, 'power')),
    ('tắt máy chiếu phòng họp', (5, 'power')),
    ('kênh tiếp ti vi', (2, 'ch_up')),
])
def test_understood(hub, text, expected):
    assert keyof(hub.voice.match(text)) == expected


@pytest.mark.parametrize('text', [
    'bật điều hòa',          # hai điều hòa, không nói phòng, chưa đặt phòng mặc định
    'hát một bài đi',
    'tắt tiếng quạt',        # quạt chưa học nút Tắt tiếng: không được hiểu thành "tắt" (nút Nguồn)
    'bật tivi phòng ngủ',    # phòng ngủ không có tivi
    'batman',                # "bat" phải đúng ranh giới từ
])
def test_not_understood(hub, text):
    assert hub.voice.match(text) is None


def test_default_room(hub, client):
    client.post('/api/voice', json={'default_room_id': 2})
    assert keyof(hub.voice.match('bật điều hòa')) == (4, 'power')


def test_fold():
    assert fold('  Điều-HOÀ   phòng Khách! ') == 'dieu hoa phong khach'


def test_scene_by_voice(hub, client):
    client.post('/api/scenes', json={'name': 'Đi ngủ', 'steps': [{'command_id': 23, 'delay_ms': 0}, {'command_id': 20, 'delay_ms': 0}]})
    hit = hub.voice.match('bật chế độ đi ngủ')
    assert hit['scene']['name'] == 'Đi ngủ'
    ev = hub.voice.handle_text('di ngu')
    assert ev['scene'] == 'Đi ngủ' and ev['status'] == 'ok'


def test_device_beats_scene_with_room_name(hub, client):
    # Ngữ cảnh trùng tên phòng không được "nuốt" lệnh cho thiết bị trong phòng đó
    client.post('/api/scenes', json={'name': 'Phòng khách', 'steps': [{'command_id': 6}]})
    assert keyof(hub.voice.match('tắt tivi phòng khách')) == (2, 'power')


def test_not_understood_is_logged(hub, client):
    ev = hub.voice.handle_text('hát một bài đi')
    assert ev['ok'] is False
    h = client.get('/api/history').get_json()[0]
    assert (h['status'], h['text'], h['source']) == ('not_understood', 'hát một bài đi', 'voice')


def test_disabled_voice_ignored(hub, client):
    client.post('/api/voice', json={'enabled': False})
    assert hub.voice.handle_text('bật tivi phòng khách') is None


class LoopTransport:
    """Mô phỏng paho-mqtt: MỘT luồng mạng vừa chuyển câu nói tới voice.on_message, vừa nhận ACK.
    Nếu on_message chặn luồng này trong lúc chờ ACK thì ACK không bao giờ tới (lỗi cũ)."""

    def __init__(self, hub):
        self.hub = hub
        self.inbox = queue.Queue()
        self.pending = {}
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            kind, data = self.inbox.get()
            if kind == 'voice':
                self.hub.voice.on_message('result', data)
            elif kind == 'ack' and data['req'] in self.pending:
                self.pending[data['req']].set()

    def send(self, slave_id, ir, timeout):
        req, ev = uuid.uuid4().hex, threading.Event()
        self.pending[req] = ev
        self.inbox.put(('ack', {'req': req}))     # ESP8266 trả ACK ngay, đi qua luồng mạng
        return {'req': req, 'ok': True} if ev.wait(timeout) else None

    def publish(self, *a, **k):
        pass

    def healthy(self):
        return True


def test_voice_from_mqtt_thread_gets_ack(hub, client):
    hub.cfg.ACK_TIMEOUT_S = 1.0
    hub.transport = LoopTransport(hub)
    hub.transport.inbox.put(('voice', {'text': 'bật tivi phòng khách'}))
    deadline = time.time() + 5
    while time.time() < deadline:
        hist = client.get('/api/history').get_json()
        if hist and hist[0]['source'] == 'voice':
            break
        time.sleep(0.05)
    assert hist[0]['status'] == 'ok', 'lệnh giọng nói phải nhận được ACK, không bị timeout'
