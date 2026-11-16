"""Xử lý chuỗi xung Mark/Space từ mắt thu IR.

Một khung tín hiệu (frame) là danh sách thời gian (µs) xen kẽ mark/space, bắt đầu bằng mark:
    [9000, 4500, 560, 560, 560, 1690, ..., 560]

Quy ước giá trị `value` giống IRremoteESP8266: bit truyền đi đầu tiên là bit cao nhất (MSB),
để ESP8266 phát lại bằng sendNEC(value, 32) / sendSAMSUNG(value, 32) là đúng mã.
"""


def _close(measured, expected, tol=0.3, min_abs=200):
    return abs(measured - expected) <= max(min_abs, expected * tol)


def _rev8(b):
    return int('{:08b}'.format(b)[::-1], 2)


def compare_frames(frames, tol=0.25, min_abs=150):
    """So sánh nhiều lần thu. Trả (match_pct, khung trung bình đã làm tròn 10 µs)."""
    if not frames:
        return 0, []
    shortest = min(len(f) for f in frames)
    longest = max(len(f) for f in frames)
    matched = 0
    avg = []
    for i in range(shortest):
        vals = sorted(f[i] for f in frames)
        ref = vals[len(vals) // 2]
        if all(abs(v - ref) <= max(min_abs, ref * tol) for v in vals):
            matched += 1
        avg.append(int(round(sum(vals) / len(vals) / 10.0)) * 10)
    pct = int(round(100.0 * matched / longest)) if longest else 0
    return pct, avg


def _read_bits(d, start, nbits, mark=560, one=1690, zero=560):
    value = 0
    for b in range(nbits):
        i = start + 2 * b
        if i + 1 >= len(d) or not _close(d[i], mark):
            return None
        if _close(d[i + 1], one):
            bit = 1
        elif _close(d[i + 1], zero):
            bit = 0
        else:
            return None
        value = (value << 1) | bit
    return value


# Giao thức nhận dạng được: (tên, header mark, header space). Cả hai dùng 32 bit, mã hóa khoảng cách xung.
PROTOCOLS = [('NEC', 9000, 4500), ('SAMSUNG', 4500, 4500)]


def decode(d):
    """Thử nhận dạng giao thức. Trả dict hoặc None (khi đó lưu dạng RAW)."""
    if len(d) < 2 + 2 * 32:
        return None
    for name, hm, hs in PROTOCOLS:
        if _close(d[0], hm, tol=0.2) and _close(d[1], hs, tol=0.2):
            v = _read_bits(d, 2, 32)
            if v is None:
                continue
            b = v.to_bytes(4, 'big')
            return {
                'protocol': name,
                'value': '0x%08X' % v,
                'bits': 32,
                'address': '0x%02X' % _rev8(b[0]),
                'command': '0x%02X' % _rev8(b[2]),
            }
    return None


def encode_32(protocol, value):
    """Sinh khung xung từ mã 32 bit (dùng cho giả lập và kiểm thử)."""
    hm, hs = {'NEC': (9000, 4500), 'SAMSUNG': (4500, 4500)}[protocol]
    d = [hm, hs]
    for i in range(31, -1, -1):
        d += [560, 1690 if (value >> i) & 1 else 560]
    d.append(560)
    return d


def nec_value(address, command):
    """Mã NEC chuẩn (địa chỉ 8 bit + bù, lệnh + bù) theo quy ước MSB-first ở trên."""
    return (_rev8(address) << 24) | (_rev8(~address & 0xFF) << 16) | (_rev8(command) << 8) | _rev8(~command & 0xFF)


def samsung_value(address, command):
    return (_rev8(address) << 24) | (_rev8(address) << 16) | (_rev8(command) << 8) | _rev8(~command & 0xFF)
