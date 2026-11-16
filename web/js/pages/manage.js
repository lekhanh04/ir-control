// Quản lý: phòng và thiết bị trong từng phòng; lối vào bộ phát, giọng nói, hệ thống.
import { api } from '../api.js';
import { $, $$, by, esc, ic, toast, dialog } from '../util.js';
import { S, store, skel, loadBase, handleErr, slaveLine , typeInfo } from '../state.js';
import { render } from '../router.js';

const row = (href, title, sub, extra = '') =>
  `<a href="#${href}"><span class="grow"><b>${title}</b>${sub ? `<br><span class="small muted">${sub}</span>` : ''}</span>${extra}${ic('chev')}</a>`;

export function addRoom() {
  dialog({ title: 'Thêm phòng', input: { label: 'Tên phòng', max: 24 }, actions: [
    { label: 'Hủy' },
    { label: 'Thêm', pri: true, submit: true, run: async (name) => {
      try {
        const r = await api('POST', '/api/rooms', { name });
        toast(`Đã thêm “${name}”`);
        S.room = r.id; store.set('room', r.id);
        await loadBase(); render();
      } catch (e) { handleErr(e); }
    } },
  ] });
}

function roomMenu(r) {
  dialog({ title: r.name, actions: [
    { label: 'Xóa phòng', dng: true, run: () => dialog({
      title: `Xóa “${r.name}”?`, body: 'Chỉ xóa được phòng không còn thiết bị. Bộ phát của phòng sẽ chuyển sang “chưa gán phòng”.',
      actions: [{ label: 'Hủy' }, { label: 'Xóa', dng: true, run: async () => {
        try { await api('DELETE', '/api/rooms/' + r.id); toast('Đã xóa phòng'); await loadBase(); render(); }
        catch (e) { toast(e.code === 'not_empty' ? 'Phòng còn thiết bị, hãy chuyển hoặc xóa thiết bị trước' : e.message); }
      } }],
    }) },
    { label: 'Đổi tên', pri: true, run: () => dialog({ title: 'Đổi tên phòng', input: { label: 'Tên phòng', value: r.name, max: 24 }, actions: [
      { label: 'Hủy' },
      { label: 'Lưu', pri: true, submit: true, run: (name) => api('PATCH', '/api/rooms/' + r.id, { name }).then(loadBase).then(render, handleErr) },
    ] }) },
  ] });
}

/** Đổi chỗ phần tử i với i+dir trong danh sách id rồi lưu thứ tự lên bộ trung tâm */
function move(kind, ids, i, dir) {
  const j = i + dir;
  if (j < 0 || j >= ids.length) return;
  [ids[i], ids[j]] = [ids[j], ids[i]];
  api('PUT', '/api/order', { kind, ids }).then(loadBase).then(render, handleErr);
}

const arrows = (kind, idx, len, label) =>
  `<span class="sortbtns"><button type="button" class="iconbtn sm" data-mv="${kind}" data-i="${idx}" data-d="-1" aria-label="Chuyển ${esc(label)} lên"${idx ? '' : ' disabled'}>${ic('up')}</button>` +
  `<button type="button" class="iconbtn sm" data-mv="${kind}" data-i="${idx}" data-d="1" aria-label="Chuyển ${esc(label)} xuống"${idx < len - 1 ? '' : ' disabled'}>${ic('down')}</button></span>`;

export function managePage(v) {
  if (!S.rooms || !S.devices || !S.slaves) return skel(v);
  const sort = S.sortMode;
  const free = S.slaves.filter((s) => s.room_id === null).length;
  const on = S.slaves.filter((s) => s.online).length;
  v.innerHTML = '<div class="row" style="margin:8px 4px -8px"><h2 class="sec grow" style="margin:0">Phòng và thiết bị</h2>' +
    `<button type="button" class="btn sm${sort ? ' pri' : ' ghost'}" id="sortm" aria-pressed="${sort}">${sort ? 'Xong' : 'Sắp xếp'}</button></div>` +
    (sort ? '<p class="hint" style="margin:0 4px">Dùng mũi tên để đổi thứ tự phòng và thiết bị. Thứ tự lưu ở bộ trung tâm nên mọi máy đều thấy.</p>' : '') +
    S.rooms.map((r, ri) => {
      const devs = S.devices.filter(by('room_id', r.id));
      return `<section class="card" style="padding:0;gap:0;overflow:hidden"><div class="row" style="padding:14px 8px 10px 16px">
          <div class="grow"><b>${esc(r.name)}</b>${slaveLine(r.id, 'margin:2px 0 0')}</div>` +
        (sort ? arrows('room', ri, S.rooms.length, r.name) : `<button type="button" class="iconbtn" data-room-menu="${r.id}" aria-label="Tùy chọn phòng ${esc(r.name)}">${ic('pen')}</button>`) +
        '</div><div class="list" style="border:0;border-top:1px solid var(--line);border-radius:0">' +
        devs.map((d, di) => {
          const t = typeInfo(d.type);
          const inner = `${ic(t.icon)}<span class="grow"><b>${esc(d.name)}</b><br><span class="small muted">${esc(t.label)}${d.brand ? ' · ' + esc(d.brand) : ''} · ${d.command_count || 0} nút</span></span>`;
          return sort ? `<div data-room-of="${r.id}">${inner}${arrows('device:' + r.id, di, devs.length, d.name)}</div>` : `<a href="#sua-tb-${d.id}">${inner}${ic('chev')}</a>`;
        }).join('') +
        (sort ? '' : `<a href="#them-tb" data-add-room="${r.id}" style="color:var(--text-muted)">${ic('plus')}<span class="grow">Thêm thiết bị vào ${esc(r.name.toLowerCase())}</span></a>`) +
        '</div></section>';
    }).join('') +
    (sort ? '' : `<button type="button" class="btn full dash" id="addroom">${ic('plus')}Thêm phòng</button>`) +
    '<h2 class="sec">Tự động</h2><nav class="list" aria-label="Tự động">' +
    row('ngu-canh', 'Ngữ cảnh', S.scenes && S.scenes.length ? `${S.scenes.length} ngữ cảnh` : 'Một lần chạm, phát nhiều nút', ic('play')) +
    row('hen-gio', 'Hẹn giờ', 'Chạy ngữ cảnh hoặc nút vào giờ cố định', ic('clock')) + '</nav>' +
    '<h2 class="sec">Hệ thống</h2><nav class="list" aria-label="Hệ thống">' +
    row('bo-phat', 'Bộ phát ESP8266', `${on}/${S.slaves.length} đang hoạt động${free ? ` · ${free} chưa gán phòng` : ''}`, free ? '<span class="badge warn">Mới</span>' : '') +
    (S.voice ? row('giong-noi', 'Giọng nói', S.voice.module === 'missing' ? 'Chưa thấy module giọng nói' : S.voice.enabled ? 'Đang nghe' : 'Đang tắt') : '') +
    row('he-thong', 'Bộ trung tâm Raspberry Pi', 'MQTT, mắt thu IR, bộ nhớ, sao lưu') + '</nav>';
  const ar = $('#addroom', v);
  if (ar) ar.onclick = addRoom;
  $('#sortm', v).onclick = () => { S.sortMode = !S.sortMode; render(); };
  $$('[data-mv]', v).forEach((b) => {
    b.onclick = () => {
      const [kind, roomId] = b.dataset.mv.split(':');
      const ids = kind === 'room' ? S.rooms.map((r) => r.id) : S.devices.filter(by('room_id', +roomId)).map((d) => d.id);
      move(kind, ids, +b.dataset.i, +b.dataset.d);
    };
  });
  $$('[data-add-room]', v).forEach((a) => { a.onclick = () => { S.formRoom = +a.dataset.addRoom; }; });
  $$('[data-room-menu]', v).forEach((b) => { b.onclick = () => roomMenu(S.rooms.find(by('id', +b.dataset.roomMenu))); });
}
