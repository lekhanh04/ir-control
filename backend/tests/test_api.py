import time

import pytest


# ---------- Phòng, thiết bị, nút ----------
def test_room_names_unique_ignoring_case_and_accents_case(client):
    assert client.post('/api/rooms', json={'name': 'PHÒNG KHÁCH'}).status_code == 409
    r = client.post('/api/rooms', json={'name': 'Bếp'})
    assert r.status_code == 201
    assert client.patch('/api/rooms/%d' % r.get_json()['id'], json={'name': 'phòng ngủ'}).status_code == 409


def test_room_with_devices_cannot_be_deleted(client):
    assert client.delete('/api/rooms/1').get_json()['error'] == 'not_empty'


def test_device_create_and_duplicate(client):
    r = client.post('/api/devices', json={'name': 'Loa', 'type': 'other', 'room_id': 1})
    assert r.status_code == 201 and r.get_json()['command_count'] == 0
    assert client.post('/api/devices', json={'name': 'LOA', 'type': 'other', 'room_id': 1}).status_code == 409
    assert client.post('/api/devices', json={'name': 'Loa', 'type': 'nope', 'room_id': 1}).status_code == 400


def test_device_slave_must_be_in_same_room(client):
    assert client.patch('/api/devices/2', json={'slave_id': 'esp-7c20'}).status_code == 400
    assert client.patch('/api/devices/2', json={'slave_id': 'esp-a1f3'}).get_json()['slave_id'] == 'esp-a1f3'
    # đổi phòng → bỏ gán bộ phát riêng
    assert client.patch('/api/devices/2', json={'room_id': 2}).get_json()['slave_id'] is None
    # phòng ngủ đã có "Điều hòa" → không chuyển điều hòa phòng khách sang được
    assert client.patch('/api/devices/1', json={'room_id': 2}).status_code == 409


def test_commands_list_and_rename(client):
    cmds = client.get('/api/devices/1/commands').get_json()
    assert cmds[0]['kind'] == 'raw' and cmds[0]['raw_len'] > 100
    assert client.patch('/api/commands/2', json={'label': 'nguồn'}).status_code == 409   # trùng "Nguồn"
    assert client.patch('/api/commands/2', json={'label': 'Nóng hơn'}).get_json()['label'] == 'Nóng hơn'


# ---------- Gửi lệnh ----------
def test_send_ok_writes_history(client):
    r = client.post('/api/send', json={'command_id': 6}).get_json()
    assert r['status'] == 'ok' and r['latency_ms'] >= 0
    h = client.get('/api/history?limit=1').get_json()[0]
    assert (h['device_name'], h['label'], h['source'], h['status']) == ('Tivi', 'Nguồn', 'web', 'ok')


def test_send_offline_slave(client):
    r = client.post('/api/send', json={'command_id': 24})   # máy chiếu, bộ phát phòng họp mất kết nối
    assert r.status_code == 503 and r.get_json()['error'] == 'slave_offline'


def test_send_no_ack(client, hub):
    hub.sim_fail_ack = True
    assert client.post('/api/send', json={'command_id': 6}).get_json()['error'] == 'no_ack'


def test_send_unknown(client):
    assert client.post('/api/send', json={'command_id': 9999}).status_code == 404
    assert client.post('/api/send', json={}).status_code == 404


# ---------- Học mã ----------
def wait_learn(client, sid, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        st = client.get('/api/learn/' + sid).get_json()
        if st['state'] != 'waiting':
            return st
        time.sleep(0.1)
    raise AssertionError('phiên học không kết thúc')


def test_learn_flow_save_and_replace(client):
    r = client.post('/api/learn', json={'device_id': 2, 'key': 'home'}).get_json()
    st = wait_learn(client, r['session'])
    assert st['state'] == 'done' and st['decoded']['protocol'] == 'SAMSUNG'
    assert client.post('/api/learn/%s/test' % r['session']).get_json()['status'] == 'ok'
    saved = client.post('/api/learn/%s/save' % r['session'], json={'label': 'Trang chủ'}).get_json()
    assert saved['key'] == 'home'
    # học lại nút đã có: phải xác nhận thay mã
    r2 = client.post('/api/learn', json={'device_id': 2, 'key': 'home'}).get_json()
    wait_learn(client, r2['session'])
    assert client.post('/api/learn/%s/save' % r2['session'], json={'label': 'Trang chủ'}).get_json()['error'] == 'exists'
    assert client.post('/api/learn/%s/save' % r2['session'], json={'label': 'Trang chủ', 'replace': True}).get_json()['id'] == saved['id']


def test_learn_busy_and_force(client, hub):
    hub.receiver.mode = 'timeout'           # mắt thu giả không tự bấm
    a = client.post('/api/learn', json={'device_id': 2, 'key': 'home'})
    assert a.status_code == 200
    b = client.post('/api/learn', json={'device_id': 1, 'key': 'swing'})
    assert b.status_code == 409 and b.get_json()['error'] == 'receiver_busy'
    c = client.post('/api/learn', json={'device_id': 1, 'key': 'swing', 'force': True})
    assert c.status_code == 200
    assert client.get('/api/learn/' + a.get_json()['session']).status_code == 404   # phiên cũ bị thay


def test_learn_frame_after_timeout_is_rejected(client, hub):
    hub.receiver.mode = 'timeout'
    sid = client.post('/api/learn', json={'device_id': 2, 'key': 'home'}).get_json()['session']
    s = hub.learn.get(sid)
    s.started -= 1000                        # giả như đã quá giờ
    for _ in range(3):
        hub.learn._on_frame([9000, 4500] + [560, 560] * 33)
    assert s.state == 'timeout' and not s.frames


def test_learn_mismatch(client, hub):
    hub.receiver.mode = 'mismatch'
    sid = client.post('/api/learn', json={'device_id': 2, 'key': 'home'}).get_json()['session']
    assert wait_learn(client, sid)['state'] == 'mismatch'


# ---------- Ngữ cảnh ----------
def test_scene_crud_and_run(client):
    r = client.post('/api/scenes', json={'name': 'Xem phim', 'steps': [{'command_id': 6, 'delay_ms': 0}, {'command_id': 19, 'delay_ms': 50}]})
    assert r.status_code == 201
    sc = r.get_json()
    assert [s['label'] for s in sc['steps']] == ['Nguồn', 'Netflix']
    assert client.post('/api/scenes', json={'name': 'XEM PHIM', 'steps': [{'command_id': 6}]}).status_code == 409
    res = client.post('/api/scenes/%d/run' % sc['id']).get_json()
    assert res['status'] == 'ok' and len(res['results']) == 2
    hist = client.get('/api/history?limit=2').get_json()
    assert {h['source'] for h in hist} == {'scene'} and hist[0]['text'] == 'Xem phim'
    up = client.put('/api/scenes/%d' % sc['id'], json={'name': 'Xem phim', 'steps': [{'command_id': 7}]}).get_json()
    assert [s['command_id'] for s in up['steps']] == [7]
    assert client.delete('/api/scenes/%d' % sc['id']).get_json() == {'ok': True}
    assert client.get('/api/scenes').get_json() == []


def test_scene_partial_when_one_slave_offline(client):
    sc = client.post('/api/scenes', json={'name': 'Tắt hết', 'steps': [{'command_id': 6, 'delay_ms': 0}, {'command_id': 24, 'delay_ms': 0}]}).get_json()
    res = client.post('/api/scenes/%d/run' % sc['id']).get_json()
    assert res['status'] == 'partial'
    assert [x['status'] for x in res['results']] == ['ok', 'offline']


@pytest.mark.parametrize('body', [
    {'name': '', 'steps': [{'command_id': 6}]},
    {'name': 'A', 'steps': []},
    {'name': 'A', 'steps': [{'command_id': 9999}]},
    {'name': 'A', 'steps': [{'command_id': 6, 'delay_ms': -1}]},
    {'name': 'A', 'steps': [{'command_id': True}]},
    {'name': 'A', 'steps': 'x'},
])
def test_scene_validation(client, body):
    assert client.post('/api/scenes', json=body).status_code == 400


def test_deleting_device_removes_its_scene_steps(client):
    sc = client.post('/api/scenes', json={'name': 'S', 'steps': [{'command_id': 6}, {'command_id': 20}]}).get_json()
    client.delete('/api/devices/2')
    assert [s['command_id'] for s in client.get('/api/scenes').get_json()[0]['steps']] == [20]
    assert sc['id']


# ---------- Hẹn giờ ----------
def test_schedule_crud(client):
    sc = client.post('/api/scenes', json={'name': 'S', 'steps': [{'command_id': 6}]}).get_json()
    r = client.post('/api/schedules', json={'scene_id': sc['id'], 'at_time': '06:30', 'days': 0b0011111})
    assert r.status_code == 201
    s = r.get_json()
    assert s['scene_name'] == 'S' and s['enabled'] is True
    s2 = client.post('/api/schedules', json={'command_id': 23, 'at_time': '22:00'}).get_json()
    assert (s2['device_name'], s2['command_label'], s2['days']) == ('Điều hòa', 'Nguồn', 127)
    assert client.patch('/api/schedules/%d' % s['id'], json={'enabled': False}).get_json()['enabled'] is False
    assert [x['at_time'] for x in client.get('/api/schedules').get_json()] == ['06:30', '22:00']
    assert client.delete('/api/schedules/%d' % s['id']).get_json() == {'ok': True}


@pytest.mark.parametrize('body', [
    {'command_id': 6, 'at_time': '24:00'},
    {'command_id': 6, 'at_time': '7:00'},
    {'command_id': 6, 'at_time': '07:00', 'days': 0},
    {'command_id': 6, 'scene_id': 1, 'at_time': '07:00'},
    {'at_time': '07:00'},
    {'command_id': 9999, 'at_time': '07:00'},
])
def test_schedule_validation(client, body):
    if body.get('scene_id'):
        client.post('/api/scenes', json={'name': 'S', 'steps': [{'command_id': 6}]})
    assert client.post('/api/schedules', json=body).status_code == 400


def test_run_due_schedules(client, hub):
    # Thứ Hai 2026-11-16 07:00:20 giờ địa phương
    now = time.mktime((2026, 11, 16, 7, 0, 20, 0, 0, -1))
    mon = client.post('/api/schedules', json={'command_id': 6, 'at_time': '07:00', 'days': 1}).get_json()
    client.post('/api/schedules', json={'command_id': 7, 'at_time': '07:00', 'days': 2})     # chỉ Thứ Ba
    client.post('/api/schedules', json={'command_id': 8, 'at_time': '07:01'})
    off = client.post('/api/schedules', json={'command_id': 9, 'at_time': '07:00'}).get_json()
    client.patch('/api/schedules/%d' % off['id'], json={'enabled': False})
    assert hub.run_due_schedules(now) == [mon['id']]
    assert hub.run_due_schedules(now + 30) == []          # không chạy lặp trong cùng phút
    time.sleep(0.6)
    h = client.get('/api/history?limit=1').get_json()[0]
    assert (h['source'], h['label'], h['text']) == ('schedule', 'Nguồn', 'Hẹn giờ 07:00')


# ---------- Khác ----------
def test_settings_retention(client):
    assert client.patch('/api/settings', json={'history_retention_days': 30}).get_json() == {'history_retention_days': 30}
    assert client.patch('/api/settings', json={'history_retention_days': -1}).status_code == 400


def test_unknown_api_is_json_404(client):
    r = client.get('/api/khong-co')
    assert r.status_code == 404 and r.get_json()['error'] == 'not_found'


def test_system(client):
    s = client.get('/api/system').get_json()
    assert s['db_schema'] == 4 and s['simulate'] is True
