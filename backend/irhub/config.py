"""Cấu hình đọc từ biến môi trường hoặc file backend/.env (xem .env.example)."""
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)


def _load_dotenv(path):
    """Đọc file .env đơn giản (KEY=VALUE), không ghi đè biến đã có trong môi trường."""
    if not os.path.exists(path):
        return
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(os.path.join(BACKEND_DIR, '.env'))


def _bool(name, default):
    return os.getenv(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


class Config:
    HOST = os.getenv('IRHUB_HOST', '0.0.0.0')
    PORT = int(os.getenv('IRHUB_PORT', '8000'))
    DB_PATH = os.getenv('IRHUB_DB', os.path.join(BACKEND_DIR, 'data', 'irhub.db'))
    WEB_DIR = os.getenv('IRHUB_WEB', os.path.join(PROJECT_DIR, 'web'))

    # 1 = chạy trên máy tính không cần phần cứng: bộ phát ESP8266, mắt thu IR, module giọng nói đều giả lập.
    # 0 = chạy thật trên Raspberry Pi: MQTT tới ESP8266, mắt thu qua pigpio.
    SIMULATE = _bool('IRHUB_SIMULATE', True)
    SEED_DEMO = _bool('IRHUB_SEED_DEMO', SIMULATE)   # tạo dữ liệu mẫu khi CSDL trống

    MQTT_HOST = os.getenv('MQTT_HOST', 'localhost')
    MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))
    MQTT_USER = os.getenv('MQTT_USER', '')
    MQTT_PASS = os.getenv('MQTT_PASS', '')
    MQTT_PREFIX = os.getenv('MQTT_PREFIX', 'irhub')

    IR_GPIO = int(os.getenv('IR_GPIO', '18'))         # chân OUT của mắt thu VS1838B/TSOP (số BCM)

    ACK_TIMEOUT_S = float(os.getenv('ACK_TIMEOUT_S', '3'))
    SLAVE_STALE_S = int(os.getenv('SLAVE_STALE_S', '90'))   # quá lâu không có status → coi là mất kết nối
    LEARN_CAPTURES = int(os.getenv('LEARN_CAPTURES', '3'))
    LEARN_TIMEOUT_S = int(os.getenv('LEARN_TIMEOUT_S', '15'))
    LEARN_MIN_MATCH = int(os.getenv('LEARN_MIN_MATCH', '90'))  # % độ khớp tối thiểu giữa các lần thu

    VERSION = '1.1.0'
