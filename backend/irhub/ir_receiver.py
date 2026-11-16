"""Mắt thu IR nối vào GPIO của Raspberry Pi (VS1838B / HX1838B / TSOP).

PigpioReceiver đo thời gian giữa các cạnh tín hiệu bằng pigpio (cần chạy `sudo pigpiod`).
Khi không có cạnh mới trong GAP_MS, khung tín hiệu được coi là kết thúc và gửi cho on_frame(frame).

SimReceiver dùng khi IRHUB_SIMULATE=1: tự sinh 3 lần thu sau khi bắt đầu học mã.
"""
import hashlib
import random
import threading
import time

from . import ir_decode

MIN_FRAME = 6   # bỏ khung quá ngắn (nhiễu, mã lặp NEC khi giữ nút)
GAP_MS = 20     # khoảng lặng kết thúc một khung


class PigpioReceiver:
    def __init__(self, gpio, glitch_us=100):
        import pigpio  # chỉ có trên Raspberry Pi
        self._pigpio = pigpio
        self.gpio = gpio
        self.on_frame = None
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise RuntimeError('Không kết nối được pigpiod. Chạy: sudo systemctl enable --now pigpiod')
        self.pi.set_mode(gpio, pigpio.INPUT)
        self.pi.set_pull_up_down(gpio, pigpio.PUD_UP)
        self.pi.set_glitch_filter(gpio, glitch_us)
        self._pulses = []
        self._last = None
        self._cb = self.pi.callback(gpio, pigpio.EITHER_EDGE, self._edge)
        self.pi.set_watchdog(gpio, GAP_MS)

    def _edge(self, gpio, level, tick):
        if level == self._pigpio.TIMEOUT:      # watchdog: không có cạnh mới → hết khung
            if self._pulses:
                frame, self._pulses, self._last = self._pulses, [], None
                if len(frame) >= MIN_FRAME and self.on_frame:
                    self.on_frame(frame)
            return
        if self._last is not None:
            self._pulses.append(self._pigpio.tickDiff(self._last, tick))
        self._last = tick

    def arm(self, hint=None):
        self._pulses, self._last = [], None

    def healthy(self):
        return bool(self.pi.connected)


class SimReceiver:
    """Giả lập người dùng bấm nút 3 lần. mode: 'ok' | 'mismatch' | 'timeout'."""

    def __init__(self):
        self.on_frame = None
        self.mode = 'ok'
        self._token = 0

    def healthy(self):
        return True

    def arm(self, hint=None):
        self._token += 1
        token, hint, mode = self._token, hint or {}, self.mode
        if mode == 'timeout':
            return
        base = self._frame_for(hint)

        def run():
            time.sleep(1.0)
            for i in range(3):
                if token != self._token:
                    return
                frame = [max(100, v + random.randint(-40, 40)) for v in base]
                if mode == 'mismatch' and i == 2:
                    frame = [v * (2 if j % 7 == 0 else 1) for j, v in enumerate(frame)]
                if self.on_frame:
                    self.on_frame(frame)
                time.sleep(1.1)

        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def _frame_for(hint):
        seed = int(hashlib.md5(('%s/%s' % (hint.get('device_id'), hint.get('key'))).encode()).hexdigest()[:6], 16)
        t = hint.get('type')
        if t in ('tv',):
            return ir_decode.encode_32('SAMSUNG', ir_decode.samsung_value(0x07, seed & 0xFF))
        if t in ('projector', 'other'):
            return ir_decode.encode_32('NEC', ir_decode.nec_value(0x30, seed & 0xFF))
        # Điều hòa, quạt: khung dài không theo NEC → lưu RAW
        rnd = random.Random(seed)
        d = [3500, 1750]
        for _ in range(64):
            d += [430, 1300 if rnd.random() < 0.5 else 430]
        d.append(430)
        return d
