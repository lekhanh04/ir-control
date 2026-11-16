import random

import pytest

from irhub import ir_decode as d


@pytest.mark.parametrize('protocol,value,bits', [
    ('NEC', d.nec_value(0x30, 0x12), 32),
    ('SAMSUNG', d.samsung_value(0x07, 0x02), 32),
    ('PANASONIC', 0x40040100BCBD, 48),
    ('SONY', d.sony_value(0x01, 0x15, 12), 12),
    ('SONY', d.sony_value(0x1A, 0x3C, 15), 15),
    ('SONY', d.sony_value(0x05, 0x02, 20), 20),
])
def test_round_trip(protocol, value, bits):
    out = d.decode(d.encode(protocol, value, bits))
    assert out['protocol'] == protocol
    assert int(out['value'], 16) == value
    assert out['bits'] == bits


def test_nec_address_command():
    out = d.decode(d.encode('NEC', d.nec_value(0x30, 0x12)))
    assert (out['address'], out['command']) == ('0x30', '0x12')


def test_sony_known_power_code():
    # Mã nguồn tivi Sony nổi tiếng: 0xA90 (12 bit) = địa chỉ 1, lệnh 21
    out = d.decode(d.encode('SONY', 0xA90, 12))
    assert (out['address'], out['command'], out['value']) == ('0x01', '0x15', '0xA90')


def test_noisy_timing_still_decodes():
    rnd = random.Random(1)
    frame = [v + rnd.randint(-60, 60) for v in d.encode('SAMSUNG', d.samsung_value(7, 9))]
    assert d.decode(frame)['protocol'] == 'SAMSUNG'


def test_long_air_conditioner_frame_stays_raw():
    # Khung 64 bit header 3500/1750 (điều hòa) không được nhận nhầm thành PANASONIC 48 bit
    frame = [3500, 1750] + [430, 1300] * 64 + [430]
    assert d.decode(frame) is None


def test_nec_header_with_extra_bits_stays_raw():
    # Header giống NEC nhưng dài hơn 32 bit → không phải NEC, phải lưu RAW để phát lại đúng
    frame = d.encode('NEC', 0x12345678)[:-1] + [560, 560] * 8 + [560]
    assert d.decode(frame) is None


def test_trailing_repeat_after_long_gap_is_ignored():
    frame = d.encode('NEC', d.nec_value(1, 2)) + [40000, 9000, 2250, 560]
    assert d.decode(frame)['protocol'] == 'NEC'


def test_garbage_returns_none():
    assert d.decode([100, 200, 300]) is None
    assert d.decode([]) is None


def test_compare_frames_match_and_average():
    base = d.encode('NEC', d.nec_value(1, 2))
    frames = [[v + 20 for v in base], base, [v - 20 for v in base]]
    pct, avg = d.compare_frames(frames)
    assert pct == 100
    assert avg == [int(round(v / 10.0)) * 10 for v in base]


def test_compare_frames_detects_mismatch():
    base = d.encode('NEC', d.nec_value(1, 2))
    bad = [v * (2 if i % 3 == 0 else 1) for i, v in enumerate(base)]
    pct, _ = d.compare_frames([base, base, bad])
    assert pct < 90
