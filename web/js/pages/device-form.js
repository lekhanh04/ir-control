// Thêm / sửa thiết bị: loại, tên, hãng, phòng, bộ phát. Thêm xong chuyển thẳng sang remote ở chế độ học nút.
import { api } from '../api.js';
import { $, $$, by, esc, ic, toast, dialog } from '../util.js';
import { S, store, skel, loadBase, handleErr, slavesIn, typeInfo } from '../state.js';
import { go, setHeader } from '../router.js';

export function deviceFormPage(v, id) {
  const d = id ? (S.devices || []).find(by('id', id)) : null;
  if (id) setHeader({ title: 'Sửa thiết bị', back: d ? 'tb-' + id : 'quan-ly' });
  if (!S.rooms || !S.devices || !S.types) return skel(v);
  if (id && !d) { v.innerHTML = '<p class="muted">Thiết bị này không còn.</p>'; return; }
  let type = d ? d.type : S.formType || S.types[0].code;
  let room = d ? d.room_id : S.formRoom || S.room;
  let slave = d ? d.slave_id || '' : '';
  v.innerHTML = '<form class="card" id="df" novalidate style="gap:16px">' +
    '<fieldset class="field"><legend class="lab" style="margin-bottom:8px">Loại thiết bị</legend><div class="types">' +
    S.types.map(({ code }) => { const t = typeInfo(code); return `<button type="button" class="type" data-type="${esc(code)}" aria-pressed="${code === type}">${ic(t.icon)}${esc(t.label)}</button>`; }).join('') + '</div></fieldset>' +
    `<div class="field"><label for="dn">Tên thiết bị</label><input id="dn" class="inp" maxlength="30" value="${esc(d ? d.name : typeInfo(type).label)}"></div>` +
    `<div class="field"><label for="db">Hãng <span class="muted">(không bắt buộc)</span></label><input id="db" class="inp" maxlength="24" value="${esc(d ? d.brand : '')}" placeholder="VD: Samsung"></div>` +
    '<fieldset class="field"><legend class="lab" style="margin-bottom:8px">Phòng</legend><div class="chips wrap">' +
    S.rooms.map((r) => `<button type="button" class="chip" data-room="${r.id}" aria-pressed="${r.id === room}">${esc(r.name)}</button>`).join('') +
    '</div></fieldset><div class="field" id="sf"></div>' +
    `<p class="err" id="de" role="alert"></p><button class="btn pri big full">${d ? 'Lưu' : 'Thêm và học nút'}</button></form>` +
    (d ? '<button type="button" class="btn dng full" id="del">Xóa thiết bị</button>' : '');

  const nm = $('#dn', v);
  let nameEdited = !!d;
  // Bộ phát: "Tự động" = dùng bộ phát của phòng (ưu tiên bộ đang hoạt động); hoặc chọn riêng khi phòng có nhiều bộ
  const showSlave = () => {
    const list = slavesIn(room), box = $('#sf', v);
    if (!list.some(by('id', slave))) slave = '';
    const st = (s) => (s.online ? '' : ' (mất kết nối)');
    if (!list.length) { box.innerHTML = '<p class="hint">Phòng này chưa có bộ phát ESP8266. <a href="#bo-phat">Gán bộ phát</a></p>'; return; }
    if (list.length === 1) { box.innerHTML = `<p class="hint">Lệnh sẽ phát qua ${esc(list[0].name)}${st(list[0])}.</p>`; return; }
    box.innerHTML = '<label for="ds">Phát qua bộ phát</label><select id="ds" class="inp">' +
      `<option value="">Tự động (bộ đang hoạt động trong phòng)</option>` +
      list.map((s) => `<option value="${esc(s.id)}"${s.id === slave ? ' selected' : ''}>${esc(s.name)}${st(s)}</option>`).join('') + '</select>' +
      '<p class="hint">Chọn riêng khi bộ phát chỉ chiếu tới được thiết bị này.</p>';
    $('#ds', box).onchange = (e) => { slave = e.target.value; };
  };
  showSlave();
  nm.oninput = () => { nameEdited = true; };
  $$('[data-type]', v).forEach((b) => {
    b.onclick = () => {
      type = b.dataset.type; S.formType = type;
      $$('[data-type]', v).forEach((x) => x.setAttribute('aria-pressed', x === b));
      if (!nameEdited) nm.value = typeInfo(type).label;
    };
  });
  $$('[data-room]', v).forEach((b) => {
    b.onclick = () => { room = +b.dataset.room; $$('[data-room]', v).forEach((x) => x.setAttribute('aria-pressed', x === b)); showSlave(); };
  });
  $('#df', v).onsubmit = async (e) => {
    e.preventDefault();
    const body = { name: nm.value.trim(), brand: $('#db', v).value.trim(), type, room_id: room, slave_id: slave || null };
    if (!body.name) { $('#de', v).textContent = 'Nhập tên thiết bị.'; nm.focus(); return; }
    try {
      const x = await api(d ? 'PATCH' : 'POST', d ? '/api/devices/' + d.id : '/api/devices', body);
      S.formRoom = S.formType = null;
      S.room = room; store.set('room', room);
      await loadBase();
      if (d) { toast('Đã lưu'); go('tb-' + d.id); } else { toast(`Đã thêm “${body.name}”`); S.edit = true; go('tb-' + x.id); }
    } catch (err) {
      if (err.code === 'name_exists') { $('#de', v).textContent = 'Phòng này đã có thiết bị cùng tên. Đặt tên khác.'; nm.focus(); }
      else handleErr(err);
    }
  };
  const del = $('#del', v);
  if (del) del.onclick = () => dialog({
    title: `Xóa “${d.name}”?`, body: `Xóa cả ${d.command_count || 0} nút đã học. Lịch sử điều khiển vẫn được giữ.`,
    actions: [{ label: 'Hủy' }, { label: 'Xóa', dng: true, run: async () => {
      try { await api('DELETE', '/api/devices/' + d.id); toast('Đã xóa thiết bị'); await loadBase(); go('quan-ly'); } catch (e) { handleErr(e); }
    } }],
  });
}
