// Hẹn giờ: chạy một ngữ cảnh hoặc một nút vào giờ cố định, các ngày chọn trong tuần (theo đồng hồ của Raspberry Pi).
import { api } from '../api.js';
import { $, $$, by, esc, ic, toast, dialog, clock, dayLabel } from '../util.js';
import { S, skel, loadCmds, handleErr } from '../state.js';
import { cur, render } from '../router.js';

const DAYS = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'];
const DAY_NAMES = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ nhật'];
const PRESETS = [[127, 'Mọi ngày'], [31, 'Thứ 2 – Thứ 6'], [96, 'Cuối tuần']];

export function daysText(m) {
  const p = PRESETS.find(([x]) => x === m);
  return p ? p[1] : DAYS.filter((_, i) => m & (1 << i)).join(', ');
}

const LAST = { ok: 'thành công', partial: 'một phần', error: 'không thành công', skipped: 'bỏ qua (ngữ cảnh trống)' };
function runInfo(s) {
  const parts = [];
  if (s.next_run) parts.push(`Lần tới: ${dayLabel(s.next_run)} ${clock(s.next_run)}`);
  if (s.last_at) {
    const n = s.last_total ? ` · ${s.last_ok}/${s.last_total} lệnh` : '';
    parts.push(`<span${s.last_status === 'ok' || s.last_status === 'skipped' ? '' : ' style="color:var(--danger)"'}>Lần trước: ${dayLabel(s.last_at)} ${clock(s.last_at)}, ${LAST[s.last_status] || s.last_status}${n}</span>`);
  }
  return parts.length ? `<br><span class="small muted">${parts.join('<br>')}</span>` : '';
}

const title = (s) => (s.scene_id ? `Ngữ cảnh “${s.scene_name}”` : `${s.device_name} · ${s.command_label}${s.room_name ? ` (${s.room_name})` : ''}`);

let F = null;   // biểu mẫu đang mở: {id|null, target: 's:<scene_id>' | 'c:<command_id>', at_time, days}

function reload() {
  return api('GET', '/api/schedules').then((l) => { S.schedules = l; if (cur().name === 'hen-gio') render(); }, handleErr);
}

export function schedulesPage(v) {
  if (!S.scenes || !S.devices || !S.rooms) return skel(v);
  if (!S.schedules) { skel(v, 2); reload(); return; }
  const need = S.devices.filter((d) => d.command_count && !S.cmds[d.id]);   // cần danh sách nút để chọn
  if (need.length) {
    skel(v, 2);
    Promise.all(need.map((d) => loadCmds(d.id))).then(() => { if (cur().name === 'hen-gio') render(); }, handleErr);
    return;
  }

  const list = S.schedules.map((s) => `<section class="card"><div class="row" style="gap:12px">
      <span class="tm${s.enabled ? '' : ' muted'}">${esc(s.at_time)}</span>
      <div class="grow"><b>${esc(title(s))}</b><br><span class="small muted">${esc(daysText(s.days))}</span>${runInfo(s)}` +
      (s.scene_id && !s.scene_steps ? '<br><span class="badge warn">Ngữ cảnh không còn bước nào, hẹn giờ sẽ tự tắt</span>' : '') + `</div>
      <button type="button" class="switch" role="switch" data-tog="${s.id}" aria-checked="${s.enabled}" aria-label="Bật hẹn giờ ${esc(s.at_time)}"></button></div>
      <div class="row"><button type="button" class="btn sm ghost" data-edit="${s.id}">${ic('pen')}Sửa</button>
      <button type="button" class="btn sm ghost" style="color:var(--danger)" data-del="${s.id}">Xóa</button></div></section>`).join('');

  v.innerHTML = '<p class="hint" style="margin:0 4px">Chạy một ngữ cảnh hoặc một nút vào giờ cố định. Giờ theo đồng hồ của bộ trung tâm (Raspberry Pi), cần Pi có mạng để giờ đúng.</p>' +
    (S.schedules.length || F ? list : '<section class="card center"><p class="muted">Chưa có hẹn giờ nào.</p></section>') +
    (F ? formHtml() : `<button type="button" class="btn full dash" id="hadd">${ic('plus')}Thêm hẹn giờ</button>`);

  $$('[data-tog]', v).forEach((b) => {
    b.onclick = async () => {
      const s = S.schedules.find(by('id', +b.dataset.tog));
      try { Object.assign(s, await api('PATCH', `/api/schedules/${s.id}`, { enabled: !s.enabled })); toast(s.enabled ? 'Đã bật hẹn giờ' : 'Đã tắt hẹn giờ'); render(); }
      catch (e) { handleErr(e); }
    };
  });
  $$('[data-edit]', v).forEach((b) => {
    b.onclick = () => {
      const s = S.schedules.find(by('id', +b.dataset.edit));
      F = { id: s.id, target: s.scene_id ? 's:' + s.scene_id : 'c:' + s.command_id, at_time: s.at_time, days: s.days };
      render();
    };
  });
  $$('[data-del]', v).forEach((b) => {
    b.onclick = () => {
      const s = S.schedules.find(by('id', +b.dataset.del));
      dialog({ title: `Xóa hẹn giờ ${s.at_time}?`, body: esc(title(s)), actions: [{ label: 'Hủy' }, { label: 'Xóa', dng: true, run: async () => {
        try { await api('DELETE', `/api/schedules/${s.id}`); toast('Đã xóa hẹn giờ'); if (F && F.id === s.id) F = null; reload(); } catch (e) { handleErr(e); }
      } }] });
    };
  });
  const add = $('#hadd', v);
  if (add) add.onclick = () => { F = { id: null, target: '', at_time: '22:00', days: 127 }; render(); };
  if (F) bindForm(v);
}

function targetOptions() {
  let h = '<option value="">Chọn…</option>';
  if (S.scenes.length) h += `<optgroup label="Ngữ cảnh">${S.scenes.map((sc) => `<option value="s:${sc.id}">${esc(sc.name)}</option>`).join('')}</optgroup>`;
  for (const r of S.rooms) {
    for (const d of S.devices.filter(by('room_id', r.id))) {
      const cmds = S.cmds[d.id] || [];
      if (cmds.length) h += `<optgroup label="${esc(r.name + ' · ' + d.name)}">${cmds.map((c) => `<option value="c:${c.id}">${esc(d.name + ' · ' + c.label)}</option>`).join('')}</optgroup>`;
    }
  }
  return h;
}

function formHtml() {
  return `<form class="card" id="hf" novalidate style="gap:16px"><h2>${F.id ? 'Sửa hẹn giờ' : 'Thêm hẹn giờ'}</h2>
    <div class="field"><label for="ht">Giờ</label><input id="ht" type="time" class="inp" value="${esc(F.at_time)}" required></div>
    <fieldset class="field"><legend class="lab" style="margin-bottom:8px">Lặp lại</legend>
      <div class="days" role="group" aria-label="Các ngày">${DAYS.map((d, i) => `<button type="button" class="chip" data-day="${i}" aria-pressed="${!!(F.days & (1 << i))}" aria-label="${DAY_NAMES[i]}">${d}</button>`).join('')}</div>
      <div class="row wrap" style="margin-top:8px">${PRESETS.map(([m, l]) => `<button type="button" class="btn sm ghost" data-preset="${m}">${l}</button>`).join('')}</div></fieldset>
    <div class="field"><label for="hg">Việc cần làm</label><select id="hg" class="inp">${targetOptions()}</select></div>
    <p class="err" id="he" role="alert"></p>
    <div class="row"><button type="button" class="btn grow" id="hc">Hủy</button><button class="btn pri grow">Lưu</button></div></form>`;
}

function bindForm(v) {
  const f = $('#hf', v), sel = $('#hg', f);
  sel.value = F.target;
  sel.onchange = () => { F.target = sel.value; };
  $('#ht', f).oninput = (e) => { F.at_time = e.target.value; };
  const paintDays = () => $$('[data-day]', f).forEach((b) => b.setAttribute('aria-pressed', !!(F.days & (1 << +b.dataset.day))));
  $$('[data-day]', f).forEach((b) => { b.onclick = () => { F.days ^= 1 << +b.dataset.day; paintDays(); }; });
  $$('[data-preset]', f).forEach((b) => { b.onclick = () => { F.days = +b.dataset.preset; paintDays(); }; });
  $('#hc', f).onclick = () => { F = null; render(); };
  f.onsubmit = async (e) => {
    e.preventDefault();
    const err = (m) => { $('#he', f).textContent = m; };
    const at = (F.at_time || '').slice(0, 5);
    if (!/^\d\d:\d\d$/.test(at)) return err('Chọn giờ.');
    if (!F.days) return err('Chọn ít nhất một ngày.');
    if (!F.target) return err('Chọn ngữ cảnh hoặc nút cần chạy.');
    const [k, id] = F.target.split(':');
    const body = { at_time: at, days: F.days, scene_id: k === 's' ? +id : null, command_id: k === 'c' ? +id : null };
    try {
      await api(F.id ? 'PATCH' : 'POST', F.id ? `/api/schedules/${F.id}` : '/api/schedules', body);
      toast(`Đã lưu hẹn giờ ${at} · ${daysText(F.days)}`);
      F = null;
      reload();
    } catch (x) { if (x.code === 'invalid') err(x.message); else handleErr(x); }
  };
  $('#ht', f).focus();
}
