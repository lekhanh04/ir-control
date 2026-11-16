"""API phục vụ các cải tiến giao diện: nhiệt độ ước tính, sắp xếp, đồng bộ nhiều máy, phân trang lịch sử, hẹn giờ."""
import queue
import time

import pytest


# ---------- Nút Nguồn trên thẻ thiết bị ----------
def test_devices_list_has_power_command(client):
    devs = {d['id']: d for d in client.get('/api/devices').get_json()}
    assert devs[2]['power_command_id'] == 6
    client.delete('/api/commands/6')
    assert client.get('/api/devices').get_json()[1]['power_command_id'] is None


# ---------- Nhiệt độ ước tính ----------
def test_temperature_follows_temp_buttons(client):
    assert client.get('/api/devices').get_json()[0]['temp'] is None
    client.post('/api/send', json={'command_id': 2})              # chưa đặt nhiệt độ → không đoán
    assert client.get('/api/devices').get_json()[0]['temp'] is None
    assert client.put('/api/devices/1/state', json={'temp': 25}).get_json() == {'device_id': 1, 'temp': 25}
    client.post('/api/send', json={'command_id': 2})              # Nhiệt độ +
    client.post('/api/send', json={'command_id': 2})
    client.post('/api/send', json={'command_id': 3})              # Nhiệt độ −
    assert client.get('/api/devices').get_json()[0]['temp'] == 26


def test_temperature_clamped_and_not_changed_on_failure(client, hub):
    client.put('/api/devices/1/state', json={'temp': 30})
    client.post('/api/send', json={'command_id': 2})
    assert client.get('/api/devices').get_json()[0]['temp'] == 30
    hub.sim_fail_ack = True
    client.post('/api/send', json={'command_id': 3})              # không có ACK → giữ nguyên
    assert client.get('/api/devices').get_json()[0]['temp'] == 30


@pytest.mark.parametrize('t', [15, 31, '25', 25.5, True])
def test_temperature_validation(client, t):
    assert client.put('/api/devices/1/state', json={'temp': t}).status_code == 400


def test_temperature_cleared_and_removed_with_device(client, hub):
    client.put('/api/devices/1/state', json={'temp': 24})
    client.put('/api/devices/1/state', json={'temp': None})
    assert client.get('/api/devices').get_json()[0]['temp'] is None
    client.put('/api/devices/4/state', json={'temp': 24})
    client.delete('/api/devices/4')
    assert hub.db.one('SELECT COUNT(*) n FROM device_state')['n'] == 0


# ---------- Sắp xếp ----------
def test_reorder_rooms_devices_commands(client):
    assert client.put('/api/order', json={'kind': 'room', 'ids': [3, 1, 2]}).status_code == 200
    assert [r['id'] for r in client.get('/api/rooms').get_json()] == [3, 1, 2]
    client.post('/api/rooms', json={'name': 'Bếp'})                 # phòng mới chưa xếp → cuối
    assert client.get('/api/rooms').get_json()[-1]['name'] == 'Bếp'
    client.put('/api/order', json={'kind': 'device', 'ids': [2, 1]})
    assert [d['id'] for d in client.get('/api/devices').get_json() if d['room_id'] == 1] == [2, 1]
    client.put('/api/order', json={'kind': 'command', 'ids': [19, 6]})
    assert [c['id'] for c in client.get('/api/devices/2/commands').get_json()][:2] == [19, 6]


@pytest.mark.parametrize('body', [
    {'kind': 'room', 'ids': []}, {'kind': 'x', 'ids': [1]}, {'kind': 'room', 'ids': [1, 1]},
    {'kind': 'room', 'ids': [999]}, {'kind': 'room', 'ids': ['1']}, {'kind': 'room'},
])
def test_reorder_validation(client, body):
    assert client.put('/api/order', json=body).status_code == 400


def test_order_cleaned_on_delete(client, hub):
    client.put('/api/order', json={'kind': 'device', 'ids': [2, 1]})
    client.put('/api/order', json={'kind': 'command', 'ids': [19, 6]})
    client.delete('/api/devices/2')
    left = hub.db.all('SELECT kind, item_id FROM ui_order ORDER BY kind, item_id')
    assert left == [{'kind': 'device', 'item_id': 1}]


# ---------- Đồng bộ nhiều trình duyệt ----------
def drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


def test_changed_event_on_config_change(client, hub):
    q = hub.events.subscribe()
    client.post('/api/rooms', json={'name': 'Bếp'}, headers={'X-Client-Id': 'abc'})
    msgs = [m for m in drain(q) if m.startswith('event: changed')]
    assert len(msgs) == 1 and '"/api/rooms"' in msgs[0] and '"abc"' in msgs[0]
    # gửi lệnh, chạy ngữ cảnh, lỗi kiểm tra dữ liệu: không báo "changed"
    client.post('/api/send', json={'command_id': 6})
    client.post('/api/rooms', json={'name': ''})
    assert not [m for m in drain(q) if m.startswith('event: changed')]


# ---------- Lịch sử: phân trang, lọc ----------
def test_history_paging_and_filters(client, hub):
    for i in range(7):
        hub.db.run("INSERT INTO history (at, device_name, source, status) VALUES (?, 'x', ?, ?)",
                   (1000 + i // 2, 'voice' if i % 3 == 0 else 'web', 'ok' if i % 2 else 'timeout'))
    page1 = client.get('/api/history?limit=3').get_json()
    last = page1[-1]
    page2 = client.get('/api/history?limit=3&before=%d&before_id=%d' % (last['at'], last['id'])).get_json()
    page3 = client.get('/api/history?limit=3&before=%d&before_id=%d' % (page2[-1]['at'], page2[-1]['id'])).get_json()
    ids = [h['id'] for h in page1 + page2 + page3]
    assert len(ids) == 7 == len(set(ids))                          # không trùng, không sót kể cả khi cùng `at`
    assert all(h['source'] == 'voice' for h in client.get('/api/history?filter=voice').get_json())
    assert all(h['status'] != 'ok' for h in client.get('/api/history?filter=fail').get_json())


# ---------- Hẹn giờ: lần tới, lần trước ----------
def test_next_run():
    from irhub.hub import Hub
    mon_7 = time.mktime((2026, 11, 16, 7, 0, 0, 0, 0, -1))          # Thứ Hai 07:00
    assert Hub.next_run('07:30', 127, True, mon_7) == int((mon_7 + 1800) * 1000)
    assert Hub.next_run('06:00', 127, True, mon_7) == int(time.mktime((2026, 11, 17, 6, 0, 0, 0, 0, -1)) * 1000)
    assert Hub.next_run('06:00', 1, True, mon_7) == int(time.mktime((2026, 11, 23, 6, 0, 0, 0, 0, -1)) * 1000)   # Thứ Hai tuần sau
    assert Hub.next_run('06:00', 127, False, mon_7) is None


def test_schedule_last_run_recorded(client, hub):
    s = client.post('/api/schedules', json={'command_id': 6, 'at_time': '07:00'}).get_json()
    assert s['last_status'] is None and s['next_run']
    hub.run_due_schedules(time.mktime((2026, 11, 16, 7, 0, 5, 0, 0, -1)))
    time.sleep(0.6)
    s = client.get('/api/schedules').get_json()[0]
    assert (s['last_status'], s['last_ok'], s['last_total']) == ('ok', 1, 1)
