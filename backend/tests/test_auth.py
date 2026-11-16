import pytest


@pytest.fixture
def pin_client(make_app):
    app, _ = make_app(PIN='2468')
    return app.test_client()


def test_no_pin_means_open(client):
    assert client.get('/api/auth').get_json() == {'required': False, 'ok': True}
    assert client.get('/api/rooms').status_code == 200


def test_api_requires_login(pin_client):
    assert pin_client.get('/api/auth').get_json() == {'required': True, 'ok': False}
    for path in ('/api/rooms', '/api/system', '/api/backup', '/api/events', '/api/khong-co'):
        r = pin_client.get(path)
        assert r.status_code == 401 and r.get_json()['error'] == 'auth', path
    assert pin_client.post('/api/dev/voice', json={'text': 'bật tivi'}).status_code == 401


def test_static_page_is_public(pin_client):
    assert pin_client.get('/').status_code == 200


def test_login_logout(pin_client):
    assert pin_client.post('/api/login', json={'pin': '0000'}).get_json()['error'] == 'bad_pin'
    assert pin_client.post('/api/login', json={'pin': ' 2468 '}).get_json()['ok'] is True
    assert pin_client.get('/api/rooms').status_code == 200
    pin_client.post('/api/logout')
    assert pin_client.get('/api/rooms').status_code == 401


def test_lockout_after_five_wrong(pin_client):
    for _ in range(5):
        assert pin_client.post('/api/login', json={'pin': '1111'}).status_code == 401
    r = pin_client.post('/api/login', json={'pin': '2468'})     # đúng nhưng đang bị khóa
    assert r.status_code == 429 and r.get_json()['error'] == 'locked'


def test_changing_pin_logs_everyone_out(make_app, tmp_path):
    app, _ = make_app(PIN='2468')
    c = app.test_client()
    c.post('/api/login', json={'pin': '2468'})
    cookie = c.get_cookie('irhub')
    assert cookie
    app2, _ = make_app(PIN='1357', SEED_DEMO=False)        # cùng CSDL (cùng khóa bí mật), PIN mới
    c2 = app2.test_client()
    c2.set_cookie('irhub', cookie.value)
    assert c2.get('/api/rooms').status_code == 401
