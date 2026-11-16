// Giọng nói: module thu giọng nói → bộ trung tâm hiểu câu → phát lệnh. Kết quả đẩy lên qua SSE (sự kiện "voice").
import { api } from '../api.js';
import { $, $$, by, esc, ic, toast } from '../util.js';
import { S, handleErr, roomName } from '../state.js';
import { cur, render } from '../router.js';

const SENS = { low: 'Thấp', mid: 'Vừa', high: 'Cao' };

/** Vẽ thẻ giọng nói trên màn chính (#vc) */
export function paintVoice() {
  const el = $('#vc');
  if (!el) return;
  const vo = S.voice, n = S.vnow;
  if (!vo) { el.hidden = true; return; }
  el.hidden = false;
  el.classList.toggle('on', n.state === 'listening');
  const link = `<a class="iconbtn" href="#giong-noi" aria-label="Cài đặt giọng nói">${ic('chev')}</a>`;
  let h;
  if (vo.module === 'missing') h = `<span class="vic warn">${ic('alert')}</span><div class="grow"><b>Không tìm thấy module giọng nói</b><p class="small muted">Lệnh giọng nói tạm thời không dùng được.</p></div>${link}`;
  else if (!vo.enabled) h = `<span class="vic off">${ic('mic')}</span><div class="grow"><b>Micro đang tắt</b></div><button type="button" class="btn sm" id="vtog">Bật micro</button>`;
  else if (n.state === 'listening') h = `<span class="vic on">${ic('mic')}</span><div class="grow"><b>Đang nghe…</b></div>`;
  else if (n.state === 'result' && n.ok) h = `<span class="vic ok">${ic('check')}</span><div class="grow"><b>“${esc(n.text)}”</b><p class="small">${esc(n.label)}</p></div>`;
  else if (n.state === 'result') h = `<span class="vic warn">${ic('alert')}</span><div class="grow"><b>“${esc(n.text)}”</b><p class="small">${esc(n.message)}</p></div>`;
  else h = `<span class="vic">${ic('mic')}</span><div class="grow"><b>Đang chờ lệnh giọng nói</b><p class="small muted">Thử nói: “Bật tivi phòng khách”</p></div>${link}`;
  el.innerHTML = h;
  const t = $('#vtog', el);
  if (t) t.onclick = () => api('POST', '/api/voice', { enabled: true }).then((x) => { S.voice = x; paintVoice(); }, handleErr);
}

/** Sự kiện SSE: {state:'listening'} rồi {state:'result', text, ok, device_id, key, label, status} */
export function onVoice(ev) {
  clearTimeout(S.vT);
  if (ev.state === 'listening') {
    S.vnow = { state: 'listening' };
    paintVoice();
    S.vT = setTimeout(() => { S.vnow = { state: 'idle' }; paintVoice(); }, 8000);
    return;
  }
  const d = (S.devices || []).find(by('id', ev.device_id));
  const ok = ev.ok && ev.status === 'ok';
  const label = ev.scene ? `Đã chạy ngữ cảnh “${ev.scene}”` : 'Đã phát: ' + (d ? `${roomName(d.room_id)} · ${d.name} · ${ev.label}` : ev.label || '');
  const DEVICE_MSG = {
    offline: `Bộ phát của ${roomName(d && d.room_id).toLowerCase()} đang mất kết nối.`,
    timeout: 'Bộ phát không xác nhận.',
    error: 'Bộ phát báo lỗi khi phát lệnh.',
    busy: 'Bộ phát đang bận, nói lại sau giây lát.',
  };
  const message = !ev.ok ? 'Chưa hiểu lệnh. Nói kèm tên thiết bị và phòng, ví dụ “Tắt điều hòa phòng ngủ”.'
    : ev.scene ? (ev.status === 'partial' ? `Ngữ cảnh “${ev.scene}”: một số lệnh không thành công.` : `Ngữ cảnh “${ev.scene}”: không lệnh nào thành công.`)
      : DEVICE_MSG[ev.status] || 'Không gửi được lệnh.';
  S.vnow = { state: 'result', ok, text: ev.text, label, message };
  if (cur().name === '') paintVoice();
  else toast('Giọng nói: ' + (ok ? label : message));
  S.vT = setTimeout(() => { S.vnow = { state: 'idle' }; paintVoice(); }, 7000);
}

export function voicePage(v) {
  if (!S.voice || !S.rooms) { v.innerHTML = '<p class="muted">Đang tải…</p>'; S.waiting = true; return; }
  const vo = S.voice;
  v.innerHTML = `<section class="card"><div class="row"><span class="grow" id="l-mic"><b>Nghe lệnh giọng nói</b><br><span class="small muted">Module thu giọng nói nhận lệnh, bộ trung tâm tra mã và gửi tới bộ phát.</span></span>
      <button type="button" class="switch" role="switch" id="micsw" aria-checked="${!!vo.enabled}" aria-labelledby="l-mic"></button></div>` +
    (vo.module === 'missing' ? `<div class="note warn">${ic('alert')}<span>Bộ trung tâm chưa nhận được tín hiệu từ module giọng nói. Kiểm tra nguồn và kết nối MQTT của module.</span></div>` : '') + '</section>' +
    '<section class="card"><h2 class="lbl" id="l-sen">Độ nhạy</h2><div class="seg" role="group" aria-labelledby="l-sen">' +
    Object.keys(SENS).map((k) => `<button type="button" class="btn" data-sen="${k}" aria-pressed="${vo.sensitivity === k}">${SENS[k]}</button>`).join('') +
    '</div><p class="hint">Tăng nếu hay không nghe thấy; giảm nếu hay nhận nhầm tiếng TV.</p></section>' +
    '<section class="card"><h2 class="lbl" id="l-def">Khi không nói tên phòng, điều khiển thiết bị ở</h2><div class="chips wrap" role="group" aria-labelledby="l-def">' +
    `<button type="button" class="chip" data-def="" aria-pressed="${!vo.default_room_id}">Không chọn</button>` +
    S.rooms.map((r) => `<button type="button" class="chip" data-def="${r.id}" aria-pressed="${vo.default_room_id === r.id}">${esc(r.name)}</button>`).join('') + '</div></section>' +
    '<section class="card"><h2>Cách nói</h2><p class="small muted">Nói <b>hành động + tên thiết bị + tên phòng</b>, đúng như tên trong mục Quản lý. Nút tự tạo gọi theo tên nút.</p>' +
    '<ul class="tips"><li>“Bật tivi phòng khách”</li><li>“Tăng âm lượng tivi”</li><li>“Tắt điều hòa phòng ngủ”</li><li>“Mở Netflix”</li><li>“Bật chế độ đi ngủ” (tên <a href="#ngu-canh">ngữ cảnh</a>)</li></ul>' +
    '<p class="small muted">Module gửi chữ không dấu cũng được, ví dụ “bat tivi phong khach”.</p></section>' +
    `<a class="btn full" href="#lich-su" id="vh">${ic('history')}Xem lịch sử lệnh giọng nói</a>`;
  const save = (body, msg) => api('POST', '/api/voice', body).then((x) => { S.voice = x; if (msg) toast(msg); render(); }, handleErr);
  $('#micsw', v).onclick = () => save({ enabled: !vo.enabled }, vo.enabled ? 'Đã tắt micro' : 'Đã bật micro');
  $$('[data-sen]', v).forEach((b) => { b.onclick = () => save({ sensitivity: b.dataset.sen }); });
  $$('[data-def]', v).forEach((b) => { b.onclick = () => save({ default_room_id: b.dataset.def ? +b.dataset.def : null }); });
  $('#vh', v).onclick = () => { S.histFilter = 'voice'; };
}
