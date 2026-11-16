-- Cơ sở dữ liệu SQLite của bộ trung tâm (Raspberry Pi 4B) – phiên bản cấu trúc 4
-- Phòng → Thiết bị → Lệnh (mã IR); bộ phát ESP8266 theo phòng; ngữ cảnh, hẹn giờ; lịch sử điều khiển.
-- Thời gian *_at, last_seen tính bằng mili giây Unix (UTC).
--
-- File này chỉ dùng khi tạo CSDL MỚI. CSDL đã có được nâng cấp bằng migrations.py
-- (đánh số qua PRAGMA user_version). Sửa cấu trúc: sửa file này VÀ thêm một bước nâng cấp.

CREATE TABLE IF NOT EXISTS rooms (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT    NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(name)) BETWEEN 1 AND 24),
  created_at  INTEGER NOT NULL
);

-- Loại thiết bị. Thêm loại mới chỉ cần thêm một dòng (bố cục remote khai báo trong web/js/types.js).
CREATE TABLE IF NOT EXISTS device_types (
  code        TEXT    PRIMARY KEY CHECK (code GLOB '[a-z]*' AND length(code) BETWEEN 2 AND 20),
  label       TEXT    NOT NULL,
  sort_order  INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO device_types (code, label, sort_order) VALUES
  ('ac', 'Điều hòa', 1), ('tv', 'Tivi', 2), ('fan', 'Quạt điều hòa', 3), ('projector', 'Máy chiếu', 4), ('other', 'Thiết bị khác', 99);

-- Bộ phát ESP8266. id = mã chip do firmware tự gửi lên (vd "esp-a1f3c2").
-- Một phòng có thể có nhiều bộ phát (phòng lớn, thiết bị ở nhiều hướng). room_id NULL = chưa gán phòng.
CREATE TABLE IF NOT EXISTS slaves (
  id          TEXT    PRIMARY KEY,
  name        TEXT    NOT NULL,
  room_id     INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
  online      INTEGER NOT NULL DEFAULT 0,
  ip          TEXT,
  rssi        INTEGER,
  fw          TEXT,
  last_seen   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_slaves_room ON slaves (room_id);

-- slave_id: bộ phát riêng của thiết bị. NULL = tự chọn bộ phát của phòng (ưu tiên bộ đang hoạt động).
-- Tên thiết bị không trùng trong cùng một phòng (để lệnh giọng nói xác định đúng thiết bị).
CREATE TABLE IF NOT EXISTS devices (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id     INTEGER NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
  type        TEXT    NOT NULL REFERENCES device_types(code) ON UPDATE CASCADE ON DELETE RESTRICT,
  name        TEXT    NOT NULL COLLATE NOCASE CHECK (length(trim(name)) BETWEEN 1 AND 30),
  brand       TEXT    NOT NULL DEFAULT '',
  slave_id    TEXT    REFERENCES slaves(id) ON DELETE SET NULL,
  created_at  INTEGER NOT NULL,
  UNIQUE (room_id, name)
);
CREATE INDEX IF NOT EXISTS idx_devices_slave ON devices (slave_id);
CREATE INDEX IF NOT EXISTS idx_devices_type ON devices (type);

-- Một nút trên remote của thiết bị.
-- kind = 'protocol': nhận dạng được giao thức → protocol, value (mã đầy đủ để phát), address, command, bits.
-- kind = 'raw': không nhận dạng được → raw = mảng JSON thời gian xung (µs), bắt đầu bằng mark.
-- Mã nút (key) và tên nút (label) đều không trùng trong cùng một thiết bị.
CREATE TABLE IF NOT EXISTS commands (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  key         TEXT    NOT NULL CHECK (key GLOB '[a-z0-9_]*' AND length(key) BETWEEN 1 AND 20),
  label       TEXT    NOT NULL COLLATE NOCASE CHECK (length(trim(label)) BETWEEN 1 AND 20),
  kind        TEXT    NOT NULL CHECK (kind IN ('protocol', 'raw')),
  protocol    TEXT,
  value       TEXT,                          -- hex, vd "0x20DF10EF"
  address     TEXT,
  command     TEXT,
  bits        INTEGER,
  carrier_khz INTEGER NOT NULL DEFAULT 38,
  raw         TEXT /*JSON_CHECK*/ CHECK (raw IS NULL OR json_valid(raw)) /*END_JSON_CHECK*/,
  match_pct   INTEGER,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL,
  UNIQUE (device_id, key),
  UNIQUE (device_id, label),
  CHECK ((kind = 'protocol' AND protocol IS NOT NULL AND value IS NOT NULL) OR (kind = 'raw' AND raw IS NOT NULL))
);

-- Lịch sử điều khiển. Lưu bản sao tên phòng/thiết bị/nút để vẫn đọc được khi đã xóa hay đổi tên.
-- status 'not_understood': câu nói không xác định được thiết bị/nút (để đánh giá nhận dạng giọng nói).
-- Bản ghi cũ hơn settings['history.retention_days'] ngày được tự động xóa.
CREATE TABLE IF NOT EXISTS history (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  at          INTEGER NOT NULL,
  device_id   INTEGER REFERENCES devices(id) ON DELETE SET NULL,
  room_name   TEXT,
  device_name TEXT,
  key         TEXT,
  label       TEXT,
  source      TEXT    NOT NULL CHECK (source IN ('web', 'voice', 'scene', 'schedule')),
  text        TEXT,                          -- câu nói (voice), tên ngữ cảnh (scene), mô tả hẹn giờ (schedule)
  slave_id    TEXT,
  status      TEXT    NOT NULL CHECK (status IN ('ok', 'timeout', 'offline', 'error', 'not_understood')),
  latency_ms  INTEGER,
  CHECK (status = 'not_understood' OR device_name IS NOT NULL),
  CHECK (status <> 'not_understood' OR (source = 'voice' AND text IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_history_at ON history (at DESC);
CREATE INDEX IF NOT EXISTS idx_history_device ON history (device_id, at DESC);

-- Ngữ cảnh (macro): bấm một lần, phát lần lượt nhiều nút, vd "Đi ngủ" = tắt tivi + tắt đèn + bật quạt.
CREATE TABLE IF NOT EXISTS scenes (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT    NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(name)) BETWEEN 1 AND 30),
  created_at  INTEGER NOT NULL
);

-- Các bước của ngữ cảnh, phát theo position tăng dần; chờ delay_ms sau mỗi bước.
-- Xóa nút (hoặc thiết bị) thì bước tương ứng tự mất.
CREATE TABLE IF NOT EXISTS scene_steps (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  scene_id    INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
  position    INTEGER NOT NULL,
  command_id  INTEGER NOT NULL REFERENCES commands(id) ON DELETE CASCADE,
  delay_ms    INTEGER NOT NULL DEFAULT 500 CHECK (delay_ms BETWEEN 0 AND 60000)
);
CREATE INDEX IF NOT EXISTS idx_scene_steps ON scene_steps (scene_id, position);

-- Hẹn giờ: chạy một ngữ cảnh HOẶC một nút vào giờ at_time (giờ địa phương của Pi) các ngày trong days.
-- days: bit 0 = Thứ Hai … bit 6 = Chủ nhật (127 = mọi ngày). last_run chống chạy lặp trong cùng một phút.
CREATE TABLE IF NOT EXISTS schedules (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  scene_id    INTEGER REFERENCES scenes(id) ON DELETE CASCADE,
  command_id  INTEGER REFERENCES commands(id) ON DELETE CASCADE,
  at_time     TEXT    NOT NULL CHECK (at_time GLOB '[0-2][0-9]:[0-5][0-9]' AND at_time < '24:00'),
  days        INTEGER NOT NULL DEFAULT 127 CHECK (days BETWEEN 1 AND 127),
  enabled     INTEGER NOT NULL DEFAULT 1,
  last_run    INTEGER,
  created_at  INTEGER NOT NULL,
  CHECK ((scene_id IS NULL) <> (command_id IS NULL))
);

-- Cài đặt dạng khóa–giá trị
CREATE TABLE IF NOT EXISTS settings (
  key         TEXT PRIMARY KEY,
  value       TEXT NOT NULL
);
INSERT OR IGNORE INTO settings (key, value) VALUES ('history.retention_days', '90');
