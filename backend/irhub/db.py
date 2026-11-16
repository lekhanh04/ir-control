"""Truy cập SQLite. Mỗi lệnh mở một kết nối riêng nên dùng an toàn từ nhiều luồng.

CSDL chạy chế độ WAL (đặt trong migrations.py) với synchronous=NORMAL: ít lần ghi đồng bộ xuống thẻ nhớ
hơn FULL; mất điện đột ngột chỉ có thể mất giao dịch cuối, không làm hỏng file.
"""
import os
import sqlite3
import time

from . import migrations


def now_ms():
    return int(time.time() * 1000)


class Database:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.version = migrations.migrate(path)   # tạo mới hoặc nâng cấp cấu trúc

    def connect(self):
        c = sqlite3.connect(self.path, timeout=5)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys = ON')
        c.execute('PRAGMA synchronous = NORMAL')
        return c

    def all(self, sql, args=()):
        c = self.connect()
        try:
            return [dict(r) for r in c.execute(sql, args).fetchall()]
        finally:
            c.close()

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def run(self, sql, args=()):
        """Chạy INSERT/UPDATE/DELETE, trả (lastrowid, rowcount)."""
        c = self.connect()
        try:
            cur = c.execute(sql, args)
            c.commit()
            return cur.lastrowid, cur.rowcount
        finally:
            c.close()

    def get_setting(self, key, default=None):
        r = self.one('SELECT value FROM settings WHERE key = ?', (key,))
        return r['value'] if r else default

    def set_setting(self, key, value):
        self.run('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', (key, str(value)))

    def backup_to(self, dest_path):
        src, dst = self.connect(), sqlite3.connect(dest_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

    def restore_from(self, src_path):
        """Chép đè toàn bộ nội dung CSDL đang chạy bằng file src_path (đã kiểm tra, đã nâng cấp).
        Dùng backup API của SQLite nên các kết nối khác chỉ phải chờ khóa, không cần dừng chương trình."""
        src, dst = sqlite3.connect(src_path), self.connect()
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

    def size_bytes(self):
        """Dung lượng thật trên thẻ nhớ: file chính + file WAL (nếu có)."""
        return sum(os.path.getsize(p) for p in (self.path, self.path + '-wal') if os.path.exists(p))
