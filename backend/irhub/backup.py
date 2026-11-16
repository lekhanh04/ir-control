"""Sao lưu tự động và khôi phục CSDL.

- Mỗi ngày một bản: data/backups/irhub-YYYYMMDD.db, giữ BACKUP_KEEP bản mới nhất (0 = tắt).
  Bản sao nằm cùng thẻ nhớ nên cứu được khi file CSDL hỏng / lỡ xóa nhầm, KHÔNG cứu được khi hỏng cả thẻ:
  thỉnh thoảng hãy tải bản sao về máy (trang Bộ trung tâm).
- Khôi phục (từ file tải lên hoặc từ bản tự động): kiểm tra file, nâng cấp lên phiên bản mới nhất,
  sao lưu CSDL hiện tại thành irhub-truoc-khoi-phuc-<thời gian>.db, rồi chép đè.
"""
import os
import re
import shutil
import sqlite3
import tempfile
import time

from . import migrations

NAME_RE = re.compile(r'^irhub-[0-9a-z-]{8,40}\.db$')
REQUIRED_TABLES = {'rooms', 'devices', 'commands', 'history'}


class BadBackup(Exception):
    """File không phải bản sao lưu dùng được. Thông điệp bằng tiếng Việt, hiển thị được cho người dùng."""


def backup_dir(db_path):
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), 'backups')


def list_backups(db_path):
    d = backup_dir(db_path)
    if not os.path.isdir(d):
        return []
    out = []
    for name in os.listdir(d):
        p = os.path.join(d, name)
        if NAME_RE.match(name) and os.path.isfile(p):
            st = os.stat(p)
            out.append({'name': name, 'size_kb': st.st_size // 1024, 'at': int(st.st_mtime * 1000)})
    return sorted(out, key=lambda b: b['at'], reverse=True)


def backup_path(db_path, name):
    """Đường dẫn của một bản sao lưu theo tên; None nếu tên không hợp lệ hoặc không có (chặn ../)."""
    if not isinstance(name, str) or not NAME_RE.match(name):
        return None
    p = os.path.join(backup_dir(db_path), name)
    return p if os.path.isfile(p) else None


def daily_backup(db, keep, now=None, log=print):
    """Tạo bản sao của hôm nay nếu chưa có, rồi xóa bớt bản tự động cũ. Trả tên file vừa tạo hoặc None."""
    if keep <= 0:
        return None
    d = backup_dir(db.path)
    os.makedirs(d, exist_ok=True)
    name = time.strftime('irhub-%Y%m%d.db', time.localtime(now or time.time()))
    path = os.path.join(d, name)
    created = None
    if not os.path.exists(path):
        tmp = path + '.tmp'
        db.backup_to(tmp)
        os.replace(tmp, path)          # không để lại file dở dang nếu mất điện giữa chừng
        created = name
        log('[Sao lưu] Đã tạo %s' % name)
    daily = sorted(n for n in os.listdir(d) if re.match(r'^irhub-\d{8}\.db$', n))
    for old in daily[:-keep]:
        os.remove(os.path.join(d, old))
    return created


def check_file(path):
    """Kiểm tra file là CSDL của bộ trung tâm, không hỏng, không mới hơn phần mềm. Trả phiên bản cấu trúc."""
    try:
        with open(path, 'rb') as f:
            if f.read(16) != b'SQLite format 3\x00':
                raise BadBackup('File không phải cơ sở dữ liệu SQLite')
        c = sqlite3.connect('file:%s?mode=ro' % path.replace('\\', '/'), uri=True)
        try:
            if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise BadBackup('File sao lưu bị hỏng')
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            ver = c.execute('PRAGMA user_version').fetchone()[0] or 1
        finally:
            c.close()
    except sqlite3.DatabaseError:
        raise BadBackup('File sao lưu bị hỏng hoặc không đọc được')
    if not REQUIRED_TABLES <= tables:
        raise BadBackup('File không phải bản sao lưu của bộ trung tâm IR')
    if ver > migrations.LATEST:
        raise BadBackup('Bản sao lưu từ phần mềm mới hơn (cấu trúc v%d). Hãy cập nhật phần mềm trước.' % ver)
    return ver


def restore(db, src_path, log=print):
    """Khôi phục từ src_path (file không bị sửa). Trả tên bản sao lưu an toàn của CSDL trước khi khôi phục."""
    check_file(src_path)
    work = tempfile.mkdtemp(prefix='irhub-restore-', dir=os.path.dirname(os.path.abspath(db.path)))
    try:
        tmp = os.path.join(work, 'restore.db')
        shutil.copyfile(src_path, tmp)
        migrations.migrate(tmp, log=log)          # bản sao cũ → nâng cấp lên phiên bản hiện tại
        d = backup_dir(db.path)
        os.makedirs(d, exist_ok=True)
        safety = time.strftime('irhub-truoc-khoi-phuc-%Y%m%d-%H%M%S.db')
        db.backup_to(os.path.join(d, safety))
        secret = db.get_setting('auth.secret')    # giữ khóa đăng nhập hiện tại: không ai bị đăng xuất
        db.restore_from(tmp)
        if secret:
            db.set_setting('auth.secret', secret)
        log('[Khôi phục] Xong. CSDL trước đó lưu ở backups/%s' % safety)
        return safety
    finally:
        shutil.rmtree(work, ignore_errors=True)
