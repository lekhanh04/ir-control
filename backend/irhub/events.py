"""Đẩy sự kiện thời gian thực lên giao diện qua Server-Sent Events (GET /api/events)."""
import json
import queue
import threading


class EventBus:
    def __init__(self):
        self._subs = set()
        self._lock = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=200)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)

    def publish(self, event, data):
        msg = 'event: %s\ndata: %s\n\n' % (event, json.dumps(data, ensure_ascii=False))
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass  # trình duyệt đọc quá chậm: bỏ qua, nó sẽ tải lại dữ liệu khi cần

    def stream(self):
        """Generator cho Flask Response."""
        q = self.subscribe()
        try:
            yield ': connected\n\n'
            while True:
                try:
                    yield q.get(timeout=15)
                except queue.Empty:
                    yield ': ping\n\n'  # giữ kết nối, giúp trình duyệt phát hiện rớt mạng
        finally:
            self.unsubscribe(q)
