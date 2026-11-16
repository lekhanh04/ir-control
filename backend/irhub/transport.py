"""Kênh liên lạc với các ESP8266 Slave và module giọng nói.

MqttTransport: chạy thật qua MQTT broker (Mosquitto). Topic và payload: xem docs/giao-tiep-thiet-bi.md
SimTransport : giả lập 4 bộ phát trong bộ nhớ, không cần broker (IRHUB_SIMULATE=1).

Cả hai gọi về hub qua cùng các hàm: hub.on_slave_status(), hub.voice.on_message(),
nên logic phía trên không phân biệt thật hay giả lập.
"""
import json
import random
import threading
import time
import uuid


class MqttTransport:
    def __init__(self, hub):
        import paho.mqtt.client as mqtt  # paho-mqtt >= 2.0
        self.hub = hub
        cfg = hub.cfg
        self.p = cfg.MQTT_PREFIX
        self.connected = False
        self._pending = {}
        self._lock = threading.Lock()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='irhub-pi-%s' % uuid.uuid4().hex[:6])
        if cfg.MQTT_USER:
            self.client.username_pw_set(cfg.MQTT_USER, cfg.MQTT_PASS)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)

    def start(self):
        self.client.connect_async(self.hub.cfg.MQTT_HOST, self.hub.cfg.MQTT_PORT, keepalive=30)
        self.client.loop_start()

    def healthy(self):
        return self.connected

    # ---- nhận ----
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = not reason_code.is_failure
        if self.connected:
            p = self.p
            client.subscribe([('%s/slave/+/status' % p, 1), ('%s/slave/+/ack' % p, 1),
                              ('%s/voice/status' % p, 1), ('%s/voice/listening' % p, 0), ('%s/voice/result' % p, 1)])
            self.hub.voice.push_config()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode('utf-8') or '{}')
        except ValueError:
            return
        parts = msg.topic.split('/')
        if len(parts) == 4 and parts[1] == 'slave':
            if parts[3] == 'status':
                self.hub.on_slave_status(parts[2], data)
            elif parts[3] == 'ack':
                with self._lock:
                    waiter = self._pending.get(data.get('req'))
                if waiter:
                    waiter['result'] = data
                    waiter['event'].set()
        elif len(parts) == 3 and parts[1] == 'voice':
            self.hub.voice.on_message(parts[2], data)

    # ---- gửi ----
    def publish(self, topic, payload, retain=False, qos=1):
        self.client.publish('%s/%s' % (self.p, topic), json.dumps(payload, ensure_ascii=False), qos=qos, retain=retain)

    def send(self, slave_id, ir, timeout):
        """Gửi mã IR tới một ESP8266 và chờ ACK. Trả dict ACK hoặc None nếu quá thời gian."""
        req = uuid.uuid4().hex[:8]
        waiter = {'event': threading.Event(), 'result': None}
        with self._lock:
            self._pending[req] = waiter
        try:
            self.publish('slave/%s/cmd' % slave_id, dict(ir, req=req))
            waiter['event'].wait(timeout)
            return waiter['result']
        finally:
            with self._lock:
                self._pending.pop(req, None)

    def identify(self, slave_id, seconds=5):
        self.publish('slave/%s/identify' % slave_id, {'seconds': seconds}, qos=0)


class SimTransport:
    """4 bộ phát giả: 3 đã gán phòng (1 mất kết nối), 1 bộ mới chưa gán."""

    SLAVES = [
        ('esp-a1f3', True, '192.168.1.51', -54),
        ('esp-7c20', True, '192.168.1.52', -67),
        ('esp-91be', False, '192.168.1.53', -81),
        ('esp-0d44', True, '192.168.1.54', -60),
    ]

    def __init__(self, hub):
        self.hub = hub
        self.online = {}

    def start(self):
        for sid, online, ip, rssi in self.SLAVES:
            self.set_online(sid, online, ip=ip, rssi=rssi)
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def _heartbeat(self):
        # Giống firmware thật: bộ phát đang sống gửi status 30 s/lần
        while True:
            time.sleep(30)
            for sid, online in list(self.online.items()):
                if online:
                    self.hub.on_slave_status(sid, {'online': True})

    def healthy(self):
        return True

    def set_online(self, sid, online, ip=None, rssi=None):
        self.online[sid] = online
        self.hub.on_slave_status(sid, {'online': online, 'ip': ip, 'rssi': rssi, 'fw': '1.0.2'})

    def publish(self, topic, payload, retain=False, qos=1):
        pass

    def send(self, slave_id, ir, timeout):
        if not self.online.get(slave_id):
            time.sleep(timeout)
            return None
        if self.hub.sim_fail_ack:
            time.sleep(timeout)
            return None
        time.sleep(random.uniform(0.08, 0.2))
        return {'req': 'sim', 'ok': True}

    def identify(self, slave_id, seconds=5):
        pass
