# REST API của bộ trung tâm

Gốc: `http://<ip-raspberry-pi>:8000/api`. Mọi body và kết quả là JSON. Lỗi trả về `{"error": "<mã>", "message": "<mô tả tiếng Việt>"}`.
Thời gian (`at`, `last_seen`) tính bằng mili giây Unix.

| Method | Đường dẫn | Body / Query | Kết quả | Lỗi |
|---|---|---|---|---|
| GET | `/system` | — | `uptime_s, cpu_temp_c, disk_used_mb, disk_total_mb, db_size_kb, db_schema, mqtt, ir_receiver, version, simulate` | — |
| GET | `/events` | — | Server-Sent Events: `slave`, `history`, `voice` | — |
| GET | `/backup` | — | file `.db` (SQLite) | — |
| GET | `/settings` | — | `{history_retention_days}` | — |
| PATCH | `/settings` | `{history_retention_days}` (0 = giữ mãi, tối đa 3650) | như GET; xóa ngay lịch sử quá hạn | 400 `retention` |
| GET | `/device-types` | — | `[{code, label}]` theo thứ tự hiển thị (bảng `device_types`) | — |
| GET | `/rooms` | — | `[{id, name}]` | — |
| POST | `/rooms` | `{name}` | `{id, name}` | 400 `name`, 409 `exists` |
| PATCH | `/rooms/{id}` | `{name}` | `{id, name}` | 400, 409 `exists`, 404 |
| DELETE | `/rooms/{id}` | — | `{ok}` | 409 `not_empty`, 404 |
| GET | `/devices` | — | `[{id, room_id, type, name, brand, slave_id, command_count}]` | — |
| POST | `/devices` | `{name, type, room_id, brand?, slave_id?}` | thiết bị | 400 `invalid`, 409 `name_exists` |
| PATCH | `/devices/{id}` | trường cần đổi | thiết bị (đổi phòng mà không gửi `slave_id` → `slave_id` về `null`) | 400, 404, 409 `name_exists` |
| DELETE | `/devices/{id}` | — | `{ok}` (xóa kèm nút, giữ lịch sử) | 404 |
| GET | `/devices/{id}/commands` | — | `[{id, key, label, kind, protocol, value, address, command, bits, carrier_khz, raw_len, match_pct}]` | — |
| PATCH | `/commands/{id}` | `{label}` | `{id, label}` | 400, 404, 409 `label_exists` |
| DELETE | `/commands/{id}` | — | `{ok}` | 404 |
| POST | `/send` | `{command_id}` | `{status:"ok", latency_ms, history_id}` sau khi có ACK | 503 `slave_offline`, 504 `no_ack`, 502 `slave_error`, 429 `busy`, 404 |
| POST | `/learn` | `{device_id, key}` | `{session, captures, timeout_s}` | 404, 400 `key`, 503 `ir_receiver` |
| GET | `/learn/{session}` | — | `{state: waiting\|done\|mismatch\|timeout, count, captures, match_pct?, decoded?, raw_len?, carrier_khz?}` | 404 |
| POST | `/learn/{session}/test` | — | `{status:"ok", latency_ms}` (phát thử qua bộ phát của thiết bị) | như `/send`, 409 `not_ready` |
| POST | `/learn/{session}/save` | `{label, replace?}` | `{id, key, label}` | 409 `exists` (nút đã có mã), 409 `label_exists` (trùng tên nút khác), 409 `not_ready` |
| DELETE | `/learn/{session}` | — | `{ok}` | — |
| GET | `/slaves` | — | `[{id, name, room_id, online, ip, rssi, fw, last_seen}]` | — |
| PATCH | `/slaves/{id}` | `{room_id \| null, name?}` | bộ phát. Một phòng có thể có nhiều bộ; thiết bị phòng khác đang gán riêng bộ này về `slave_id = null` | 400, 404 |
| DELETE | `/slaves/{id}` | — | `{ok}` (chỉ bộ đang mất kết nối) | 409 `online`, 404 |
| POST | `/slaves/{id}/identify` | — | `{ok}` | 503, 404 |
| GET | `/history` | `?limit=60` | `[{id, at, device_id, room_name, device_name, key, label, source, text, slave_id, status, latency_ms}]` mới nhất trước. `status`: `ok, offline, timeout, error, not_understood` (câu nói không hiểu: chỉ có `source=voice`, `text`) | — |
| GET | `/voice` | — | `{enabled, sensitivity, default_room_id, module: ok\|missing}` | — |
| POST | `/voice` | `{enabled?, sensitivity?, default_room_id?}` | như GET | 400 |

`decoded` = `{protocol, value, address, command, bits}` hoặc `null` (lưu RAW).

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
