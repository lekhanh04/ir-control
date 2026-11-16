// Màn chính: chọn phòng → danh sách thiết bị trong phòng.
import { $, $$, by, esc, ic } from '../util.js';
import { S, store, skel, slaveLine , typeInfo } from '../state.js';
import { render } from '../router.js';
import { addRoom } from './manage.js';
import { paintVoice } from './voice.js';

export function homePage(v) {
  if (!S.rooms || !S.devices || !S.slaves) return skel(v);
  if (!S.rooms.length) {
    v.innerHTML = `<section class="card center" style="padding:40px 20px;gap:16px"><span class="muted">${ic('home')}</span>
      <h2>Bắt đầu bằng việc tạo phòng</h2><p class="muted">Mỗi phòng có một bộ phát ESP8266 và các thiết bị trong phòng đó.</p>
      <button type="button" class="btn pri big full" id="nr">Tạo phòng đầu tiên</button></section>`;
    $('#nr', v).onclick = addRoom;
    return;
  }
  const devs = S.devices.filter(by('room_id', S.room));
  v.innerHTML = '<section class="vc" id="vc" aria-live="polite" aria-label="Giọng nói"></section>' +
    '<div class="chips" role="group" aria-label="Chọn phòng">' +
    S.rooms.map((r) => `<button type="button" class="chip" data-room="${r.id}" aria-pressed="${r.id === S.room}">${esc(r.name)}</button>`).join('') + '</div>' +
    slaveLine(S.room) +
    '<div class="devs">' + devs.map((d) => {
      const t = typeInfo(d.type);
      return `<a class="dev" href="#tb-${d.id}"><span class="dico">${ic(t.icon)}</span><span><b>${esc(d.name)}</b><span class="small muted">${esc(d.brand || t.label)} · ${d.command_count || 0} nút</span></span></a>`;
    }).join('') + `<a class="dev add" href="#them-tb">${ic('plus')}Thêm thiết bị</a></div>`;
  paintVoice();
  $$('[data-room]', v).forEach((b) => { b.onclick = () => { S.room = +b.dataset.room; store.set('room', S.room); render(); }; });
  $('a.dev.add', v).onclick = () => { S.formRoom = S.room; };
}
