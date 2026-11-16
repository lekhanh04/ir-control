// Học mã IR: bấm nút trên remote nhiều lần vào mắt thu của Pi → so sánh → phát thử qua ESP8266 → lưu.
import { api } from '../api.js';
import { $, esc, ic, toast, say, dialog } from '../util.js';
import { S, loadBase, handleErr, roomName, slaveForDevice } from '../state.js';
import { cur, go, render, setHeader } from '../router.js';

let L = null;   // phiên học đang mở trên giao diện

export function startLearnFor(device, key, label, replace, force = false) {
  L = { device, key, label, replace, force, step: 'start', session: null, count: 0, total: 3, t0: 0, timeout: 15000, result: null, tested: false };
  go('hoc');
}

const ILLUS = `<svg viewBox="0 0 240 90" width="240" height="90" aria-hidden="true" style="color:var(--text-muted)">
  <rect x="14" y="20" width="28" height="58" rx="8" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="28" cy="33" r="4" fill="currentColor"/>
  <path d="M54 49h96" stroke="var(--ir)" stroke-width="2.5" stroke-dasharray="5 7" fill="none"/><path d="M144 41l10 8-10 8" stroke="var(--ir)" stroke-width="2.5" fill="none" stroke-linecap="round"/>
  <rect x="168" y="26" width="58" height="46" rx="6" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="184" cy="49" r="5" fill="var(--ir)"/>
  <text x="197" y="86" text-anchor="middle" font-size="11" fill="currentColor">Raspberry Pi</text></svg>`;

export function learnPage(v) {
  if (!L) { setHeader({ title: 'Học mã IR', back: '' }); v.innerHTML = '<p class="muted">Chọn một nút trên remote của thiết bị để bắt đầu học.</p>'; return; }
  const d = L.device, sl = slaveForDevice(d), slOk = !!(sl && sl.online);
  setHeader({ title: `Học nút “${L.label}”`, sub: d.name + ' · ' + roomName(d.room_id), back: 'tb-' + d.id });
  const back = () => go('tb-' + d.id);

  if (L.step === 'start') {
    v.innerHTML = '<div class="card center"><p class="muted">Đang chuẩn bị mắt thu…</p></div>';
    beginCapture();
    return;
  }

  if (L.step === 'capture') {
    v.innerHTML = `<section class="card center" style="gap:14px">${ILLUS}
      <h2>Bấm nút “${esc(L.label)}” trên remote ${L.total} lần</h2>
      <p class="muted">Hướng remote vào mắt thu trên bộ trung tâm (Raspberry Pi), mỗi lần cách nhau khoảng 1 giây.</p>
      <div class="caps" id="caps"></div><p class="hint" id="cd"></p><button type="button" class="btn ghost" id="lc">Hủy</button></section>`;
    paintCaps();
    $('#lc', v).onclick = back;
    const pollT = setInterval(async () => {
      let r;
      try { r = await api('GET', '/api/learn/' + L.session); } catch (e) { return; }
      if (!L || L.step !== 'capture') return;
      L.count = r.count || 0;
      paintCaps();
      if (r.state !== 'waiting' || Date.now() - L.t0 > L.timeout + 2000) {
        stop();
        S.cleanup = null;
        L.result = r;
        L.step = r.state === 'done' ? 'result' : r.state === 'mismatch' ? 'mismatch' : 'timeout';
        render();
      }
    }, 400);
    const tick = setInterval(() => { const c = $('#cd'); if (c) c.textContent = 'Còn ' + Math.max(0, Math.ceil((L.timeout - (Date.now() - L.t0)) / 1000)) + ' giây'; }, 250);
    const stop = () => { clearInterval(pollT); clearInterval(tick); };
    S.cleanup = () => { stop(); api('DELETE', '/api/learn/' + L.session).catch(() => {}); };
    return;
  }

  if (L.step === 'timeout' || L.step === 'mismatch') {
    v.innerHTML = `<section class="card center" style="gap:12px"><span style="color:var(--warn)">${ic('alert')}</span>` +
      (L.step === 'timeout'
        ? '<h2>Chưa nhận đủ tín hiệu</h2><ul class="tips"><li>Đưa remote lại gần mắt thu hơn (khoảng 10–30 cm)</li><li>Kiểm tra pin của remote</li><li>Bấm dứt khoát, mỗi lần cách nhau 1 giây</li></ul>'
        : `<h2>Các lần thu không giống nhau</h2><p class="muted small">Chỉ khớp ${L.result.match_pct}%. Có thể do giữ nút quá lâu hoặc có nguồn hồng ngoại khác gần đó (đèn, nắng).</p>`) +
      '<button type="button" class="btn pri big full" id="again">Thu lại</button><button type="button" class="btn ghost" id="lc">Hủy</button></section>';
    $('#again', v).onclick = () => { L.step = 'start'; render(); };
    $('#lc', v).onclick = back;
    return;
  }

  // Kết quả + phát thử
  const r = L.result, dec = r.decoded;
  v.innerHTML = `<section class="card" style="gap:14px"><div class="note ok">${ic('check')}<span><b>${L.total} lần thu khớp nhau.</b> ` +
    (dec ? `Nhận dạng được giao thức <b>${esc(dec.protocol)}</b>.` : 'Không nhận dạng được giao thức, mã sẽ được lưu dạng RAW để phát lại nguyên dạng.') + '</span></div>' +
    '<details><summary>Chi tiết kỹ thuật</summary><dl class="kv">' +
    (dec ? `<dt>Giao thức</dt><dd>${esc(dec.protocol)}</dd><dt>Địa chỉ</dt><dd>${esc(dec.address)}</dd><dt>Mã lệnh</dt><dd>${esc(dec.command)}</dd><dt>Mã đầy đủ</dt><dd>${esc(dec.value)}</dd><dt>Số bit</dt><dd>${dec.bits}</dd>`
      : `<dt>Kiểu lưu</dt><dd>RAW</dd><dt>Số xung</dt><dd>${r.raw_len}</dd><dt>Sóng mang</dt><dd>${r.carrier_khz} kHz (giả định)</dd>`) +
    `<dt>Độ khớp</dt><dd>${r.match_pct}%</dd></dl></details></section>` +
    '<section class="card center" style="gap:12px"><h2>Thử trước khi lưu</h2>' +
    (slOk ? `<p class="muted small">Phát qua ${esc(sl.name)} rồi nhìn ${esc(d.name.toLowerCase())}.</p><button type="button" class="btn big full" id="try">${ic('remote')}Phát thử</button><p class="fb" id="tryfb" hidden></p>`
      : `<div class="note warn">${ic('alert')}<span>${sl ? esc(sl.name) + ' đang mất kết nối' : 'Phòng này chưa có bộ phát'}, chưa phát thử được. Bạn vẫn có thể lưu và thử sau.</span></div>`) +
    `<div id="ask" style="width:100%;display:flex;flex-direction:column;gap:10px"${L.tested || !slOk ? '' : ' hidden'}>` +
    (slOk ? `<b>${esc(d.name)} có phản ứng không?</b>` : '') +
    `<div class="row"><button type="button" class="btn grow" id="redo">${slOk ? 'Không, thu lại' : 'Thu lại'}</button><button type="button" class="btn pri grow" id="save">${slOk ? 'Có, lưu nút' : 'Lưu nút'}</button></div></div></section>`;
  // Rời trang khi chưa lưu → hủy phiên học trên Pi
  S.cleanup = () => { if (L && L.step === 'result' && cur().name !== 'hoc') api('DELETE', '/api/learn/' + L.session).catch(() => {}); };

  const tr = $('#try', v);
  if (tr) tr.onclick = async () => {
    const f = $('#tryfb', v);
    f.hidden = false; f.className = 'fb'; f.innerHTML = '<span class="d"></span>Đang phát thử…';
    try {
      const x = await api('POST', `/api/learn/${L.session}/test`, {}, 6000);
      f.classList.add('ok'); f.innerHTML = `${ic('check')}<span>Bộ phát đã phát · ${x.latency_ms} ms</span>`;
      L.tested = true; $('#ask', v).hidden = false; $('#save', v).focus();
    } catch (e) {
      f.classList.add('bad'); f.innerHTML = `${ic('alert')}<span>${e.code === 'no_ack' ? 'Bộ phát không xác nhận sau 3 giây' : esc(e.message)}</span>`;
    }
  };
  $('#redo', v).onclick = () => { L.step = 'start'; L.tested = false; render(); };
  $('#save', v).onclick = () => saveLearn(L.replace);
}

function paintCaps() {
  const c = $('#caps');
  if (!c) return;
  let h = '';
  for (let i = 1; i <= L.total; i++) {
    h += `<div class="cap${i <= L.count ? ' done' : ''}">${i <= L.count ? ic('check') : `<span style="height:20px">${i}</span>`}<span>Lần ${i}</span></div>`;
  }
  c.innerHTML = h;
}

async function beginCapture() {
  try {
    const r = await api('POST', '/api/learn', { device_id: L.device.id, key: L.key, force: L.force || undefined });
    Object.assign(L, { session: r.session, total: r.captures || 3, timeout: (r.timeout_s || 15) * 1000, t0: Date.now(), count: 0, step: 'capture' });
    if (cur().name === 'hoc') render();
    say(`Bấm nút ${L.label} trên remote ${L.total} lần`);
  } catch (e) {
    const { device, key, label, replace } = L;
    go('tb-' + device.id);
    if (e.code === 'ir_receiver') toast('Mắt thu IR trên bộ trung tâm không hoạt động');
    else if (e.code === 'receiver_busy') {
      dialog({ title: 'Mắt thu đang bận', body: 'Có người đang học một nút khác trên bộ trung tâm. Vẫn học nút này? Phiên học kia sẽ bị hủy.',
        actions: [{ label: 'Để sau' }, { label: 'Vẫn học', pri: true, run: () => startLearnFor(device, key, label, replace, true) }] });
    } else handleErr(e);
  }
}

async function saveLearn(replace) {
  const d = L.device;
  try {
    await api('POST', `/api/learn/${L.session}/save`, { label: L.label, replace: replace || undefined });
    toast(`Đã lưu nút “${L.label}”`);
    delete S.cmds[d.id];
    S.edit = true;
    L = null;
    await loadBase();
    go('tb-' + d.id);
  } catch (e) {
    if (e.code === 'exists' && !replace) {
      dialog({ title: 'Nút đã có mã', body: `Thay mã cũ của “${esc(L.label)}” bằng mã vừa học?`, actions: [{ label: 'Hủy' }, { label: 'Thay mã', pri: true, run: () => saveLearn(true) }] });
    } else if (e.code === 'label_exists') {
      dialog({ title: 'Trùng tên nút', body: `${esc(d.name)} đã có nút tên “${esc(L.label)}”. Đặt tên khác cho nút này.`,
        input: { label: 'Tên nút', value: L.label, max: 20 },
        actions: [{ label: 'Hủy' }, { label: 'Lưu', pri: true, submit: true, run: (name) => { L.label = name; saveLearn(replace); } }] });
    } else handleErr(e);
  }
}
