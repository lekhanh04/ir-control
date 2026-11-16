// Bộ phát ESP8266: gán phòng (một phòng có thể có nhiều bộ), nháy đèn nhận biết, đổi tên, xóa bộ không dùng nữa.
// Bộ phát mới tự xuất hiện khi gửi status lên MQTT.
import { api } from '../api.js';
import { $$, by, esc, ic, ago, bars, toast, dialog } from '../util.js';
import { S, skel, loadBase, handleErr, roomName, slavesIn } from '../state.js';
import { render } from '../router.js';

export function slavesPage(v) {
  if (!S.slaves || !S.rooms) return skel(v);
  const list = S.slaves.slice().sort((a, b) => (a.room_id === null ? -1 : 0) - (b.room_id === null ? -1 : 0));
  v.innerHTML = '<p class="hint" style="margin:0 4px">Phòng rộng hoặc có vật che có thể đặt nhiều bộ phát ESP8266; thiết bị sẽ tự dùng bộ đang hoạt động, hoặc bạn chọn riêng trong phần sửa thiết bị. Bộ phát mới bật lên trong mạng sẽ tự xuất hiện ở đây.</p>' +
    (list.length ? '' : '<section class="card center"><p class="muted">Chưa có bộ phát nào kết nối tới MQTT broker.</p></section>') +
    list.map((s) => `<section class="card"><div class="row"><span class="muted">${ic('chip')}</span>
        <div class="grow"><b>${esc(s.name)}</b><br><span class="small muted">${esc(s.id)}${s.ip ? ' · ' + esc(s.ip) : ''}${s.fw ? ' · firmware ' + esc(s.fw) : ''}</span></div>` +
      (s.room_id === null ? '<span class="badge warn">Chưa gán phòng</span>' : s.online ? '<span class="badge ok"><span class="dot ok"></span>Hoạt động</span>' : '<span class="badge bad"><span class="dot bad"></span>Mất kết nối</span>') + '</div>' +
      `<div class="row small muted">${s.online ? `${s.rssi != null ? bars(s.rssi) + `<span>Wi-Fi ${s.rssi} dBm</span>` : '<span>Đang hoạt động</span>'}` : `<span>Lần cuối thấy: ${s.last_seen ? ago(s.last_seen) : 'chưa rõ'}</span>`}</div>` +
      `<div class="field"><label for="sr-${esc(s.id)}">Đặt ở phòng</label><select id="sr-${esc(s.id)}" class="inp" data-assign="${esc(s.id)}"><option value="">Chưa gán phòng</option>` +
      S.rooms.map((r) => { const n = slavesIn(r.id).filter((x) => x.id !== s.id).length; return `<option value="${r.id}"${s.room_id === r.id ? ' selected' : ''}>${esc(r.name)}${n ? ` (đã có ${n} bộ)` : ''}</option>`; }).join('') + '</select></div>' +
      `<div class="row"><button type="button" class="btn sm" data-identify="${esc(s.id)}"${s.online ? '' : ' disabled'}>Nháy đèn để nhận biết</button><button type="button" class="btn sm ghost" data-rename="${esc(s.id)}">Đổi tên</button>` +
      (s.online ? '' : `<button type="button" class="btn sm ghost" style="color:var(--danger)" data-remove="${esc(s.id)}">Xóa</button>`) + '</div></section>').join('');

  $$('[data-assign]', v).forEach((sel) => {
    sel.onchange = async () => {
      const rid = sel.value ? +sel.value : null;
      try { await api('PATCH', '/api/slaves/' + sel.dataset.assign, { room_id: rid }); toast(rid ? 'Đã gán vào ' + roomName(rid) : 'Đã bỏ gán phòng'); await loadBase(); render(); }
      catch (e) { handleErr(e); }
    };
  });
  $$('[data-identify]', v).forEach((b) => {
    b.onclick = () => api('POST', `/api/slaves/${b.dataset.identify}/identify`).then(() => toast('Đèn trên bộ phát đang nháy 5 giây'), handleErr);
  });
  $$('[data-remove]', v).forEach((b) => {
    b.onclick = () => {
      const s = S.slaves.find(by('id', b.dataset.remove));
      const pinned = (S.devices || []).filter((d) => d.slave_id === s.id).length;
      dialog({ title: `Xóa “${s.name}”?`,
        body: 'Dùng khi bộ phát đã tháo ra hoặc thay mới. Nếu bật lại, nó sẽ tự xuất hiện như bộ phát mới.' + (pinned ? ` ${pinned} thiết bị đang gán riêng bộ này sẽ chuyển về “Tự động”.` : ''),
        actions: [{ label: 'Hủy' }, { label: 'Xóa', dng: true, run: () => api('DELETE', '/api/slaves/' + s.id).then(() => { toast('Đã xóa bộ phát'); return loadBase(); }).then(render, handleErr) }] });
    };
  });
  $$('[data-rename]', v).forEach((b) => {
    b.onclick = () => {
      const s = S.slaves.find(by('id', b.dataset.rename));
      dialog({ title: 'Đổi tên bộ phát', input: { label: 'Tên', value: s.name, max: 30 }, actions: [
        { label: 'Hủy' },
        { label: 'Lưu', pri: true, submit: true, run: (name) => api('PATCH', '/api/slaves/' + s.id, { name }).then(loadBase).then(render, handleErr) },
      ] });
    };
  });
}
