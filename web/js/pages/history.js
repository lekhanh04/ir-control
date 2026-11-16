// Lịch sử điều khiển: mỗi lệnh gửi tới bộ phát và kết quả xác nhận (ACK).
import { api } from '../api.js';
import { $$, esc, ic, clock } from '../util.js';
import { S, skel, handleErr } from '../state.js';
import { cur, render } from '../router.js';
import { KEY_LABEL } from '../types.js';

const FILTERS = [['all', 'Tất cả'], ['voice', 'Giọng nói'], ['fail', 'Không thành công']];
const STATUS = { ok: 'đã phát', offline: 'bộ phát mất kết nối', timeout: 'bộ phát không xác nhận', error: 'bộ phát báo lỗi', not_understood: 'không hiểu câu lệnh' };

export function historyPage(v) {
  if (!S.history) {
    skel(v);
    api('GET', '/api/history?limit=100').then((l) => { S.history = l; if (cur().name === 'lich-su') render(); }, handleErr);
    return;
  }
  const list = S.history.filter((h) => S.histFilter === 'all' || (S.histFilter === 'voice' ? h.source === 'voice' : h.status !== 'ok'));
  const line = (h) => {
    if (h.status === 'not_understood') {
      return `<div><span style="color:var(--warn)">${ic('alert')}</span><span class="grow"><b>“${esc(h.text)}”</b><br><span class="small muted">Giọng nói · không hiểu câu lệnh</span></span><span class="small muted">${clock(h.at)}</span></div>`;
    }
    const what = [h.room_name, h.device_name || 'Thiết bị đã xóa', h.label || KEY_LABEL[h.key] || h.key].filter(Boolean).join(' · ');
    const st = h.status === 'ok' ? `<span style="color:var(--accent-text)">${ic('check')}</span>` : `<span style="color:var(--danger)">${ic('x')}</span>`;
    const src = h.source === 'voice' ? 'Giọng nói' + (h.text ? `: “${esc(h.text)}”` : '') : 'Web';
    const res = STATUS[h.status] + (h.status === 'ok' && h.latency_ms != null ? ', ' + h.latency_ms + ' ms' : '');
    return `<div>${st}<span class="grow"><b>${esc(what)}</b><br><span class="small muted">${src} · ${res}</span></span><span class="small muted">${clock(h.at)}</span></div>`;
  };
  v.innerHTML = '<div class="chips" role="group" aria-label="Lọc">' +
    FILTERS.map(([k, l]) => `<button type="button" class="chip" data-f="${k}" aria-pressed="${S.histFilter === k}">${l}</button>`).join('') + '</div>' +
    `<section class="card"><div class="hist">${list.length ? list.map(line).join('') : '<p class="hint" style="padding:8px 0">Không có lệnh nào.</p>'}</div></section>` +
    '<p class="hint" style="text-align:center">Mỗi dòng là một lệnh gửi tới bộ phát và kết quả xác nhận (ACK), hoặc một câu nói hệ thống chưa hiểu. ' +
    'Lịch sử cũ được tự xóa theo cài đặt ở <a href="#he-thong">Bộ trung tâm</a>.</p>';
  $$('[data-f]', v).forEach((b) => { b.onclick = () => { S.histFilter = b.dataset.f; render(); }; });
}
