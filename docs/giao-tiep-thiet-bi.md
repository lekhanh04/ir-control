# Giao tiếp giữa bộ trung tâm và thiết bị

Tài liệu này là "hợp đồng" để firmware ESP8266 và module giọng nói khớp với backend. Backend đọc/ghi đúng các topic và trường dưới đây (xem `backend/irhub/transport.py`, `voice.py`, `ir_receiver.py`).

Mọi payload là JSON UTF-8. Tiền tố topic mặc định `irhub` (đổi bằng `MQTT_PREFIX`).

## 1. ESP8266 Slave (bộ phát IR ở các phòng)

Mỗi phòng có một hoặc nhiều bộ phát (phòng rộng hoặc có vật che). Firmware không cần biết mình ở phòng nào: việc gán phòng và chọn bộ phát cho từng thiết bị làm trên giao diện, lưu ở Pi.

`<id>` là mã riêng của từng mạch, nên dùng chip ID: `esp-` + 6 ký tự hex của `ESP.getChipId()`, ví dụ `esp-a1f3c2`. Chỉ dùng chữ, số, `-`, `_`, tối đa 32 ký tự.

| Hướng | Topic | QoS | Retain | Payload |
|---|---|---|---|---|
| ESP → Pi | `irhub/slave/<id>/status` | 1 | **có** | `{"online": true, "ip": "192.168.1.51", "rssi": -54, "fw": "1.0.2"}` |
| ESP → Pi (LWT) | `irhub/slave/<id>/status` | 1 | **có** | `{"online": false}` |
| Pi → ESP | `irhub/slave/<id>/cmd` | 1 | không | xem 1.2 |
| ESP → Pi | `irhub/slave/<id>/ack` | 1 | không | `{"req": "a1b2c3d4", "ok": true}` hoặc `{"req": "...", "ok": false, "err": "bad_payload"}` |
| Pi → ESP | `irhub/slave/<id>/identify` | 0 | không | `{"seconds": 5}` → nháy LED trên mạch để người dùng nhận ra |

### 1.1 Trạng thái và phát hiện bộ phát mới

- Khi kết nối MQTT: đặt **Last Will** = `{"online":false}` (retained) trên topic status, rồi publish status `online:true` (retained).
- **Gửi lại status mỗi 30 giây** (kèm `rssi` mới). Backend coi bộ phát mất kết nối nếu quá 90 giây (`SLAVE_STALE_S`) không nhận được status.
- Bộ phát chưa có trong CSDL sẽ được tự thêm với trạng thái "Chưa gán phòng". Người dùng gán phòng trong giao diện: **Quản lý › Bộ phát ESP8266**. Firmware không cần biết mình ở phòng nào.

### 1.2 Lệnh phát IR (`cmd`)

Hai dạng, tương ứng hai kiểu lưu trong bảng `commands`:

```json
{"req": "a1b2c3d4", "type": "protocol", "protocol": "NEC", "value": "0x20DF10EF", "bits": 32}
```

```json
{"req": "a1b2c3d4", "type": "raw", "freq": 38, "data": [9000, 4500, 560, 1690, 560, 560, "...", 560]}
```

- `protocol`: hiện backend nhận dạng `NEC` và `SAMSUNG`. Phát bằng `irsend.sendNEC(value, bits)` / `irsend.sendSAMSUNG(value, bits)` của IRremoteESP8266.
- `value` là chuỗi hex, bit truyền đi đầu tiên là bit cao nhất, đúng quy ước của IRremoteESP8266. Đọc bằng `strtoull(value, nullptr, 16)`.
- `raw`: mảng thời gian (µs) xen kẽ mark/space, bắt đầu bằng mark. Phát bằng `irsend.sendRaw(buf, len, freq)`. Điều hòa thường thuộc dạng này, có thể dài 200–600 phần tử.
- Sau khi phát xong, **luôn gửi `ack` với đúng `req`**. Backend chờ ACK tối đa 3 giây (`ACK_TIMEOUT_S`). Không có ACK thì giao diện báo "Bộ phát không xác nhận".
- Mỗi bộ phát chỉ nhận một lệnh tại một thời điểm (backend tự xếp hàng).

**Lưu ý firmware:**
- PubSubClient mặc định chỉ nhận gói 256 byte. Lệnh RAW dài hơn nhiều, nên phải gọi `client.setBufferSize(8192)`.
- ArduinoJson: dùng `JsonDocument` đủ lớn (khoảng 12 KB cho 600 phần tử) và parse trực tiếp từ payload.

### 1.3 Khung firmware tham khảo (chưa biên dịch thử)

Chỉ cần sửa 3 chỗ: `TEN_WIFI`, `MAT_KHAU` và IP của Raspberry Pi. Mở Serial Monitor ở 115200 baud để xem mạch đang làm gì.

```cpp
// platformio.ini: lib_deps = crankyoldgit/IRremoteESP8266, knolleary/PubSubClient, bblanchon/ArduinoJson@^7
#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <IRremoteESP8266.h>
#include <IRsend.h>

const uint16_t IR_LED = 4;              // GPIO4 (D2) → transistor/MOSFET → LED IR 940 nm
IRsend irsend(IR_LED);
WiFiClient net; PubSubClient mqtt(net);
String id, tStatus, tCmd, tAck, tIdentify;
uint16_t rawBuf[1024];

void publishStatus(bool online) {
  JsonDocument d; d["online"] = online;
  if (online) { d["ip"] = WiFi.localIP().toString(); d["rssi"] = WiFi.RSSI(); d["fw"] = "1.0.0"; }
  char out[160]; size_t n = serializeJson(d, out);
  mqtt.publish(tStatus.c_str(), (uint8_t*)out, n, true);   // retained
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  JsonDocument d;
  if (deserializeJson(d, payload, len)) return;
  if (tIdentify == topic) {                 // nháy đèn trên mạch ~2,5 giây (đèn sáng ở mức thấp)
    Serial.println("Nhay den nhan biet");
    for (int i = 0; i < 10; i++) { digitalWrite(LED_BUILTIN, i % 2); delay(250); }
    digitalWrite(LED_BUILTIN, HIGH);
    return;
  }
  Serial.printf("Nhan lenh: %.*s\n", (int)len, (const char*)payload);
  bool ok = true;
  const char* type = d["type"] | "";
  if (!strcmp(type, "protocol")) {
    uint64_t v = strtoull(d["value"] | "0", nullptr, 16);
    uint16_t bits = d["bits"] | 32;
    const char* p = d["protocol"] | "";
    if (!strcmp(p, "NEC")) irsend.sendNEC(v, bits);
    else if (!strcmp(p, "SAMSUNG")) irsend.sendSAMSUNG(v, bits);
    else ok = false;
  } else if (!strcmp(type, "raw")) {
    JsonArray a = d["data"].as<JsonArray>();
    uint16_t n = 0;
    for (JsonVariant x : a) { if (n < 1024) rawBuf[n++] = x.as<uint16_t>(); }
    irsend.sendRaw(rawBuf, n, d["freq"] | 38);
  } else ok = false;

  JsonDocument ack; ack["req"] = d["req"]; ack["ok"] = ok; if (!ok) ack["err"] = "bad_payload";
  char out[96]; size_t m = serializeJson(ack, out);
  mqtt.publish(tAck.c_str(), (uint8_t*)out, m, false);
  Serial.println(ok ? "Da phat, gui ACK" : "Lenh khong hop le");
}

void connectMqtt() {
  while (!mqtt.connected()) {
    if (mqtt.connect(id.c_str(), /*user*/ nullptr, /*pass*/ nullptr, tStatus.c_str(), 1, true, "{\"online\":false}")) {
      mqtt.subscribe(tCmd.c_str(), 1);
      mqtt.subscribe(tIdentify.c_str(), 0);
      publishStatus(true);
      Serial.println("Da ket noi MQTT, ma bo phat: " + id);
    } else { Serial.printf("MQTT loi %d, thu lai sau 2 giay\n", mqtt.state()); delay(2000); }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT); digitalWrite(LED_BUILTIN, HIGH);
  irsend.begin();
  char buf[16]; snprintf(buf, sizeof buf, "esp-%06x", ESP.getChipId()); id = buf;
  tStatus = "irhub/slave/" + id + "/status"; tCmd = "irhub/slave/" + id + "/cmd";
  tAck = "irhub/slave/" + id + "/ack";       tIdentify = "irhub/slave/" + id + "/identify";
  WiFi.begin("TEN_WIFI", "MAT_KHAU");
  while (WiFi.status() != WL_CONNECTED) delay(300);
  Serial.println("Wi-Fi OK, IP: " + WiFi.localIP().toString());
  mqtt.setServer("192.168.1.10", 1883);    // IP của Raspberry Pi
  mqtt.setBufferSize(8192);
  mqtt.setCallback(onMessage);
}

unsigned long lastStatus = 0;
void loop() {
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();
  if (millis() - lastStatus > 30000) { lastStatus = millis(); publishStatus(true); }
}
```

## 2. Module giọng nói

Module tự nhận dạng câu nói (offline hoặc online tùy phần cứng) rồi **gửi chữ** lên Pi. Pi tự tìm phòng, thiết bị, nút rồi phát lệnh (`backend/irhub/voice.py`).

| Hướng | Topic | Retain | Payload |
|---|---|---|---|
| Module → Pi | `irhub/voice/status` | **có** (LWT `{"online":false}`) | `{"online": true}` |
| Module → Pi | `irhub/voice/listening` | không | `{}` khi bắt đầu nghe thấy tiếng nói (giao diện hiện "Đang nghe…") |
| Module → Pi | `irhub/voice/result` | không | `{"text": "bật tivi phòng khách"}` |
| Pi → Module | `irhub/voice/config` | **có** | `{"enabled": true, "sensitivity": "low" \| "mid" \| "high"}` |

- Nếu module chỉ nhận được một tập lệnh cố định (mã số), hãy đổi mã đó thành câu chữ tương ứng trước khi gửi `result`.
- Cách Pi hiểu câu: tên phòng + tên thiết bị (hoặc loại: "điều hòa", "tivi", "quạt", "máy chiếu") + hành động ("bật/tắt/mở" → nút Nguồn, "tăng âm lượng", "giảm nhiệt độ", "kênh tiếp", "tắt tiếng"…). Nút tự tạo được gọi theo tên ("mở Netflix").
- Thiếu tên phòng mà nhà có nhiều thiết bị cùng loại: dùng "phòng mặc định" trong **Quản lý › Giọng nói**; không có thì báo "Chưa hiểu lệnh".
- IR thường chỉ có một nút nguồn bật/tắt luân phiên, nên "bật" và "tắt" đều gửi nút Nguồn.

## 3. Mắt thu IR trên Raspberry Pi

- Nối chân OUT của VS1838B/HX1838B/TSOP vào GPIO 18 (BCM, đổi bằng `IR_GPIO`), VCC 3,3 V, GND.
- Cần dịch vụ pigpio: `sudo apt install pigpio python3-pigpio && sudo systemctl enable --now pigpiod`.
- Backend đo thời gian giữa các cạnh, coi khoảng lặng 20 ms là hết một khung, bỏ khung ngắn hơn 6 cạnh (nhiễu, mã lặp khi giữ nút).
- Mỗi lần học thu 3 khung, so sánh từng xung (lệch tối đa 25% hoặc 150 µs). Khớp từ 90% trở lên (`LEARN_MIN_MATCH`) thì lấy trung bình. Nhận dạng được NEC/SAMSUNG thì lưu giao thức, không thì lưu RAW.
- Mắt thu đã lọc sóng mang nên không đo được tần số. Mã RAW được gán 38 kHz, đúng với đa số remote.
