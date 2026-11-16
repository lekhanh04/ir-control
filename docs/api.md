# REST API của bộ trung tâm

Gốc: `http://<ip-raspberry-pi>:8000/api`. Mọi body và kết quả là JSON. Lỗi trả về `{"error": "<mã>", "message": "<mô tả tiếng Việt>"}`.
Thời gian (`at`, `last_seen`, `last_run`) tính bằng mili giây Unix.

**Đăng nhập:** khi backend đặt `IRHUB_PIN`, mọi API (trừ `/auth`, `/login`, `/logout`) trả `401 {"error": "auth"}` cho tới khi đăng nhập. Đăng nhập thành công đặt cookie `irhub` (nhớ 1 năm); trình duyệt tự gửi cookie cho cả `/events` và `/backup`.

| Method | Đường dẫn | Body | Kết quả | Lỗi |
|---|---|---|---|---|
| GET | `/auth` | — | `{required, ok}` | — |
| POST | `/login` | `{pin}` | `{required, ok}` | 401 `bad_pin`, 429 `locked` (sai 5 lần → khóa 60 giây) |
| POST | `/logout` | — | `{required, ok}` | — |

| Method | Đường dẫn | Body / Query | Kết quả | Lỗi |
|---|---|---|---|---|
| GET | `/system` | — | `uptime_s, cpu_temp_c, disk_used_mb, disk_total_mb, db_size_kb, db_schema, mqtt, ir_receiver, version, simulate` | — |
| GET | `/events` | — | Server-Sent Events: `slave`, `history`, `voice` | — |
| GET | `/backup` | — | file `.db` (SQLite), bản sao tại thời điểm gọi | — |
| GET | `/backups` | — | `{keep, items: [{name, size_kb, at}]}` bản sao lưu trên Pi (tự động hằng ngày `irhub-YYYYMMDD.db`, và `irhub-truoc-khoi-phuc-*.db`), mới nhất trước | — |
| GET | `/backups/{name}` | — | tải file sao lưu đó | 404 |
| POST | `/restore` | multipart, trường `file` (file `.db`) **hoặc** JSON `{name}` (bản trên Pi) | `{ok, safety_backup}`. File được kiểm tra (`integrity_check`, đúng bảng, không mới hơn phần mềm), nâng cấp lên cấu trúc hiện tại; CSDL đang dùng được lưu thành `safety_backup` trước khi thay. Giữ nguyên khóa đăng nhập | 400 `bad_backup`, 404 |
| GET | `/settings` | — | `{history_retention_days}` | — |
| PATCH | `/settings` | `{history_retention_days}` (0 = giữ mãi, tối đa 3650) | như GET; xóa ngay lịch sử quá hạn | 400 `retention` |
| GET | `/device-types` | — | `[{code, label}]` theo thứ tự hiển thị (bảng `device_types`) | — |
| GET | `/rooms` | — | `[{id, name}]` | — |
| POST | `/rooms` | `{name}` | `{id, name}` | 400 `name`, 409 `exists` |
| PATCH | `/rooms/{id}` | `{name}` | `{id, name}` | 400, 409 `exists`, 404 |
| DELETE | `/rooms/{id}` | — | `{ok}` | 409 `not_empty`, 404 |
| GET | `/devices` | — | `[{id, room_id, type, name, brand, slave_id, command_count}]` | — |
| POST | `/devices` | `{name, type, room_id, brand?, slave_id?}` (`room_id` phải là số nguyên) | thiết bị | 400 `invalid`, 409 `name_exists` |
| PATCH | `/devices/{id}` | trường cần đổi | thiết bị (đổi phòng mà không gửi `slave_id` → `slave_id` về `null`) | 400, 404, 409 `name_exists` |
| DELETE | `/devices/{id}` | — | `{ok}` (xóa kèm nút, giữ lịch sử) | 404 |
| GET | `/devices/{id}/commands` | — | `[{id, key, label, kind, protocol, value, address, command, bits, carrier_khz, raw_len, match_pct}]` | — |
| PATCH | `/commands/{id}` | `{label}` | `{id, label}` | 400, 404, 409 `label_exists` |
| DELETE | `/commands/{id}` | — | `{ok}` | 404 |
| POST | `/send` | `{command_id}` | `{status:"ok", latency_ms, history_id}` sau khi có ACK | 503 `slave_offline`, 504 `no_ack`, 502 `slave_error`, 429 `busy`, 404 |
| POST | `/learn` | `{device_id, key, force?}` | `{session, captures, timeout_s}`. `force: true` hủy phiên của người khác đang chờ tín hiệu | 404, 400 `key`, 409 `receiver_busy`, 503 `ir_receiver` |
| GET | `/learn/{session}` | — | `{state: waiting\|done\|mismatch\|timeout, count, captures, match_pct?, decoded?, raw_len?, carrier_khz?}` | 404 |
| POST | `/learn/{session}/test` | — | `{status:"ok", latency_ms}` (phát thử qua bộ phát của thiết bị) | như `/send`, 409 `not_ready` |
| POST | `/learn/{session}/save` | `{label, replace?}` | `{id, key, label}` | 409 `exists` (nút đã có mã), 409 `label_exists` (trùng tên nút khác), 409 `not_ready` |
| DELETE | `/learn/{session}` | — | `{ok}` | — |
| GET | `/slaves` | — | `[{id, name, room_id, online, ip, rssi, fw, last_seen}]` | — |
| PATCH | `/slaves/{id}` | `{room_id \| null, name?}` | bộ phát. Một phòng có thể có nhiều bộ; thiết bị phòng khác đang gán riêng bộ này về `slave_id = null` | 400, 404 |
| DELETE | `/slaves/{id}` | — | `{ok}` (chỉ bộ đang mất kết nối) | 409 `online`, 404 |
| POST | `/slaves/{id}/identify` | — | `{ok}` | 503, 404 |
| GET | `/scenes` | — | `[{id, name, steps: [{command_id, delay_ms, key, label, device_id, device_name, room_name}]}]` | — |
| POST | `/scenes` | `{name, steps: [{command_id, delay_ms?}]}` (1–30 bước, chờ 0–60000 ms, mặc định 500) | ngữ cảnh | 400 `name`/`steps`, 409 `exists` |
| PUT | `/scenes/{id}` | như POST (thay toàn bộ) | ngữ cảnh | 400, 404, 409 |
| DELETE | `/scenes/{id}` | — | `{ok}` (xóa kèm hẹn giờ dùng nó) | 404 |
| POST | `/scenes/{id}/run` | — | `{scene_id, name, status: ok\|partial\|error, results: [{command_id, label, device_name, status, latency_ms}]}` sau khi chạy xong mọi bước | 404 |
| GET | `/schedules` | — | `[{id, scene_id, command_id, at_time, days, enabled, last_run, scene_steps, scene_name, command_label, device_id, device_name, room_name}]` theo giờ. `scene_steps` = số bước còn lại của ngữ cảnh; hẹn giờ của ngữ cảnh 0 bước tự tắt khi đến giờ | — |
| POST | `/schedules` | `{scene_id \| command_id, at_time: "HH:MM", days?: 1–127, enabled?}` | hẹn giờ | 400 `invalid` |
| PATCH | `/schedules/{id}` | trường cần đổi | hẹn giờ | 400, 404 |
| DELETE | `/schedules/{id}` | — | `{ok}` | 404 |
| GET | `/history` | `?limit=60` | `[{id, at, device_id, room_name, device_name, key, label, source, text, slave_id, status, latency_ms}]` mới nhất trước. `source`: `web, voice, scene, schedule` (`text` = câu nói / tên ngữ cảnh / "Hẹn giờ HH:MM"). `status`: `ok, offline, timeout, error, not_understood` (câu nói không hiểu: chỉ có `source=voice`, `text`) | — |
| GET | `/voice` | — | `{enabled, sensitivity, default_room_id, module: ok\|missing}` | — |
| POST | `/voice` | `{enabled?, sensitivity?, default_room_id?}` (`default_room_id`: id phòng có thật hoặc `null`) | như GET | 400 `sensitivity`, 400 `default_room` |

`decoded` = `{protocol, value, address, command, bits}` hoặc `null` (lưu RAW). `protocol`: `NEC`, `SAMSUNG`, `SONY`, `PANASONIC`.

**Hẹn giờ:** `days` là mặt nạ bit, bit 0 = Thứ Hai … bit 6 = Chủ nhật (31 = Thứ 2–6, 96 = cuối tuần, 127 = mọi ngày). Giờ theo đồng hồ của Raspberry Pi; kiểm tra mỗi 15 giây, mỗi hẹn giờ chạy tối đa một lần mỗi phút.

**Chọn bộ phát khi gửi lệnh:** `devices.slave_id` nếu có; nếu không, bộ phát trong phòng của thiết bị, ưu tiên bộ đang hoạt động rồi bộ thấy gần nhất.

**So trùng tên** (phòng, thiết bị trong phòng, nút trong thiết bị) không phân biệt hoa thường, kể cả chữ có dấu.

Mã nút chuẩn (`key`): `power, source, temp_up, temp_down, mode, fan_speed, swing, vol_up, vol_down, ch_up, ch_down, up, down, left, right, ok, back, home, mute, speed, cool, timer, menu, freeze, blank`. Nút tự tạo: `custom_1`, `custom_2`, …

## Sự kiện SSE (`GET /events`)

| Sự kiện | Dữ liệu | Khi nào |
|---|---|---|
| `slave` | một bộ phát (như `/slaves`) | bộ phát kết nối, mất kết nối, gửi status |
| `history` | một dòng lịch sử | sau mỗi lệnh gửi (web hoặc giọng nói) và mỗi câu nói không hiểu |
| `voice` | `{state:"listening"}` hoặc `{state:"result", text, ok, device_id?, key?, label?, status?}` | module giọng nói nghe / có kết quả |

## Chỉ có ở chế độ giả lập (`IRHUB_SIMULATE=1`)

| Method | Đường dẫn | Body | Tác dụng |
|---|---|---|---|
| POST | `/dev/voice` | `{text}` | giả lập module giọng nói nghe được câu này |
| POST | `/dev/slaves/{id}` | `{online}` | bật/tắt một bộ phát giả |
| POST | `/dev/sim` | `{ir: ok\|mismatch\|timeout, ack: ok\|fail, voice_module: true\|false}` | đổi hành vi mắt thu, ACK, module giọng nói |

Xem ví dụ chạy được trong `dev.http`.
