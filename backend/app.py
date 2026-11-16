"""Chạy bộ trung tâm: python app.py  →  mở http://localhost:8000

Dùng waitress (server cho chạy lâu dài) nếu đã cài; nếu chưa thì dùng server phát triển của Flask.
"""
from irhub import create_app
from irhub.config import Config

app, hub = create_app()

# Mỗi trình duyệt đang mở giữ một kết nối sự kiện (SSE) lâu dài, nên cần dư luồng cho các request khác.
THREADS = 24

if __name__ == '__main__':
    hub.start()
    mode = 'GIẢ LẬP (không cần phần cứng)' if Config.SIMULATE else 'THẬT (MQTT %s:%s, mắt thu GPIO %s)' % (Config.MQTT_HOST, Config.MQTT_PORT, Config.IR_GPIO)
    pin = 'cần mã PIN' if Config.PIN else 'không cần đăng nhập'
    print('Bộ trung tâm IR · chế độ %s · %s · http://localhost:%s' % (mode, pin, Config.PORT))
    try:
        from waitress import serve
    except ImportError:
        print('(Chưa cài waitress, dùng server phát triển của Flask. Cài: pip install waitress)')
        # threaded=True để luồng sự kiện SSE không chặn các request khác
        app.run(host=Config.HOST, port=Config.PORT, threaded=True, debug=False, use_reloader=False)
    else:
        serve(app, host=Config.HOST, port=Config.PORT, threads=THREADS, ident='irhub')
