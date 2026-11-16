// Remote của một thiết bị: chọn lệnh, gửi, xem ACK; chế độ "Sửa nút" để học/đổi tên/xóa/tạo nút.
import { api } from '../api.js';
import { $, $$, by, esc, ic, toast, say, dialog, buzz } from '../util.js';
import { S, skel, loadBase, loadCmds, handleErr, roomName, slaveForDevice, deviceSlaveLine, typeInfo } from '../state.js';
import { KEY_LABEL } from '../types.js';
import { cur, render, setHeader } from '../router.js';
import { startLearnFor } from './learn.js';

export const tempText = (t) => (t == null ? '' : t + ' °C');

/** Nhiệt độ ước tính vừa đổi (từ chính máy này hoặc sự kiện SSE): cập nhật chữ tại chỗ, không vẽ lại cả trang
 *  (vẽ lại sẽ làm đứt thao tác đang giữ nút Nhiệt độ +). */
export function updateTemp(id, temp) {
  const d = (S.devices || []).find(by('id', id));
  if (d) d.temp = temp;
  $$(`[data-temp-of="${id}"]`).forEach((el) => { el.textContent = tempText(temp) || (el.closest('.tempbtn') ? '— °C' : ''); });
}

/** opts.embedded: vẽ trong khung bên phải của màn hình rộng (không đổi thanh tiêu đề) */
export function remotePage(v, id, opts = {}) {
  const emb = !!opts.embedded;
  if (!S.devices) { if (!emb) setHeader({ title: 'Thiết bị', back: '' }); return skel(v); }
  const d = S.devices.find(by('id', id));
  if (!d) { if (!emb) setHeader({ title: 'Không tìm thấy', back: '' }); v.innerHTML = '<p class="muted">Thiết bị này không còn.</p>'; return; }
  const t = typeInfo(d.type);
  const editBtn = `<button type="button" class="btn sm${S.edit ? ' pri' : ''}" id="edt" aria-pressed="${S.edit}">${S.edit ? 'Xong' : 'Sửa nút'}</button>`;
  const toggleEdit = () => { S.edit = !S.edit; render(); };
  if (!emb) {
    setHeader({ title: d.name, sub: roomName(d.room_id), back: 'phong-' + d.room_id, right: editBtn });
    $('#edt').onclick = toggleEdit;
  }

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
    if (g.kind === 'pair') {
      // Cặp nhiệt độ: hiện nhiệt độ ước tính ở giữa, chạm để đặt lại
      const mid = g.keys.includes('temp_up') && !edit && (byKey.temp_up || byKey.temp_down)
        ? `<button type="button" class="t tempbtn" data-settemp aria-label="Đặt nhiệt độ ${esc(d.name)} đang để"><b data-temp-of="${d.id}">${tempText(d.temp) || '— °C'}</b><span>${esc(g.title)}${d.temp == null ? ' · chạm để đặt' : ''}</span></button>`
        : `<span class="t">${esc(g.title)}</span>`;
      html += '<div class="pair">' + (keyBtn(g.keys[0], '', ic('minus')) || '<span></span>') + mid + (keyBtn(g.keys[1], '', ic('plus')) || '<span></span>') + '</div>';
    }
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

  const paneHead = emb ? `<div class="pane-h"><div class="grow"><h2>${esc(d.name)}</h2><span class="small muted">${esc(roomName(d.room_id))}</span></div>${editBtn}</div>` : '';
  v.innerHTML = paneHead + deviceSlaveLine(d) +
    (edit ? `<div class="note">${ic('pen')}<span>Chạm nút viền đứt để học mã từ remote. Chạm nút đã có để học lại, đổi tên hoặc xóa.</span></div>`
      : '<p class="fb" id="fb" aria-live="polite"></p>') +
    (!cmds.length && !edit
      ? `<section class="card center" style="padding:32px 16px"><span class="muted">${ic(t.icon)}</span><h2>Chưa có nút nào</h2>
         <p class="muted small">Học nút đầu tiên từ remote gốc của ${esc(d.name.toLowerCase())}.</p><button type="button" class="btn pri big full" id="startedit">Học nút</button></section>`
      : `<section class="card remote" aria-label="Remote ${esc(d.name)}">${html}</section>`) +
    (edit ? `<a class="btn full" href="#sua-tb-${d.id}">${ic('pen')}Sửa thông tin thiết bị</a>` : '');
  paintFb();
  if (emb) $('#edt', v).onclick = toggleEdit;
  const st = $('[data-settemp]', v);
  if (st) st.onclick = () => setTemp(d);

  $$('[data-cmd]', v).forEach((b) => {
    const c = cmds.find(by('id', +b.dataset.cmd));
    if (offline) b.setAttribute('aria-disabled', 'true');
    b.onclick = () => {
      if (b._skipClick) { b._skipClick = false; return; }   // vừa nhả tay sau khi giữ để lặp
      if (offline) { buzz(false); toast('Bộ phát của thiết bị này đang mất kết nối', 'err'); } else send(b, c.id, d);
    };
    if (!offline && REPEAT.has(c.key)) holdToRepeat(b, c.id, d);
  });
  $$('[data-learn]', v).forEach((b) => { b.onclick = () => startLearnFor(d, b.dataset.learn, KEY_LABEL[b.dataset.learn], false); });
  $$('[data-manage]', v).forEach((b) => { b.onclick = () => manageKey(d, cmds.find(by('id', +b.dataset.manage)), custom); });
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

function setTemp(d) {
  dialog({
    title: `${d.name} đang để bao nhiêu độ?`,
    body: 'Hồng ngoại không báo ngược nhiệt độ. Nhập số đang hiện trên điều hòa; sau đó mỗi lần gửi Nhiệt độ +/− thành công (từ web, giọng nói, ngữ cảnh, hẹn giờ) sẽ tự cộng/trừ 1.',
    input: { label: 'Nhiệt độ (16–30 °C)', value: String(d.temp == null ? 25 : d.temp), max: 2 },
    actions: [
      { label: 'Không theo dõi', run: () => saveTemp(d, null) },
      { label: 'Lưu', pri: true, submit: true, check: (x) => (/^\d{2}$/.test(x) && +x >= 16 && +x <= 30 ? '' : 'Nhập số từ 16 đến 30.'), run: (x) => saveTemp(d, +x) },
    ],
  });
  const inp = $('#dlg-in');
  if (inp) inp.setAttribute('inputmode', 'numeric');
}

function saveTemp(d, temp) {
  api('PUT', `/api/devices/${d.id}/state`, { temp }).then(() => {
    updateTemp(d.id, temp);
    if (temp == null) render();
  }, handleErr);
}

/** Đưa nút tự tạo lên trước một bậc (thứ tự lưu ở bộ trung tâm, mọi máy đều thấy) */
function moveCustom(d, c, custom) {
  const ids = custom.map((x) => x.id), i = ids.indexOf(c.id);
  if (i <= 0) return;
  [ids[i - 1], ids[i]] = [ids[i], ids[i - 1]];
  api('PUT', '/api/order', { kind: 'command', ids }).then(() => { delete S.cmds[d.id]; render(); }, handleErr);
}

function manageKey(d, c, custom = []) {
  const info = c.kind === 'protocol' ? `Giao thức ${c.protocol} · mã ${c.value}` : `Mã RAW · ${c.raw_len} xung`;
  const canMove = custom.findIndex((x) => x.id === c.id) > 0;
  dialog({ title: `Nút “${c.label}”`, body: esc(info), actions: [
    ...(canMove ? [{ label: 'Chuyển lên trước', run: () => moveCustom(d, c, custom) }] : []),
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

// ----- Giữ nút để lặp: sau 0,5 giây gửi liên tục (chờ ACK lệnh trước rồi mới gửi lệnh sau) -----
const REPEAT = new Set(['vol_up', 'vol_down', 'ch_up', 'ch_down', 'temp_up', 'temp_down', 'up', 'down', 'left', 'right']);

function holdToRepeat(b, cmdId, d) {
  let held = false, timer = null;
  const stop = () => { held = false; clearTimeout(timer); };
  b.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    held = true;
    timer = setTimeout(async function loop() {
      if (!held || !b.isConnected) return;
      b._skipClick = true;          // nhả tay không gửi thêm một lần nữa
      await send(b, cmdId, d, true);
      if (held) timer = setTimeout(loop, 120);
    }, 500);
  });
  ['pointerup', 'pointerleave', 'pointercancel'].forEach((ev) => b.addEventListener(ev, stop));
  b.addEventListener('contextmenu', (e) => e.preventDefault());   // giữ lâu trên điện thoại không hiện menu
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

async function send(btn, cmdId, d, repeat = false) {
  if (btn && !repeat && locked(btn)) return;
  const c = (S.cmds[d.id] || []).find(by('id', cmdId));
  const label = c ? c.label : '';
  S.fb = { dev: d.id, state: 'busy', label };
  paintFb();
  if (btn) btn.classList.add('is-sending');
  try {
    const r = await api('POST', '/api/send', { command_id: cmdId }, 6000);
    S.fb = { dev: d.id, state: 'ok', label, ms: r.latency_ms };
    buzz(true);
    say('Đã phát ' + label);
  } catch (e) {
    buzz(false);
    const msg = SEND_MSG[e.code] || (e.status === 0 ? 'Không kết nối được bộ trung tâm.' : e.message);
    S.fb = { dev: d.id, state: 'bad', msg, retry: () => send(null, cmdId, d) };
    if (e.code === 'slave_offline') api('GET', '/api/slaves').then((l) => { S.slaves = l; });
  } finally {
    if (btn) btn.classList.remove('is-sending');
    paintFb();
  }
}
