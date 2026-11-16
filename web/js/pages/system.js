// Bộ trung tâm: trạng thái MQTT, mắt thu, Raspberry Pi; thời gian lưu lịch sử; sao lưu và khôi phục CSDL.
import { api } from '../api.js';
import { $, $$, esc, toast, dialog } from '../util.js';
import { S, handleErr, loadBase } from '../state.js';
import { render } from '../router.js';

const KEEP = [[30, '30 ngày'], [90, '90 ngày'], [180, '6 tháng'], [365, '1 năm'], [0, 'Giữ mãi']];

export function systemPage(v) {
  v.innerHTML = '<div class="grid2" id="stg"></div>' +
    '<section class="card"><h2>Sao lưu dữ liệu</h2><p class="small muted">Tải bản sao cơ sở dữ liệu SQLite (phòng, thiết bị, mã IR, lịch sử) để cất giữ hoặc chuyển sang thẻ nhớ mới.</p>' +
    '<a class="btn" href="/api/backup" download>Tải bản sao lưu</a>' +
    '<h3 class="lbl" style="margin-top:8px">Bản sao lưu tự động trên Pi</h3><div id="bks"><div class="sk"></div></div>' +
    '<p class="hint" id="bkh"></p></section>' +
    '<section class="card"><h2>Khôi phục dữ liệu</h2><p class="small muted">Thay toàn bộ phòng, thiết bị, mã IR, ngữ cảnh, hẹn giờ và lịch sử bằng một bản sao lưu. ' +
    'Dữ liệu hiện tại được tự lưu thành một bản sao trước khi thay.</p>' +
    '<div class="field"><label for="rf">File sao lưu (.db)</label><input type="file" id="rf" class="inp" accept=".db,application/x-sqlite3,application/octet-stream" style="padding:10px 12px"></div>' +
    '<button type="button" class="btn dng" id="rbtn" disabled>Khôi phục từ file này</button></section>' +
    '<section class="card"><h2>Lịch sử điều khiển</h2><div class="field"><label for="keep">Tự xóa lịch sử cũ hơn</label><select id="keep" class="inp" disabled></select></div>' +
    '<p class="hint">Giữ cơ sở dữ liệu gọn trên thẻ nhớ của Raspberry Pi. Phòng, thiết bị và mã IR không bị ảnh hưởng.</p></section>' +
    (S.auth && S.auth.required ? '<section class="card"><h2>Đăng nhập</h2><p class="small muted">Trình duyệt này đang được nhớ. Đăng xuất khi dùng máy của người khác. Đổi mã PIN bằng biến IRHUB_PIN trong backend/.env.</p>' +
      '<button type="button" class="btn" id="logout">Đăng xuất</button></section>' : '') +
    '<p class="hint" style="text-align:center" id="ver"></p>';
  paintSystem();
  loadBackups(v);
  const rf = $('#rf', v), rb = $('#rbtn', v);
  rf.onchange = () => { rb.disabled = !rf.files.length; };
  rb.onclick = () => {
    const f = rf.files[0];
    if (f) confirmRestore(`file “${f.name}”`, () => { const fd = new FormData(); fd.append('file', f); return fd; });
  };
  const lo = $('#logout', v);
  if (lo) lo.onclick = () => api('POST', '/api/logout').then(() => { toast('Đã đăng xuất'); S.hooks.login(); }, handleErr);
  const sel = $('#keep', v);
  api('GET', '/api/settings').then((st) => {
    const opts = KEEP.some(([d]) => d === st.history_retention_days) ? KEEP : [[st.history_retention_days, st.history_retention_days + ' ngày'], ...KEEP];
    sel.innerHTML = opts.map(([d, l]) => `<option value="${d}"${d === st.history_retention_days ? ' selected' : ''}>${l}</option>`).join('');
    sel.disabled = false;
  }, handleErr);
  sel.onchange = () => api('PATCH', '/api/settings', { history_retention_days: +sel.value })
    .then(() => { S.history = null; toast(+sel.value ? 'Đã lưu. Lịch sử cũ hơn sẽ được tự xóa' : 'Đã lưu. Lịch sử được giữ mãi'); }, handleErr);
}

const fmtTime = (ms) => new Date(ms).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' });

function loadBackups(v) {
  api('GET', '/api/backups').then(({ keep, items }) => {
    const box = $('#bks', v);
    if (!box) return;
    $('#bkh', v).textContent = keep
      ? `Mỗi ngày bộ trung tâm tự tạo một bản, giữ ${keep} bản gần nhất. Các bản này nằm cùng thẻ nhớ, nên thỉnh thoảng vẫn nên tải một bản về máy.`
      : 'Sao lưu tự động đang tắt (IRHUB_BACKUP_KEEP=0).';
    box.innerHTML = items.length
      ? '<div class="list">' + items.map((b) => `<div><span class="grow"><b>${b.name.includes('truoc-khoi-phuc') ? 'Trước khi khôi phục' : 'Tự động'}</b>` +
          `<br><span class="small muted">${esc(fmtTime(b.at))} · ${b.size_kb} KB</span></span>` +
          `<a class="btn sm ghost" href="/api/backups/${encodeURIComponent(b.name)}" download>Tải</a>` +
          `<button type="button" class="btn sm" data-restore="${esc(b.name)}" data-at="${b.at}">Khôi phục</button></div>`).join('') + '</div>'
      : '<p class="hint">Chưa có bản sao lưu tự động nào.</p>';
    $$('[data-restore]', box).forEach((b) => {
      b.onclick = () => confirmRestore(`bản sao lưu lúc ${fmtTime(+b.dataset.at)}`, () => ({ name: b.dataset.restore }));
    });
  }, handleErr);
}

function confirmRestore(what, makeBody) {
  dialog({
    title: 'Khôi phục dữ liệu?',
    body: `Toàn bộ dữ liệu hiện tại sẽ được thay bằng ${esc(what)}. Dữ liệu hiện tại được tự lưu thành một bản sao trước khi thay.`,
    actions: [{ label: 'Hủy' }, { label: 'Khôi phục', dng: true, run: () => doRestore(makeBody()) }],
  });
}

async function doRestore(body) {
  toast('Đang khôi phục…');
  try {
    if (body instanceof FormData) {
      // Tải file lên: không dùng api() vì cần gửi multipart thay vì JSON
      const r = await fetch('/api/restore', { method: 'POST', body, credentials: 'same-origin' });
      const j = await r.json().catch(() => ({}));
      if (r.status === 401 && j.error === 'auth') { S.hooks.login(); return; }
      if (!r.ok) throw Object.assign(new Error(j.message || 'Lỗi ' + r.status), { status: r.status, code: j.error });
    } else {
      await api('POST', '/api/restore', body, 60000);
    }
    Object.assign(S, { cmds: {}, history: null, schedules: null });
    await loadBase();
    toast('Đã khôi phục dữ liệu');
    render();
  } catch (e) {
    if (e.code === 'bad_backup') dialog({ title: 'Không khôi phục được', body: esc(e.message) + '. Dữ liệu hiện tại không bị thay đổi.', actions: [{ label: 'Đóng', pri: true }] });
    else handleErr(e);
  }
}

export function paintSystem() {
  const g = $('#stg');
  if (!g) return;
  const s = S.system;
  if (!s) { g.innerHTML = '<div class="stat"><div class="sk"></div></div><div class="stat"><div class="sk"></div></div>'; return; }
  const up = (t) => { const d = Math.floor(t / 86400), h = Math.floor((t % 86400) / 3600), m = Math.floor((t % 3600) / 60); return (d ? d + ' ngày ' : '') + h + ' giờ ' + m + ' phút'; };
  const st = (k, val) => `<div class="stat"><span class="lbl">${k}</span><div>${val}</div></div>`;
  const okb = (x) => (x === 'ok' ? '<b>Hoạt động</b>' : '<span class="badge bad">Lỗi</span>');
  const pct = Math.round((s.disk_used_mb / s.disk_total_mb) * 100);
  const on = (S.slaves || []).filter((x) => x.online).length;
  g.innerHTML = [
    st('MQTT broker', okb(s.mqtt)),
    st('Mắt thu IR', okb(s.ir_receiver)),
    st('Bộ phát đang hoạt động', `<b>${on} / ${(S.slaves || []).length}</b>`),
    st('Thời gian chạy', `<b>${up(s.uptime_s)}</b>`),
    st('Nhiệt độ CPU', `<b>${s.cpu_temp_c == null ? '—' : s.cpu_temp_c.toFixed(1) + ' °C'}</b>`),
    st('Bộ nhớ', `<b>${(s.disk_used_mb / 1024).toFixed(1)} / ${(s.disk_total_mb / 1024).toFixed(1)} GB</b><div class="bar" aria-hidden="true"><i style="width:${pct}%"></i></div>`),
    st('Cơ sở dữ liệu', `<b>${s.db_size_kb} KB</b>${s.db_schema ? ` <span class="small muted">· lược đồ v${s.db_schema}</span>` : ''}`),
  ].join('');
  const ver = $('#ver');
  if (ver) ver.textContent = `Phiên bản ${s.version}${s.simulate ? ' · đang chạy chế độ giả lập' : ''}`;
}
