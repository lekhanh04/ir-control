// Remote của một thiết bị: chọn lệnh, gửi, xem ACK; chế độ "Sửa nút" để học/đổi tên/xóa/tạo nút.
import { api } from '../api.js';
import { $, $$, by, esc, ic, toast, say, dialog } from '../util.js';
import { S, skel, loadBase, loadCmds, handleErr, roomName, slaveForDevice, deviceSlaveLine, typeInfo } from '../state.js';
import { KEY_LABEL } from '../types.js';
import { cur, render, setHeader } from '../router.js';
import { startLearnFor } from './learn.js';

export function remotePage(v, id) {
  if (!S.devices) { setHeader({ title: 'Thiết bị', back: '' }); return skel(v); }
  const d = S.devices.find(by('id', id));
  if (!d) { setHeader({ title: 'Không tìm thấy', back: '' }); v.innerHTML = '<p class="muted">Thiết bị này không còn.</p>'; return; }
  const t = typeInfo(d.type);
  setHeader({ title: d.name, sub: roomName(d.room_id), back: '',
    right: `<button type="button" class="btn sm${S.edit ? ' pri' : ''}" id="edt" aria-pressed="${S.edit}">${S.edit ? 'Xong' : 'Sửa nút'}</button>` });
  $('#edt').onclick = () => { S.edit = !S.edit; render(); };

  const cmds = S.cmds[id];
  if (!cmds) {
    skel(v, 2);
    loadCmds(id).then(() => { const c = cur(); if (c.name === 'tb' && c.id === id) render(); }, handleErr);
    return;
  }
  const sl = slaveForDevice(d), offline = !sl || !sl.online, edit = S.edit;
  S.fbDev = d.id;
  const byKey = Object.fromEntries(cmds.map((c) => [c.key, c]));

  // Một nút: đã học → gửi (hoặc quản lý khi đang sửa); chưa học → ẩn (hoặc ô viền đứt khi đang sửa)
  const keyBtn = (key, cls = '', inner) => {
    const c = byKey[key], label = c ? c.label : KEY_LABEL[key] || key;
    if (!c && !edit) return '';
    if (!c) return `<button type="button" class="rk empty ${cls}" data-learn="${key}" aria-label="Học nút ${esc(label)}">${ic('plus')}<span>${esc(label)}</span></button>`;
    return `<button type="button" class="rk ${cls}" ${edit ? `data-manage="${c.id}"` : `data-cmd="${c.id}"`} aria-label="${esc(label)}">` +
      (inner || `<span>${esc(label)}</span>`) + (edit ? `<span class="ed">${ic('pen')}</span>` : '') + '</button>';
  };
  const any = (keys) => edit || keys.some((k) => byKey[k]);

  let html = '';
  for (const g of t.groups) {
    if (!any(g.keys)) continue;
    if (g.kind === 'top') html += '<div class="rtop">' + g.keys.map((k) => (k === 'power' ? keyBtn(k, 'pw', ic('power') + '<span>Nguồn</span>') : keyBtn(k))).join('') + '</div>';
    if (g.kind === 'pair') html += '<div class="pair">' + (keyBtn(g.keys[0], '', ic('minus')) || '<span></span>') + `<span class="t">${esc(g.title)}</span>` + (keyBtn(g.keys[1], '', ic('plus')) || '<span></span>') + '</div>';
    if (g.kind === 'dpad') {
      const arrow = { up: ic('up'), down: ic('down'), left: ic('left'), right: ic('chev') };
      const cell = (k) => keyBtn(k, k === 'ok' ? 'okk' : '', arrow[k] || '<span>OK</span>') || '<span></span>';
      html += `<div class="dpad"><span></span>${cell('up')}<span></span>${cell('left')}${cell('ok')}${cell('right')}<span></span>${cell('down')}<span></span></div>`;
    }
    if (g.kind === 'grid') html += '<div class="kgrid">' + g.keys.map((k) => keyBtn(k)).join('') + '</div>';
  }
  const custom = cmds.filter((c) => !t.groups.some((g) => g.keys.includes(c.key)));
  if (custom.length || edit) {
    html += '<div class="rsec"><span class="lbl">Nút tự tạo</span><div class="kgrid">' + custom.map((c) => keyBtn(c.key)).join('') +
      (edit ? `<button type="button" class="rk empty" id="newkey">${ic('plus')}<span>Tạo nút mới</span></button>` : '') + '</div></div>';
  }

  v.innerHTML = deviceSlaveLine(d) +
    (edit ? `<div class="note">${ic('pen')}<span>Chạm nút viền đứt để học mã từ remote. Chạm nút đã có để học lại, đổi tên hoặc xóa.</span></div>`
      : '<p class="fb" id="fb" aria-live="polite"></p>') +
    (!cmds.length && !edit
      ? `<section class="card center" style="padding:32px 16px"><span class="muted">${ic(t.icon)}</span><h2>Chưa có nút nào</h2>
         <p class="muted small">Học nút đầu tiên từ remote gốc của ${esc(d.name.toLowerCase())}.</p><button type="button" class="btn pri big full" id="startedit">Học nút</button></section>`
      : `<section class="card remote" aria-label="Remote ${esc(d.name)}">${html}</section>`) +
    (edit ? `<a class="btn full" href="#sua-tb-${d.id}">${ic('pen')}Sửa thông tin thiết bị</a>` : '');
  paintFb();

  $$('[data-cmd]', v).forEach((b) => {
    if (offline) b.setAttribute('aria-disabled', 'true');
    b.onclick = () => (offline ? toast('Bộ phát của thiết bị này đang mất kết nối') : send(b, +b.dataset.cmd, d));
  });
  $$('[data-learn]', v).forEach((b) => { b.onclick = () => startLearnFor(d, b.dataset.learn, KEY_LABEL[b.dataset.learn], false); });
  $$('[data-manage]', v).forEach((b) => { b.onclick = () => manageKey(d, cmds.find(by('id', +b.dataset.manage))); });
  const nk = $('#newkey', v);
  if (nk) nk.onclick = () => dialog({
    title: 'Tạo nút mới', input: { label: 'Tên nút, ví dụ “Netflix”, “Chế độ ngủ”', max: 20 },
    actions: [{ label: 'Hủy' }, { label: 'Tiếp tục học mã', pri: true, submit: true, check: (name) => labelTaken(cmds, name), run: (name) => {
      let n = 1;
      while (cmds.some(by('key', 'custom_' + n))) n++;
      startLearnFor(d, 'custom_' + n, name, false);
    } }],
  });
  const se = $('#startedit', v);
  if (se) se.onclick = () => { S.edit = true; render(); };
}

/** Tên nút trùng (không phân biệt hoa thường, kể cả chữ có dấu) → thông báo lỗi */
function labelTaken(cmds, name, skipId) {
  const n = name.toLocaleLowerCase('vi');
  return cmds.some((c) => c.id !== skipId && c.label.toLocaleLowerCase('vi') === n) ? `Thiết bị đã có nút “${name}”.` : '';
}

function manageKey(d, c) {
  const info = c.kind === 'protocol' ? `Giao thức ${c.protocol} · mã ${c.value}` : `Mã RAW · ${c.raw_len} xung`;
  dialog({ title: `Nút “${c.label}”`, body: esc(info), actions: [
    { label: 'Xóa', dng: true, run: () => dialog({ title: `Xóa nút “${c.label}”?`, body: 'Mã IR đã học của nút này sẽ bị xóa.', actions: [
      { label: 'Hủy' },
      { label: 'Xóa', dng: true, run: () => api('DELETE', '/api/commands/' + c.id).then(() => { toast('Đã xóa nút'); delete S.cmds[d.id]; return loadBase(); }).then(render, handleErr) },
    ] }) },
    { label: 'Đổi tên', run: () => dialog({ title: 'Đổi tên nút', input: { label: 'Tên nút', value: c.label, max: 20 }, actions: [
      { label: 'Hủy' },
      { label: 'Lưu', pri: true, submit: true, check: (name) => labelTaken(S.cmds[d.id] || [], name, c.id), run: (name) => api('PATCH', '/api/commands/' + c.id, { label: name }).then(() => { c.label = name; render(); }, handleErr) },
    ] }) },
    { label: 'Học lại', pri: true, run: () => startLearnFor(d, c.key, c.label, true) },
  ] });
}

// ----- Gửi lệnh: Pi tra mã → MQTT → ESP8266 phát → ACK. Phản hồi hiển thị theo ACK thật. -----
function locked(btn) {
  const n = Date.now();
  if (btn._lock && n < btn._lock) return true;
  btn._lock = n + 350;   // chống bấm lặp
  return false;
}

function paintFb() {
  const f = $('#fb');
  if (!f) return;
  const s = S.fb && S.fb.dev === S.fbDev ? S.fb : null;
  f.className = 'fb';
  if (!s) { f.innerHTML = '<span>Chạm một nút để gửi lệnh</span>'; return; }
  if (s.state === 'busy') f.innerHTML = `<span class="d" aria-hidden="true"></span>Đang gửi “${esc(s.label)}” tới bộ phát…`;
  else if (s.state === 'ok') { f.classList.add('ok'); f.innerHTML = `${ic('check')}<span>Bộ phát đã phát “${esc(s.label)}” · ${s.ms} ms</span>`; }
  else {
    f.classList.add('bad');
    f.innerHTML = `${ic('alert')}<span class="grow">${esc(s.msg)}</span><button type="button" class="btn sm" id="fbr">Thử lại</button>`;
    $('#fbr', f).onclick = s.retry;
  }
}

const SEND_MSG = {
  slave_offline: 'Bộ phát của thiết bị đang mất kết nối.',
  no_ack: 'Bộ phát không xác nhận sau 3 giây.',
  slave_error: 'Bộ phát báo lỗi khi phát lệnh.',
  busy: 'Bộ phát đang bận, thử lại.',
};

async function send(btn, cmdId, d) {
  if (btn && locked(btn)) return;
  const c = (S.cmds[d.id] || []).find(by('id', cmdId));
  const label = c ? c.label : '';
  S.fb = { dev: d.id, state: 'busy', label };
  paintFb();
  if (btn) btn.classList.add('is-sending');
  try {
    const r = await api('POST', '/api/send', { command_id: cmdId }, 6000);
    S.fb = { dev: d.id, state: 'ok', label, ms: r.latency_ms };
    say('Đã phát ' + label);
  } catch (e) {
    const msg = SEND_MSG[e.code] || (e.status === 0 ? 'Không kết nối được bộ trung tâm.' : e.message);
    S.fb = { dev: d.id, state: 'bad', msg, retry: () => send(null, cmdId, d) };
    if (e.code === 'slave_offline') api('GET', '/api/slaves').then((l) => { S.slaves = l; });
  } finally {
    if (btn) btn.classList.remove('is-sending');
    paintFb();
  }
}
