// Lịch sử điều khiển: mỗi lệnh gửi tới bộ phát và kết quả xác nhận (ACK). Gom theo ngày, tải thêm từng trang.
import { api } from '../api.js';
import { $, $$, esc, ic, clock, dayLabel } from '../util.js';
import { S, skel, handleErr } from '../state.js';
import { cur, render } from '../router.js';
import { KEY_LABEL } from '../types.js';

const PAGE = 50;
const FILTERS = [['all', 'Tất cả'], ['voice', 'Giọng nói'], ['auto', 'Tự động'], ['fail', 'Lỗi']];
const MATCH = { all: () => true, voice: (h) => h.source === 'voice', auto: (h) => h.source === 'scene' || h.source === 'schedule', fail: (h) => h.status !== 'ok' };
const SOURCE = {
  web: () => 'Web',
  voice: (h) => 'Giọng nói' + (h.text ? `: “${esc(h.text)}”` : ''),
  scene: (h) => `Ngữ cảnh “${esc(h.text || '')}”`,
  schedule: (h) => esc(h.text || 'Hẹn giờ'),
};
const STATUS = { ok: 'đã phát', offline: 'bộ phát mất kết nối', timeout: 'bộ phát không xác nhận', error: 'bộ phát báo lỗi', not_understood: 'không hiểu câu lệnh' };

/** Dòng lịch sử mới (SSE) có thuộc bộ lọc đang xem không */
export const historyAccepts = (h) => (MATCH[S.histFilter] || MATCH.all)(h);

function load(more) {
  const f = S.histFilter !== 'all' ? '&filter=' + S.histFilter : '';
  const last = more && S.history && S.history[S.history.length - 1];
  const page = last ? `&before=${last.at}&before_id=${last.id}` : '';
  return api('GET', `/api/history?limit=${PAGE}${f}${page}`).then((l) => {
    S.history = more ? S.history.concat(l) : l;
    S.histMore = l.length === PAGE;
    if (cur().name === 'lich-su') render();
  }, handleErr);
}

const line = (h) => {
  if (h.status === 'not_understood') {
    return `<div><span style="color:var(--warn)">${ic('alert')}</span><span class="grow"><b>“${esc(h.text)}”</b><br><span class="small muted">Giọng nói · không hiểu câu lệnh</span></span><span class="small muted">${clock(h.at)}</span></div>`;
  }
  const what = [h.room_name, h.device_name || 'Thiết bị đã xóa', h.label || KEY_LABEL[h.key] || h.key].filter(Boolean).join(' · ');
  const st = h.status === 'ok' ? `<span style="color:var(--accent-text)">${ic('check')}</span>` : `<span style="color:var(--danger)">${ic('x')}</span>`;
  const src = (SOURCE[h.source] || SOURCE.web)(h);
  const res = STATUS[h.status] + (h.status === 'ok' && h.latency_ms != null ? ', ' + h.latency_ms + ' ms' : '');
  return `<div>${st}<span class="grow"><b>${esc(what)}</b><br><span class="small muted">${src} · ${res}</span></span><span class="small muted">${clock(h.at)}</span></div>`;
};

export function historyPage(v) {
  if (!S.history) { skel(v); load(false); return; }
  // Gom theo ngày: mỗi ngày một thẻ có tiêu đề "Hôm nay", "Hôm qua", "Thứ Hai, 14/11"…
  const days = [];
  for (const h of S.history) {
    const label = dayLabel(h.at);
    if (!days.length || days[days.length - 1].label !== label) days.push({ label, items: [] });
    days[days.length - 1].items.push(h);
  }
  v.innerHTML = '<div class="chips wrap" role="group" aria-label="Lọc">' +
    FILTERS.map(([k, l]) => `<button type="button" class="chip" data-f="${k}" aria-pressed="${S.histFilter === k}">${l}</button>`).join('') + '</div>' +
    (days.length
      ? days.map((d) => `<section class="card" aria-label="${esc(d.label)}"><h2 class="day">${esc(d.label)}</h2><div class="hist">${d.items.map(line).join('')}</div></section>`).join('')
      : '<section class="card"><p class="hint" style="padding:8px 0">Không có lệnh nào.</p></section>') +
    (S.histMore ? '<button type="button" class="btn full" id="hmore">Xem thêm</button>' : '') +
    '<p class="hint" style="text-align:center">Mỗi dòng là một lệnh gửi tới bộ phát và kết quả xác nhận (ACK), hoặc một câu nói hệ thống chưa hiểu. ' +
    'Lịch sử cũ được tự xóa theo cài đặt ở <a href="#he-thong">Bộ trung tâm</a>.</p>';
  $$('[data-f]', v).forEach((b) => { b.onclick = () => { if (S.histFilter === b.dataset.f) return; S.histFilter = b.dataset.f; S.history = null; render(); }; });
  const more = $('#hmore', v);
  if (more) more.onclick = () => { more.disabled = true; more.textContent = 'Đang tải…'; load(true); };
}
