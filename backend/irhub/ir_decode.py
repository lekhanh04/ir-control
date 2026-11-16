"""Xử lý chuỗi xung Mark/Space từ mắt thu IR.

Một khung tín hiệu (frame) là danh sách thời gian (µs) xen kẽ mark/space, bắt đầu bằng mark:
    [9000, 4500, 560, 560, 560, 1690, ..., 560]

Quy ước giá trị `value` giống IRremoteESP8266: bit truyền đi đầu tiên là bit cao nhất (MSB),
để ESP8266 phát lại bằng sendNEC(value, 32) / sendSAMSUNG(value, 32) / sendSony(value, bits) /
sendPanasonic64(value, 48) là đúng mã.
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


def _read_distance(d, start, nbits, mark, one, zero):
    """Mã hóa khoảng cách xung (NEC, Samsung, Panasonic): mark cố định, độ dài space quyết định bit."""
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


def _read_width(d, start, nbits, space, one, zero):
    """Mã hóa độ rộng xung (Sony): space cố định, độ dài mark quyết định bit. Bit cuối không có space."""
    value = 0
    for b in range(nbits):
        i = start + 2 * b
        if i >= len(d):
            return None
        if _close(d[i], one):
            bit = 1
        elif _close(d[i], zero):
            bit = 0
        else:
            return None
        if b < nbits - 1 and (i + 1 >= len(d) or not _close(d[i + 1], space)):
            return None
        value = (value << 1) | bit
    return value


def _ends_at(d, i):
    """Khung kết thúc ở phần tử i (mark cuối): hết dữ liệu, hoặc sau đó là khoảng lặng dài (khung lặp dính vào)."""
    return len(d) == i + 1 or (len(d) > i + 1 and d[i + 1] > 5000)


# Giao thức khoảng cách xung: tên, header mark, header space, bit mark, space bit 1, space bit 0, số bit.
DISTANCE = [
    ('NEC', 9000, 4500, 560, 1690, 560, 32),
    ('SAMSUNG', 4500, 4500, 560, 1690, 560, 32),
    ('PANASONIC', 3456, 1728, 432, 1296, 432, 48),
]
# Sony SIRC: header 2400/600, bit 1 = mark 1200, bit 0 = mark 600, space 600; 12, 15 hoặc 20 bit.
SONY = (2400, 600, 600, 1200, 600)
SONY_BITS = (12, 15, 20)
PROTOCOL_NAMES = [p[0] for p in DISTANCE] + ['SONY']


def _rev(v, n):
    return int('{:0{}b}'.format(v, n)[::-1], 2)


def _info(name, v, bits):
    if name in ('NEC', 'SAMSUNG'):
        b = v.to_bytes(4, 'big')
        address, command = '0x%02X' % _rev8(b[0]), '0x%02X' % _rev8(b[2])
    elif name == 'PANASONIC':
        address, command = '0x%04X' % (v >> 32), '0x%08X' % (v & 0xFFFFFFFF)
    else:   # SONY: truyền LSB trước, 7 bit lệnh rồi tới địa chỉ
        address, command = '0x%02X' % _rev(v & ((1 << (bits - 7)) - 1), bits - 7), '0x%02X' % _rev(v >> (bits - 7), 7)
    return {'protocol': name, 'value': '0x%0*X' % ((bits + 3) // 4, v), 'bits': bits, 'address': address, 'command': command}


def decode(d):
    """Thử nhận dạng giao thức. Trả dict hoặc None (khi đó lưu dạng RAW)."""
    if len(d) < 4:
        return None
    for name, hm, hs, mark, one, zero, nbits in DISTANCE:
        if _close(d[0], hm, tol=0.2) and _close(d[1], hs, tol=0.2) and len(d) >= 3 + 2 * nbits:
            v = _read_distance(d, 2, nbits, mark, one, zero)
            if v is not None and _ends_at(d, 2 + 2 * nbits):
                return _info(name, v, nbits)
    hm, hs, space, one, zero = SONY
    if _close(d[0], hm, tol=0.2) and _close(d[1], hs, tol=0.3):
        n, i = 0, 2
        while i < len(d):          # đếm số mark tới hết khung
            n += 1
            if i + 1 >= len(d) or d[i + 1] > 2000:
                break
            i += 2
        if n in SONY_BITS:
            v = _read_width(d, 2, n, space, one, zero)
            if v is not None:
                return _info('SONY', v, n)
    return None


def encode(protocol, value, bits=None):
    """Sinh khung xung từ mã (dùng cho giả lập và kiểm thử)."""
    if protocol == 'SONY':
        hm, hs, space, one, zero = SONY
        bits = bits or 12
        d = [hm, hs]
        for i in range(bits - 1, -1, -1):
            d += [one if (value >> i) & 1 else zero, space]
        return d[:-1]
    name, hm, hs, mark, one, zero, nb = next(p for p in DISTANCE if p[0] == protocol)
    bits = bits or nb
    d = [hm, hs]
    for i in range(bits - 1, -1, -1):
        d += [mark, one if (value >> i) & 1 else zero]
    d.append(mark)
    return d


def encode_32(protocol, value):
    return encode(protocol, value, 32)


def nec_value(address, command):
    """Mã NEC chuẩn (địa chỉ 8 bit + bù, lệnh + bù) theo quy ước MSB-first ở trên."""
    return (_rev8(address) << 24) | (_rev8(~address & 0xFF) << 16) | (_rev8(command) << 8) | _rev8(~command & 0xFF)


def samsung_value(address, command):
    return (_rev8(address) << 24) | (_rev8(address) << 16) | (_rev8(command) << 8) | _rev8(~command & 0xFF)


def sony_value(address, command, bits=12):
    """Mã Sony: 7 bit lệnh + (bits-7) bit địa chỉ, truyền LSB trước."""
    raw = command | (address << 7)
    return _rev(raw, bits)
