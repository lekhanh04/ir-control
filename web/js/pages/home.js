// Màn chính: chọn phòng → danh sách thiết bị (có nút Nguồn nhanh) → ngữ cảnh.
// Màn hình rộng: thiết bị bên trái, remote của thiết bị đang chọn bên phải (splitPage).
import { api } from '../api.js';
import { $, $$, by, esc, ic, toast, buzz } from '../util.js';
import { S, store, skel, slaveLine, slaveForDevice, typeInfo, handleErr } from '../state.js';
import { cur, render } from '../router.js';
import { addRoom } from './manage.js';
import { paintVoice } from './voice.js';
import { runSceneConfirm } from './scenes.js';
import { remotePage, tempText } from './remote.js';

/** Chọn phòng: nhớ theo trình duyệt và ghi vào địa chỉ (#phong-3) mà không tạo thêm bước "Quay lại" */
function selectRoom(id) {
  S.room = id;
  store.set('room', id);
  history.replaceState(null, '', '#phong-' + id);
  render();
}

export function homePage(v, _id, opts = {}) {
  if (!S.rooms || !S.devices || !S.slaves) return skel(v);
  if (!S.rooms.length) {
    v.innerHTML = `<section class="card center" style="padding:40px 20px;gap:16px"><span class="muted">${ic('home')}</span>
      <h2>Bắt đầu bằng việc tạo phòng</h2><p class="muted">Mỗi phòng có một hoặc nhiều bộ phát ESP8266 và các thiết bị trong phòng đó.</p>
      <button type="button" class="btn pri big full" id="nr">Tạo phòng đầu tiên</button></section>`;
    $('#nr', v).onclick = addRoom;
    return;
  }
  const want = cur().room;
  if (want && want !== S.room && S.rooms.some(by('id', want))) { S.room = want; store.set('room', want); }
  if (!S.rooms.some(by('id', S.room))) S.room = S.rooms[0].id;

  const devs = S.devices.filter(by('room_id', S.room));
  const card = (d) => {
    const t = typeInfo(d.type), sl = slaveForDevice(d), off = !sl || !sl.online;
    const sub = [d.brand || t.label, d.command_count ? d.command_count + ' nút' : 'chưa có nút'];
    return `<div class="dev${opts.selected === d.id ? ' sel' : ''}${off ? ' off' : ''}">` +
      `<a class="dev-link" href="#tb-${d.id}" aria-label="Mở remote ${esc(d.name)}"${opts.selected === d.id ? ' aria-current="true"' : ''}></a>` +
      `<span class="dico">${ic(t.icon)}</span><span><b>${esc(d.name)}</b><span class="small muted">${esc(sub.join(' · '))}</span>` +
      `<span class="small dtemp" data-temp-of="${d.id}">${esc(tempText(d.temp))}</span>` +
      (off ? '<span class="small" style="color:var(--danger)">Bộ phát mất kết nối</span>' : '') + '</span>' +
      (d.power_command_id ? `<button type="button" class="qp" data-pw="${d.id}" aria-label="Nguồn ${esc(d.name)}"${off ? ' aria-disabled="true"' : ''}>${ic('power')}</button>` : '') +
      '</div>';
  };
  const showVoice = S.voice && !store.get('hideVoice', false);
  v.innerHTML = (showVoice ? '<section class="vc" id="vc" aria-live="polite" aria-label="Giọng nói"></section>' : '') +
    '<div class="chips" role="group" aria-label="Chọn phòng">' +
    S.rooms.map((r) => `<button type="button" class="chip" data-room="${r.id}" aria-pressed="${r.id === S.room}">${esc(r.name)}</button>`).join('') + '</div>' +
    slaveLine(S.room) +
    (devs.length
      ? `<div class="devs">${devs.map(card).join('')}</div><a class="btn sm dash addev" href="#them-tb">${ic('plus')}Thêm thiết bị</a>`
      : `<section class="card center" style="padding:28px 16px"><p class="muted">Phòng này chưa có thiết bị.</p><a class="btn pri addev" href="#them-tb">${ic('plus')}Thêm thiết bị</a></section>`) +
    (S.scenes && S.scenes.length
      ? '<h2 class="sec">Ngữ cảnh</h2><div class="chips wrap" role="group" aria-label="Chạy ngữ cảnh">' +
        S.scenes.map((sc) => `<button type="button" class="chip" data-scene="${sc.id}">${ic('play')}${esc(sc.name)}</button>`).join('') + '</div>'
      : '');
  if (showVoice) paintVoice();
  $$('[data-scene]', v).forEach((b) => { b.onclick = () => runSceneConfirm(S.scenes.find(by('id', +b.dataset.scene)), b); });
  $$('[data-room]', v).forEach((b) => { b.onclick = () => selectRoom(+b.dataset.room); });
  $$('[data-pw]', v).forEach((b) => { b.onclick = () => quickPower(b, S.devices.find(by('id', +b.dataset.pw))); });
  $$('a.addev', v).forEach((a) => { a.onclick = () => { S.formRoom = S.room; }; });
}

/** Nút Nguồn trên thẻ thiết bị: gửi ngay, không cần mở remote */
async function quickPower(btn, d) {
  if (btn.getAttribute('aria-disabled') === 'true') { buzz(false); return toast(`Bộ phát của ${d.name} đang mất kết nối`, 'err'); }
  if (btn.classList.contains('is-sending')) return;
  btn.classList.add('is-sending');
  try {
    const r = await api('POST', '/api/send', { command_id: d.power_command_id }, 6000);
    buzz(true);
    btn.classList.add('done');
    setTimeout(() => btn.classList.remove('done'), 1200);
    toast(`Đã gửi Nguồn tới ${d.name} · ${r.latency_ms} ms`);
  } catch (e) {
    buzz(false);
    handleErr(e);
  } finally {
    btn.classList.remove('is-sending');
  }
}

/** Màn hình rộng: danh sách thiết bị và remote cạnh nhau. r = cur() */
export function splitPage(v, r) {
  const id = r.name === 'tb' ? r.id : null;
  if (id && S.devices) {
    const d = S.devices.find(by('id', id));
    if (d) S.room = d.room_id;
  }
  v.innerHTML = '<div class="split"><div class="split-l" id="spl"></div><div class="split-r" id="spr"></div></div>';
  const left = $('#spl', v), right = $('#spr', v);
  homePage(left, null, { selected: id });
  if (id) remotePage(right, id, { embedded: true });
  else right.innerHTML = `<section class="card center pane-empty"><span class="muted">${ic('remote')}</span><p class="muted">Chọn một thiết bị bên trái để mở remote.</p></section>`;
}
