// Ngữ cảnh: một lần chạm phát lần lượt nhiều nút (vd "Đi ngủ": tắt tivi, tắt điều hòa, bật quạt).
// Gọi được từ màn chính, bằng giọng nói ("bật chế độ đi ngủ") và hẹn giờ.
import { api } from '../api.js';
import { $, $$, by, esc, ic, toast, dialog } from '../util.js';
import { S, skel, loadBase, loadCmds, handleErr, roomName } from '../state.js';
import { go } from '../router.js';

const DELAYS = [[0, 'không chờ'], [500, '0,5 giây'], [1000, '1 giây'], [2000, '2 giây'], [5000, '5 giây'], [10000, '10 giây'], [30000, '30 giây']];

const stepText = (st) => `${st.device_name} · ${st.label}`;

/** Chạy ngữ cảnh và báo kết quả. btn: nút vừa bấm (tạm khóa trong lúc chạy) */
export async function runScene(sc, btn) {
  if (!sc) return;
  if (btn) { btn.disabled = true; btn.classList.add('is-sending'); }
  try {
    // Mỗi bước chờ ACK tối đa 3 giây, cộng thời gian chờ giữa các bước
    const wait = sc.steps.reduce((t, s) => t + 3500 + s.delay_ms, 5000);
    const r = await api('POST', `/api/scenes/${sc.id}/run`, {}, wait);
    const ok = r.results.filter((x) => x.status === 'ok').length;
    toast(r.status === 'ok' ? `Đã chạy “${sc.name}” · ${ok} lệnh` : `“${sc.name}”: ${ok}/${r.results.length} lệnh thành công. Xem Lịch sử`);
  } catch (e) {
    handleErr(e);
  } finally {
    if (btn) { btn.disabled = false; btn.classList.remove('is-sending'); }
  }
}

export function scenesPage(v) {
  if (!S.scenes || !S.devices) return skel(v);
  v.innerHTML = '<p class="hint" style="margin:0 4px">Ngữ cảnh phát lần lượt nhiều nút chỉ bằng một lần chạm, ví dụ “Đi ngủ” tắt tivi rồi bật quạt. ' +
    'Gọi được bằng giọng nói (“bật chế độ đi ngủ”) và dùng được trong <a href="#hen-gio">Hẹn giờ</a>.</p>' +
    (S.scenes.length
      ? S.scenes.map((sc) => `<section class="card"><div><b>${esc(sc.name)}</b><br><span class="small muted">${sc.steps.length} bước: ${esc(sc.steps.map(stepText).join(' → ') || '—')}</span></div>
          <div class="row"><button type="button" class="btn sm pri" data-run="${sc.id}"${sc.steps.length ? '' : ' disabled'}>${ic('play')}Chạy</button>
          <a class="btn sm ghost" href="#sua-nc-${sc.id}">${ic('pen')}Sửa</a></div></section>`).join('')
      : '<section class="card center"><p class="muted">Chưa có ngữ cảnh nào.</p></section>') +
    `<a class="btn full dash" href="#them-nc">${ic('plus')}Thêm ngữ cảnh</a>`;
  $$('[data-run]', v).forEach((b) => { b.onclick = () => runScene(S.scenes.find(by('id', +b.dataset.run)), b); });
}

// ----- Thêm / sửa ngữ cảnh -----
let E = null;   // bản đang sửa: {id, name, steps: [{command_id, delay_ms, device_name, label, room_name}]}

export function sceneFormPage(v, id) {
  if (!S.scenes || !S.devices || !S.rooms) return skel(v);
  const sc = id ? S.scenes.find(by('id', id)) : null;
  if (id && !sc) { v.innerHTML = '<p class="muted">Ngữ cảnh này không còn.</p>'; return; }
  if (!E || E.id !== (id || null)) E = { id: id || null, name: sc ? sc.name : '', steps: sc ? sc.steps.map((s) => ({ ...s })) : [] };

  const devs = S.devices.filter((d) => d.command_count > 0);
  const devOpts = S.rooms.map((r) => {
    const ds = devs.filter(by('room_id', r.id));
    return ds.length ? `<optgroup label="${esc(r.name)}">${ds.map((d) => `<option value="${d.id}">${esc(d.name)}</option>`).join('')}</optgroup>` : '';
  }).join('');
  v.innerHTML = `<form class="card" id="sf" novalidate style="gap:16px">
      <div class="field"><label for="sn">Tên ngữ cảnh</label><input id="sn" class="inp" maxlength="30" value="${esc(E.name)}" placeholder="VD: Đi ngủ, Xem phim" autocomplete="off"></div>
      <div class="field"><span class="lab">Các bước, phát theo thứ tự</span><div class="steps" id="steps"></div></div>
      <fieldset class="field"><legend class="lab" style="margin-bottom:8px">Thêm bước</legend>` +
    (devs.length
      ? `<div class="addstep"><select id="ad" class="inp" aria-label="Thiết bị"><option value="">Chọn thiết bị…</option>${devOpts}</select>
         <select id="ac" class="inp" aria-label="Nút" disabled><option value="">Chọn nút…</option></select>
         <button type="button" class="btn" id="aadd" disabled>${ic('plus')}Thêm</button></div>`
      : '<p class="hint">Chưa có thiết bị nào đã học nút.</p>') +
    `</fieldset><p class="err" id="se" role="alert"></p><button class="btn pri big full">${id ? 'Lưu' : 'Tạo ngữ cảnh'}</button></form>` +
    (id ? '<button type="button" class="btn dng full" id="sdel">Xóa ngữ cảnh</button>' : '');
  paintSteps(v);
  $('#sn', v).oninput = (e) => { E.name = e.target.value; };

  const ad = $('#ad', v), ac = $('#ac', v), add = $('#aadd', v);
  if (ad) {
    ad.onchange = async () => {
      ac.disabled = add.disabled = true;
      ac.innerHTML = '<option value="">Chọn nút…</option>';
      if (!ad.value) return;
      try {
        const cmds = S.cmds[+ad.value] || await loadCmds(+ad.value);
        ac.innerHTML += cmds.map((c) => `<option value="${c.id}">${esc(c.label)}</option>`).join('');
        ac.disabled = false;
      } catch (e) { handleErr(e); }
    };
    ac.onchange = () => { add.disabled = !ac.value; };
    add.onclick = () => {
      const d = S.devices.find(by('id', +ad.value)), c = d && (S.cmds[d.id] || []).find(by('id', +ac.value));
      if (!c) return;
      E.steps.push({ command_id: c.id, delay_ms: 500, device_name: d.name, label: c.label, room_name: roomName(d.room_id) });
      paintSteps(v);
      $('#se', v).textContent = '';
    };
  }

  $('#sf', v).onsubmit = async (e) => {
    e.preventDefault();
    const body = { name: E.name.trim(), steps: E.steps.map((s) => ({ command_id: s.command_id, delay_ms: s.delay_ms })) };
    if (!body.name) { $('#se', v).textContent = 'Nhập tên ngữ cảnh.'; $('#sn', v).focus(); return; }
    if (!body.steps.length) { $('#se', v).textContent = 'Thêm ít nhất một bước.'; return; }
    try {
      await api(id ? 'PUT' : 'POST', id ? `/api/scenes/${id}` : '/api/scenes', body);
      E = null;
      await loadBase();
      toast(id ? 'Đã lưu ngữ cảnh' : `Đã tạo “${body.name}”`);
      go('ngu-canh');
    } catch (err) {
      if (err.code === 'exists') { $('#se', v).textContent = 'Đã có ngữ cảnh tên này. Đặt tên khác.'; $('#sn', v).focus(); }
      else handleErr(err);
    }
  };
  const del = $('#sdel', v);
  if (del) del.onclick = () => dialog({
    title: `Xóa “${sc.name}”?`, body: 'Các hẹn giờ dùng ngữ cảnh này cũng bị xóa.',
    actions: [{ label: 'Hủy' }, { label: 'Xóa', dng: true, run: async () => {
      try { await api('DELETE', `/api/scenes/${id}`); E = null; S.schedules = null; toast('Đã xóa ngữ cảnh'); await loadBase(); go('ngu-canh'); } catch (e) { handleErr(e); }
    } }],
  });
}

function paintSteps(v) {
  const box = $('#steps', v);
  if (!E.steps.length) { box.innerHTML = '<p class="hint">Chưa có bước nào. Thêm ở bên dưới.</p>'; return; }
  const last = E.steps.length - 1;
  box.innerHTML = E.steps.map((st, i) => {
    const known = DELAYS.some(([ms]) => ms === st.delay_ms);
    const delay = i < last
      ? `<label class="small muted dl">Sau đó chờ <select class="inp" data-delay="${i}">${DELAYS.map(([ms, l]) => `<option value="${ms}"${ms === st.delay_ms ? ' selected' : ''}>${l}</option>`).join('')}` +
        `${known ? '' : `<option value="${st.delay_ms}" selected>${st.delay_ms} ms</option>`}</select></label>`
      : '';
    return `<div class="step"><span class="n" aria-hidden="true">${i + 1}</span><div class="grow"><b>${esc(stepText(st))}</b><div class="small muted">${esc(st.room_name)}</div>${delay}</div>
      <button type="button" class="iconbtn sm" data-up="${i}" aria-label="Chuyển bước ${i + 1} lên trên"${i ? '' : ' disabled'}>${ic('up')}</button>
      <button type="button" class="iconbtn sm" data-rm="${i}" aria-label="Bỏ bước ${i + 1}">${ic('x')}</button></div>`;
  }).join('');
  $$('[data-delay]', box).forEach((s) => { s.onchange = () => { E.steps[+s.dataset.delay].delay_ms = +s.value; }; });
  $$('[data-up]', box).forEach((b) => { b.onclick = () => { const i = +b.dataset.up; [E.steps[i - 1], E.steps[i]] = [E.steps[i], E.steps[i - 1]]; paintSteps(v); }; });
  $$('[data-rm]', box).forEach((b) => { b.onclick = () => { E.steps.splice(+b.dataset.rm, 1); paintSteps(v); }; });
}
