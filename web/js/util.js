// Hàm tiện ích dùng chung: chọn phần tử, thoát HTML, biểu tượng, thông báo, hộp thoại.

export const $ = (s, r) => (r || document).querySelector(s);
export const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
export const by = (k, v) => (x) => x[k] === v;

export function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** Biểu tượng SVG từ sprite trong index.html (id="i-<tên>") */
export const ic = (n) => `<svg class="ic" aria-hidden="true"><use href="#i-${n}"/></svg>`;

export function clock(ts) {
  const d = new Date(ts);
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}

export function ago(ts) {
  const m = Math.round((Date.now() - ts) / 60e3);
  return m < 1 ? 'vừa xong' : m < 60 ? m + ' phút trước' : m < 1440 ? Math.round(m / 60) + ' giờ trước' : Math.round(m / 1440) + ' ngày trước';
}

/** Vạch sóng Wi-Fi theo RSSI (dBm) */
export function bars(rssi) {
  const lv = rssi >= -60 ? 4 : rssi >= -67 ? 3 : rssi >= -75 ? 2 : rssi >= -85 ? 1 : 0;
  let h = '<span class="rssi" aria-hidden="true">';
  for (let i = 1; i <= 4; i++) h += `<i class="${i <= lv ? 'on' : ''}" style="height:${i * 3.5}px"></i>`;
  return h + '</span>';
}

/** Ngày dễ đọc: "Hôm nay", "Hôm qua", "Ngày mai", "Thứ Hai, 14/11" (thêm năm nếu khác năm nay) */
export function dayLabel(ts) {
  const d = new Date(ts), now = new Date();
  const day = (x) => Math.floor((new Date(x.getFullYear(), x.getMonth(), x.getDate()) - 0) / 864e5);
  const diff = day(d) - day(now);
  if (diff === 0) return 'Hôm nay';
  if (diff === -1) return 'Hôm qua';
  if (diff === 1) return 'Ngày mai';
  const wd = ['Chủ nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'][d.getDay()];
  const dm = String(d.getDate()).padStart(2, '0') + '/' + String(d.getMonth() + 1).padStart(2, '0');
  return `${wd}, ${dm}${d.getFullYear() !== now.getFullYear() ? '/' + d.getFullYear() : ''}`;
}

/** Rung nhẹ trên điện thoại (nếu trình duyệt hỗ trợ): ok = một nhịp ngắn, lỗi = hai nhịp */
export function buzz(ok = true) {
  try { if (navigator.vibrate) navigator.vibrate(ok ? 12 : [40, 60, 40]); } catch (e) { /* bỏ qua */ }
}

let toastT, toastCancel = null;
/**
 * Thông báo nổi ở cuối màn hình.
 * kind 'ok' (mặc định): tự ẩn sau 2,6 giây. kind 'err': giữ 7 giây, có nút đóng, đọc ngay cho trình đọc màn hình.
 */
export function toast(m, kind = 'ok') {
  const t = $('#toast');
  if (toastCancel) { toastCancel(false); toastCancel = null; }
  const err = kind === 'err';
  t.className = err ? 'show err' : 'show';
  t.setAttribute('aria-live', err ? 'assertive' : 'polite');
  t.innerHTML = `<span class="grow">${esc(m)}</span>` + (err ? '<button type="button" class="tbtn" aria-label="Đóng thông báo">✕</button>' : '');
  const hide = () => { t.className = ''; };
  t.onclick = hide;
  clearTimeout(toastT);
  toastT = setTimeout(hide, err ? 7000 : 2600);
}

/**
 * Đếm ngược rồi mới làm, có nút Hủy (chống chạm nhầm). Trả Promise<boolean>: true = đã chạy, false = đã hủy.
 */
export function countdown(msg, seconds, run) {
  const t = $('#toast');
  if (toastCancel) toastCancel(false);
  clearTimeout(toastT);
  return new Promise((resolve) => {
    let left = seconds, timer;
    const paint = () => { t.querySelector('.grow').textContent = `${msg} sau ${left} giây…`; };
    const finish = (doIt) => {
      clearInterval(timer);
      toastCancel = null;
      t.className = '';
      t.onclick = null;
      if (doIt) run();
      resolve(doIt);
    };
    t.className = 'show';
    t.setAttribute('aria-live', 'polite');
    t.innerHTML = '<span class="grow"></span><button type="button" class="tbtn" id="cdx">Hủy</button>';
    t.onclick = null;
    paint();
    $('#cdx', t).onclick = (e) => { e.stopPropagation(); finish(false); toast('Đã hủy'); };
    toastCancel = finish;
    timer = setInterval(() => { left -= 1; if (left <= 0) finish(true); else paint(); }, 1000);
  });
}

/** Đọc cho trình đọc màn hình */
export function say(m) {
  const s = $('#say');
  s.textContent = '';
  setTimeout(() => { s.textContent = m; }, 30);
}

/**
 * Hộp thoại dùng chung.
 * dialog({ title, body?, input?: {label, value, max}, actions: [{label, pri?, dng?, submit?, check?(value) → lỗi | '', run?(value)}] })
 */
export function dialog(o) {
  const d = $('#dlg');
  d.innerHTML = `<form id="dlgf" novalidate><h2 id="dlg-t">${esc(o.title)}</h2>` +
    (o.body ? `<p class="muted" style="margin-top:8px">${o.body}</p>` : '') +
    (o.input ? `<div class="field" style="margin-top:16px"><label for="dlg-in">${esc(o.input.label)}</label><input id="dlg-in" class="inp" maxlength="${o.input.max || 30}" value="${esc(o.input.value || '')}" autocomplete="off"></div><p class="err" id="dlg-e" role="alert" style="margin-top:6px"></p>` : '') +
    '<div class="dlg-act">' + o.actions.map((a, i) => `<button type="${a.submit ? 'submit' : 'button'}" class="btn ${a.pri ? 'pri' : a.dng ? 'dng' : ''}" data-i="${i}">${esc(a.label)}</button>`).join('') + '</div></form>';
  d.setAttribute('aria-labelledby', 'dlg-t');
  const run = (a) => {
    const val = o.input ? $('#dlg-in', d).value.trim() : undefined;
    if (o.input && a.submit && !val) { $('#dlg-e', d).textContent = 'Không được để trống.'; return; }
    const bad = a.check && a.check(val);
    if (bad) { $('#dlg-e', d).textContent = bad; return; }
    d.close();
    if (a.run) a.run(val);
  };
  $$('button', d).forEach((b) => { b.onclick = (e) => { e.preventDefault(); run(o.actions[+b.dataset.i]); }; });
  $('#dlgf', d).onsubmit = (e) => { e.preventDefault(); const a = o.actions.find((x) => x.submit); if (a) run(a); };
  d.showModal();
  if (o.input) { const i = $('#dlg-in', d); i.focus(); i.select(); }
}
