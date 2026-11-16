// Điều hướng theo hash (#lich-su, #tb-12, ...) và thanh tiêu đề.
import { $, $$, esc, ic } from './util.js';
import { S } from './state.js';

/** name → { title, back?, page(v, id) }  (main.js đăng ký) */
export const routes = {};

/** Đọc hash hiện tại. Trang có id: #tb-12 (remote), #sua-tb-12 (sửa thiết bị), #sua-nc-3 (sửa ngữ cảnh).
 *  #phong-3 = màn chính, đang chọn phòng 3 (giữ được khi tải lại trang hay gửi đường dẫn cho người khác). */
export function cur() {
  const h = location.hash.slice(1);
  const m = h.match(/^(tb|sua-tb|sua-nc)-(\d+)$/);
  if (m) return { name: m[1], id: +m[2] };
  const p = h.match(/^phong-(\d+)$/);
  if (p) return { name: '', room: +p[1] };
  return { name: routes[h] ? h : '' };
}

/** Màn hình rộng (máy tính, máy tính bảng ngang): màn chính hiện thiết bị bên trái, remote bên phải */
export const wideQuery = window.matchMedia('(min-width: 1100px)');

function tabOf(name) {
  if (name === 'lich-su') return 'history';
  if (name === '' || name === 'tb' || name === 'hoc') return 'home';
  return 'manage';
}

export function setHeader({ title, sub, back, right }) {
  let h = back !== undefined ? `<a class="iconbtn back" href="#${back}" aria-label="Quay lại">${ic('chev')}</a>` : '';
  h += `<h1 class="ttl grow">${esc(title)}${sub ? `<span class="sub">${esc(sub)}</span>` : ''}</h1>`;
  if (right) h += right;
  $('#top').innerHTML = h;
  document.title = title + ' · Điều khiển IR';
}

export function render() {
  if (S.cleanup) { try { S.cleanup(); } catch (e) { /* bỏ qua */ } S.cleanup = null; }
  S.waiting = false;
  const r = cur();
  const route = routes[r.name];
  document.body.classList.toggle('focus', r.name === 'hoc');
  $$('.nav a').forEach((a) => (a.dataset.tab === tabOf(r.name) ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
  const v = $('#vf');
  v.innerHTML = '';
  const split = wideQuery.matches && (r.name === '' || r.name === 'tb') && routes.split;
  document.body.classList.toggle('split-on', !!split);
  if (split) {
    setHeader({ title: 'Điều khiển' });
    routes.split.page(v, r);
  } else {
    if (route.title) setHeader({ title: route.title, back: route.back });
    route.page(v, r.id);
  }
  applyOnline();
}

export function go(hash) {
  if (location.hash.slice(1) === hash) render();
  else location.hash = hash;
}

let bannerKey = '';
export function applyOnline() {
  $('#vf').disabled = S.online === false;
  const key = S.online === false ? 'off' : '';
  if (key === bannerKey) return;
  bannerKey = key;
  $('#banners').innerHTML = key
    ? `<div class="banner" role="alert">${ic('alert')}<div><b>Mất kết nối với bộ trung tâm. Đang thử lại…</b><p class="small muted">Kiểm tra Raspberry Pi còn bật và điện thoại đang dùng cùng mạng Wi-Fi.</p></div></div>`
    : '';
}
