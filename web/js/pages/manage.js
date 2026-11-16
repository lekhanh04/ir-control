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

export function managePage(v) {
  if (!S.rooms || !S.devices || !S.slaves) return skel(v);
  const free = S.slaves.filter((s) => s.room_id === null).length;
  const on = S.slaves.filter((s) => s.online).length;
  v.innerHTML = '<h2 class="sec">Phòng và thiết bị</h2>' +
    S.rooms.map((r) => {
      const devs = S.devices.filter(by('room_id', r.id));
      return `<section class="card" style="padding:0;gap:0;overflow:hidden"><div class="row" style="padding:14px 8px 10px 16px">
          <div class="grow"><b>${esc(r.name)}</b>${slaveLine(r.id, 'margin:2px 0 0')}</div>
          <button type="button" class="iconbtn" data-room-menu="${r.id}" aria-label="Tùy chọn phòng ${esc(r.name)}">${ic('pen')}</button></div>
        <div class="list" style="border:0;border-top:1px solid var(--line);border-radius:0">` +
        devs.map((d) => { const t = typeInfo(d.type); return `<a href="#sua-tb-${d.id}">${ic(t.icon)}<span class="grow"><b>${esc(d.name)}</b><br><span class="small muted">${esc(t.label)}${d.brand ? ' · ' + esc(d.brand) : ''} · ${d.command_count || 0} nút</span></span>${ic('chev')}</a>`; }).join('') +
        `<a href="#them-tb" data-add-room="${r.id}" style="color:var(--text-muted)">${ic('plus')}<span class="grow">Thêm thiết bị vào ${esc(r.name.toLowerCase())}</span></a></div></section>`;
    }).join('') +
    `<button type="button" class="btn full dash" id="addroom">${ic('plus')}Thêm phòng</button>` +
    '<h2 class="sec">Hệ thống</h2><nav class="list" aria-label="Hệ thống">' +
    row('bo-phat', 'Bộ phát ESP8266', `${on}/${S.slaves.length} đang hoạt động${free ? ` · ${free} chưa gán phòng` : ''}`, free ? '<span class="badge warn">Mới</span>' : '') +
    (S.voice ? row('giong-noi', 'Giọng nói', S.voice.module === 'missing' ? 'Chưa thấy module giọng nói' : S.voice.enabled ? 'Đang nghe' : 'Đang tắt') : '') +
    row('he-thong', 'Bộ trung tâm Raspberry Pi', 'MQTT, mắt thu IR, bộ nhớ, sao lưu') + '</nav>';
  $('#addroom', v).onclick = addRoom;
  $$('[data-add-room]', v).forEach((a) => { a.onclick = () => { S.formRoom = +a.dataset.addRoom; }; });
  $$('[data-room-menu]', v).forEach((b) => { b.onclick = () => roomMenu(S.rooms.find(by('id', +b.dataset.roomMenu))); });
}
