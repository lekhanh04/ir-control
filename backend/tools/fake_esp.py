"""ESP8266 giả qua MQTT thật: dùng để thử backend ở chế độ IRHUB_SIMULATE=0 khi chưa có mạch.

    python tools/fake_esp.py esp-test01 [--host localhost] [--user irhub --password ...] [--fail]

Làm đúng như firmware trong docs/giao-tiep-thiet-bi.md: status retained + LWT, status 30 s/lần,
nhận cmd → in ra mã sẽ phát → gửi ack; nhận identify → in thông báo.
"""
import argparse
import json
import time

import paho.mqtt.client as mqtt

ap = argparse.ArgumentParser()
ap.add_argument('id', help='mã bộ phát, vd esp-test01')
ap.add_argument('--host', default='localhost')
ap.add_argument('--port', type=int, default=1883)
ap.add_argument('--prefix', default='irhub')
ap.add_argument('--user', default='', help='tài khoản MQTT (khi Mosquitto bắt buộc đăng nhập)')
ap.add_argument('--password', default='')
ap.add_argument('--fail', action='store_true', help='không gửi ACK (thử trường hợp mất xác nhận)')
args = ap.parse_args()

base = '%s/slave/%s' % (args.prefix, args.id)
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=args.id)
c.will_set(base + '/status', json.dumps({'online': False}), qos=1, retain=True)
if args.user:
    c.username_pw_set(args.user, args.password)


def status():
    c.publish(base + '/status', json.dumps({'online': True, 'ip': '127.0.0.1', 'rssi': -58, 'fw': 'fake-1.0'}), qos=1, retain=True)


def on_connect(client, userdata, flags, reason_code, properties):
    print('Đã kết nối broker:', reason_code)
    if reason_code.is_failure:
        print('Sai tài khoản/mật khẩu MQTT? Dùng --user và --password.')
        return
    client.subscribe([(base + '/cmd', 1), (base + '/identify', 0)])
    status()


def on_message(client, userdata, msg):
    data = json.loads(msg.payload or b'{}')
    if msg.topic.endswith('/identify'):
        print('>>> Nháy đèn %s giây' % data.get('seconds'))
        return
    if data.get('type') == 'raw':
        print('>>> Phát RAW %d xung @ %s kHz' % (len(data.get('data', [])), data.get('freq')))
    else:
        print('>>> Phát %s %s (%s bit)' % (data.get('protocol'), data.get('value'), data.get('bits')))
    if not args.fail:
        time.sleep(0.05)
        client.publish(base + '/ack', json.dumps({'req': data.get('req'), 'ok': True}), qos=1)


c.on_connect = on_connect
c.on_message = on_message
c.connect(args.host, args.port, keepalive=30)
c.loop_start()
try:
    while True:
        time.sleep(30)
        status()
except KeyboardInterrupt:
    c.publish(base + '/status', json.dumps({'online': False}), qos=1, retain=True).wait_for_publish(2)
    c.loop_stop()
