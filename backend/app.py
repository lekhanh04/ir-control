"""Chạy bộ trung tâm: python app.py  →  mở http://localhost:8000"""
from irhub import create_app
from irhub.config import Config

app, hub = create_app()

if __name__ == '__main__':
    hub.start()
    mode = 'GIẢ LẬP (không cần phần cứng)' if Config.SIMULATE else 'THẬT (MQTT %s:%s, mắt thu GPIO %s)' % (Config.MQTT_HOST, Config.MQTT_PORT, Config.IR_GPIO)
    print('Bộ trung tâm IR · chế độ %s · http://localhost:%s' % (mode, Config.PORT))
    # threaded=True để luồng sự kiện SSE không chặn các request khác
    app.run(host=Config.HOST, port=Config.PORT, threaded=True, debug=False, use_reloader=False)
