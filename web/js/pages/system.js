// Bộ trung tâm: trạng thái MQTT, mắt thu, Raspberry Pi; thời gian lưu lịch sử; sao lưu CSDL.
import { api } from '../api.js';
import { $, toast } from '../util.js';
import { S, handleErr } from '../state.js';

const KEEP = [[30, '30 ngày'], [90, '90 ngày'], [180, '6 tháng'], [365, '1 năm'], [0, 'Giữ mãi']];

export function systemPage(v) {
  v.innerHTML = '<div class="grid2" id="stg"></div>' +
    '<section class="card"><h2>Sao lưu dữ liệu</h2><p class="small muted">Tải bản sao cơ sở dữ liệu SQLite (phòng, thiết bị, mã IR, lịch sử) để cất giữ hoặc chuyển sang thẻ nhớ mới.</p>' +
    '<a class="btn" href="/api/backup" download>Tải bản sao lưu</a></section>' +
    '<section class="card"><h2>Lịch sử điều khiển</h2><div class="field"><label for="keep">Tự xóa lịch sử cũ hơn</label><select id="keep" class="inp" disabled></select></div>' +
    '<p class="hint">Giữ cơ sở dữ liệu gọn trên thẻ nhớ của Raspberry Pi. Phòng, thiết bị và mã IR không bị ảnh hưởng.</p></section>' +
    (S.auth && S.auth.required ? '<section class="card"><h2>Đăng nhập</h2><p class="small muted">Trình duyệt này đang được nhớ. Đăng xuất khi dùng máy của người khác. Đổi mã PIN bằng biến IRHUB_PIN trong backend/.env.</p>' +
      '<button type="button" class="btn" id="logout">Đăng xuất</button></section>' : '') +
    '<p class="hint" style="text-align:center" id="ver"></p>';
  paintSystem();
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
