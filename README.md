# Hệ thống điều khiển hồng ngoại – Web + Backend

Bộ trung tâm chạy trên **Raspberry Pi 4B**: web server Flask (chạy bằng waitress), REST API, SQLite, MQTT tới các **ESP8266** phát IR ở từng phòng, mắt thu IR trên GPIO để học mã, nhận lệnh từ module giọng nói. Có ngữ cảnh (một chạm phát nhiều nút), hẹn giờ, đăng nhập bằng mã PIN, cài được lên màn hình điện thoại.

```
ir-control/
├─ backend/                  Python (Flask)
│  ├─ app.py                 chạy: python app.py
│  ├─ requirements.txt       (requirements-dev.txt: thêm pytest)
│  ├─ .env.example           cấu hình (copy thành .env)
│  ├─ irhub/
│  │  ├─ config.py           biến cấu hình
│  │  ├─ schema.sql          cấu trúc CSDL SQLite (phiên bản mới nhất)
│  │  ├─ migrations.py       tự nâng cấp file CSDL cũ lên phiên bản mới, không mất dữ liệu
│  │  ├─ db.py               truy cập SQLite (WAL, synchronous=NORMAL)
│  │  ├─ backup.py           sao lưu tự động hằng ngày, kiểm tra và khôi phục file sao lưu
│  │  ├─ api.py              REST API (+ API giả lập /api/dev)
│  │  ├─ auth.py             đăng nhập bằng mã PIN (IRHUB_PIN)
│  │  ├─ hub.py              điều phối: gửi lệnh, chờ ACK, ghi lịch sử, theo dõi bộ phát, ngữ cảnh, hẹn giờ
│  │  ├─ transport.py        MQTT tới ESP8266 / module giọng nói (và bản giả lập)
│  │  ├─ ir_receiver.py      mắt thu IR qua pigpio (và bản giả lập)
│  │  ├─ ir_decode.py        so sánh nhiều lần thu, nhận dạng NEC/SAMSUNG/SONY/PANASONIC, còn lại RAW
│  │  ├─ learn.py            phiên học mã
│  │  ├─ voice.py            hiểu câu nói (có dấu hoặc không) → phòng/thiết bị/nút hoặc ngữ cảnh
│  │  ├─ events.py           đẩy sự kiện lên web (SSE)
│  │  └─ seed.py             dữ liệu mẫu cho chế độ giả lập
│  ├─ tests/                 kiểm thử tự động (pytest)
│  └─ tools/fake_esp.py      ESP8266 giả qua MQTT thật (thử khi chưa có mạch)
├─ web/                      giao diện (HTML/CSS/JS thuần, không cần build)
│  ├─ index.html, manifest.webmanifest, icons/   (PWA: thêm vào màn hình chính)
│  ├─ css/style.css
│  └─ js/
│     ├─ main.js             khởi động, đăng ký trang, SSE
│     ├─ api.js, state.js, router.js, util.js, types.js
│     └─ pages/              home, remote, learn, history, manage, device-form, slaves, system, voice, scenes, schedules
├─ docs/
│  ├─ api.md                 danh sách REST API
│  └─ giao-tiep-thiet-bi.md  MQTT topic/payload cho ESP8266 và module giọng nói, mắt thu IR
├─ deploy/                   chạy tự động trên Raspberry Pi (systemd, Mosquitto)
└─ dev.http                  gọi thử API ngay trong VS Code
```

## Chạy trên máy tính (không cần phần cứng)

Cần Python 3.9 trở lên.

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Mở <http://localhost:8000>. Mặc định chạy **chế độ giả lập** (`IRHUB_SIMULATE=1`):
- Có sẵn 4 bộ phát ESP8266 giả: 3 bộ đã gán phòng (1 bộ mất kết nối) và 1 bộ mới chưa gán.
- Mắt thu IR giả: khi học mã, nó tự "bấm" 3 lần.
- Có dữ liệu mẫu: 3 phòng, 5 thiết bị.

Muốn thử giọng nói hoặc lỗi thiết bị thì mở `dev.http` và bấm **Send Request** (cần extension REST Client).

Muốn thử đăng nhập: đặt `IRHUB_PIN=1234` trong `backend/.env` rồi chạy lại.

### Kiểm thử tự động

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
```

Gồm: nhận dạng giao thức IR, hiểu câu nói (kể cả trường hợp ACK đi qua cùng luồng MQTT), toàn bộ REST API, học mã, ngữ cảnh, hẹn giờ, đăng nhập PIN, nâng cấp CSDL từ bản cũ. Nên chạy trước mỗi lần chép code lên Pi.

Trong VS Code: mở thư mục `ir-control`, nhấn **F5** và chọn "Backend (giả lập)". Breakpoint đặt được trong mọi file Python.

Dữ liệu nằm ở `backend/data/irhub.db` (bản sao lưu tự động ở `backend/data/backups/`). Xóa thư mục `data` để làm lại từ đầu.

## Chạy thật trên Raspberry Pi

```bash
sudo apt install mosquitto pigpio python3-pigpio python3-venv
sudo systemctl enable --now mosquitto pigpiod
sudo mosquitto_passwd -c /etc/mosquitto/passwd irhub      # đặt mật khẩu MQTT
sudo chown mosquitto: /etc/mosquitto/passwd && sudo chmod 600 /etc/mosquitto/passwd
sudo cp deploy/mosquitto-irhub.conf /etc/mosquitto/conf.d/ && sudo systemctl restart mosquitto

cd ~/ir-control/backend
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env        # sửa IRHUB_SIMULATE=0, IRHUB_PIN, MQTT_USER/MQTT_PASS, IR_GPIO, ...
python app.py               # thử tay; xong thì cài dịch vụ:
sudo cp ../deploy/irhub.service /etc/systemd/system/ && sudo systemctl enable --now irhub
```

Điện thoại cùng Wi-Fi mở `http://<ip-của-pi>:8000`, nhập mã PIN (nếu đã đặt `IRHUB_PIN`).

**Thêm vào màn hình chính:** Safari (iPhone) → Chia sẻ → *Thêm vào MH chính*; Chrome (Android) → menu ⋮ → *Thêm vào màn hình chính*. Trang có biểu tượng và tên riêng. Lưu ý: muốn mở toàn màn hình như ứng dụng thật, trình duyệt yêu cầu HTTPS, mà trong mạng nhà Pi chạy HTTP, nên Android có thể chỉ tạo lối tắt mở trong trình duyệt.

Firmware ESP8266 và module giọng nói phải theo đúng topic/payload trong [`docs/giao-tiep-thiet-bi.md`](docs/giao-tiep-thiet-bi.md).

**Thử MQTT trước khi có mạch:** chạy backend với `IRHUB_SIMULATE=0`, rồi mở một terminal khác chạy `python tools/fake_esp.py esp-test01` (thêm `--user irhub --password ...` nếu Mosquitto bắt buộc đăng nhập). Bộ phát giả sẽ hiện ở **Quản lý › Bộ phát** và trả ACK như mạch thật. Riêng mắt thu IR vẫn cần Raspberry Pi.

## Luồng dữ liệu chính

1. **Điều khiển:** giao diện gọi `POST /api/send {command_id}`. Pi tra mã trong SQLite, chọn bộ phát (bộ gán riêng cho thiết bị, nếu không thì bộ đang hoạt động trong phòng), publish `irhub/slave/<id>/cmd`, chờ `.../ack` tối đa 3 giây, ghi `history` rồi trả kết quả. Giao diện hiển thị theo ACK thật.
2. **Học mã:** `POST /api/learn` mở phiên. Mắt thu trên Pi thu 3 lần, so sánh, nhận dạng giao thức hoặc lưu RAW. Sau đó người dùng phát thử qua ESP8266 (`/learn/{s}/test`) rồi lưu (`/learn/{s}/save`).
3. **Giọng nói:** module publish `irhub/voice/result {text}`. Pi đưa câu vào hàng đợi (không xử lý ngay trong luồng MQTT, để ACK của ESP8266 về kịp), hiểu câu, gửi lệnh như bước 1 hoặc chạy ngữ cảnh, đẩy sự kiện `voice` qua SSE để giao diện hiện kết quả. Câu không hiểu được ghi vào lịch sử với trạng thái `not_understood` để xem lại và bổ sung từ khóa.
4. **Bộ phát:** ESP8266 publish status 30 giây/lần (retained, có LWT). Pi cập nhật bảng `slaves` và đẩy sự kiện `slave`. Bộ phát mới tự xuất hiện để gán phòng. Một phòng có thể có nhiều bộ phát (phòng rộng, có vật che).
5. **Ngữ cảnh:** `POST /api/scenes/{id}/run` phát lần lượt từng nút (như bước 1), chờ `delay_ms` giữa các bước. Gọi từ màn chính, bằng giọng nói theo tên, hoặc từ hẹn giờ.
6. **Hẹn giờ:** một luồng nền kiểm tra mỗi 15 giây; đến giờ (theo đồng hồ Pi) thì chạy ngữ cảnh hoặc nút, ghi lịch sử với nguồn `schedule`.

Trên remote, **giữ** nút âm lượng/kênh/nhiệt độ/mũi tên để gửi lặp liên tục.

## Thêm loại thiết bị hoặc nút mới

- **Loại thiết bị:** thêm một dòng vào bảng `device_types`, ví dụ trong DB Browser for SQLite:
  `INSERT INTO device_types (code, label, sort_order) VALUES ('speaker', 'Loa', 5);`
  Khởi động lại backend là giao diện có loại mới (dùng bố cục remote "Thiết bị khác"). Muốn remote có bố cục riêng thì thêm mục `speaker` vào `TYPES` trong `web/js/types.js`.
- **Nút chuẩn của một loại:** thêm `key` vào `groups` của loại đó và tên hiển thị vào `KEY_LABEL`. Backend không cần sửa.
- **Câu lệnh giọng nói:** sửa `KEY_RULES` và `TYPE_WORDS` trong `backend/irhub/voice.py`.

## Cơ sở dữ liệu và nâng cấp phiên bản

- File CSDL: `backend/data/irhub.db`. Phiên bản lược đồ lưu trong `PRAGMA user_version` (hiện tại **4**), xem ở trang **Bộ trung tâm**.
- **Sao lưu tự động:** mỗi ngày một bản `backend/data/backups/irhub-YYYYMMDD.db`, giữ 7 bản (`IRHUB_BACKUP_KEEP`). Các bản này nằm cùng thẻ nhớ: cứu được khi file CSDL hỏng hay lỡ xóa nhầm, nhưng không cứu được khi hỏng cả thẻ, nên thỉnh thoảng hãy bấm **Tải bản sao lưu** ở trang **Bộ trung tâm** để cất về máy.
- **Khôi phục:** trang **Bộ trung tâm** → chọn một bản tự động hoặc tải file `.db` lên. File được kiểm tra và nâng cấp lên cấu trúc hiện tại; dữ liệu đang dùng được tự lưu thành `irhub-truoc-khoi-phuc-<thời gian>.db` trước khi thay, nên khôi phục nhầm vẫn quay lại được.
- **Đỡ hao thẻ nhớ:** CSDL chạy WAL với `synchronous=NORMAL`; status 30 giây/lần của bộ phát chỉ cập nhật bộ nhớ, chỉ ghi xuống thẻ khi có thay đổi (trạng thái, IP, firmware) hoặc 10 phút/lần (`SLAVE_DB_REFRESH_S`).
- Khi khởi động, `migrations.py` kiểm tra phiên bản. Nếu file cũ hơn, nó **tự sao lưu** thành `irhub.db.bak-v1-<ngày giờ>` rồi nâng cấp trong một giao dịch: lỗi giữa chừng thì quay lại nguyên trạng.
- Phiên bản 2 so với 1:
  - Một phòng có nhiều bộ phát; thiết bị có thể gán riêng một bộ (`devices.slave_id`, để trống = tự chọn).
  - Bảng `device_types` thay cho danh sách cố định.
  - Tên thiết bị không trùng trong một phòng, tên nút không trùng trong một thiết bị. Khi nâng cấp, bản trùng được đổi thành "Tên (2)".
  - Mã RAW phải là JSON hợp lệ.
  - Lịch sử tự xóa sau N ngày (mặc định 90, đổi ở **Bộ trung tâm**), ghi cả câu nói không hiểu.
- Phiên bản 3 so với 2:
  - Bảng `scenes`, `scene_steps` (ngữ cảnh) và `schedules` (hẹn giờ).
  - `history.source` nhận thêm `scene`, `schedule`.
- Phiên bản 4 so với 3: dựng lại bảng `rooms` cho đúng `schema.sql`. CSDL nâng cấp từ bản đầu tiên (v1) còn giữ bảng `rooms` cũ (thiếu kiểm tra độ dài, không so trùng hoa/thường). Tên phòng trùng được đổi thành "Tên (2)"; id phòng giữ nguyên.
- Kiểm thử `tests/test_database.py` bảo đảm CSDL nâng cấp từ bản cũ có **cấu trúc giống hệt** CSDL tạo mới.
- Thay đổi lược đồ sau này: sửa `schema.sql`, tăng `LATEST` và thêm một bước vào `STEPS` trong `migrations.py`.
