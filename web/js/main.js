// Khởi động giao diện: đăng ký trang, kiểm tra kết nối 5 s/lần, nhận sự kiện thời gian thực (SSE), đăng nhập PIN.
import { api, onAuthRequired } from './api.js';
import { $, by, toast } from './util.js';
import { S, loadBase } from './state.js';
import { routes, render, cur, applyOnline } from './router.js';
import { homePage } from './pages/home.js';
import { remotePage } from './pages/remote.js';
import { learnPage } from './pages/learn.js';
import { historyPage } from './pages/history.js';
import { managePage } from './pages/manage.js';
import { deviceFormPage } from './pages/device-form.js';
import { slavesPage } from './pages/slaves.js';
import { systemPage, paintSystem } from './pages/system.js';
import { voicePage, onVoice } from './pages/voice.js';
import { scenesPage, sceneFormPage } from './pages/scenes.js';
import { schedulesPage } from './pages/schedules.js';

// Trang có `title` thì router tự vẽ tiêu đề; trang không có tự gọi setHeader().
Object.assign(routes, {
  '': { title: 'Điều khiển', page: homePage },
  'tb': { page: remotePage },                // #tb-<id>
  'hoc': { page: learnPage },
  'lich-su': { title: 'Lịch sử điều khiển', page: historyPage },
  'quan-ly': { title: 'Quản lý', page: managePage },
  'them-tb': { title: 'Thêm thiết bị', back: 'quan-ly', page: deviceFormPage },
  'sua-tb': { page: deviceFormPage },        // #sua-tb-<id>
  'bo-phat': { title: 'Bộ phát ESP8266', back: 'quan-ly', page: slavesPage },
  'giong-noi': { title: 'Giọng nói', back: 'quan-ly', page: voicePage },
  'he-thong': { title: 'Bộ trung tâm', back: 'quan-ly', page: systemPage },
  'ngu-canh': { title: 'Ngữ cảnh', back: 'quan-ly', page: scenesPage },
  'them-nc': { title: 'Thêm ngữ cảnh', back: 'ngu-canh', page: sceneFormPage },
  'sua-nc': { title: 'Sửa ngữ cảnh', back: 'ngu-canh', page: sceneFormPage },   // #sua-nc-<id>
  'hen-gio': { title: 'Hẹn giờ', back: 'quan-ly', page: schedulesPage },
});

async function poll() {
  try {
    const st = await api('GET', '/api/system');
    const was = S.online;
    S.system = st;
    S.online = true;
    if (was === false) { toast('Đã kết nối lại'); await loadBase(); render(); }
    if (cur().name === 'he-thong') paintSystem();
  } catch (e) {
    S.online = e.status === 401 ? true : false;   // 401: vẫn kết nối được, chỉ là chưa nhập PIN
  }
  applyOnline();
}
S.hooks.poll = poll;
S.hooks.render = render;

// ----- Sự kiện thời gian thực -----
let es = null;
function connectEvents() {
  if (!window.EventSource) return;
  if (es) es.close();
  es = new EventSource('/api/events');   // trình duyệt tự kết nối lại khi rớt mạng (không tự kết nối lại khi bị 401)
  const on = (name, fn) => es.addEventListener(name, (e) => { try { fn(JSON.parse(e.data)); } catch (x) { console.error(x); } });
  on('voice', onVoice);
  on('slave', (s) => {
    if (!S.slaves) return;
    const o = S.slaves.find(by('id', s.id));
    const changed = !o || o.online !== s.online || o.room_id !== s.room_id;
    if (o) Object.assign(o, s); else S.slaves.push(s);
    // Chỉ vẽ lại khi bộ phát đổi trạng thái (status định kỳ 30 s không làm giao diện nhảy)
    if (changed && ['', 'tb', 'quan-ly', 'bo-phat'].includes(cur().name) && !$('dialog[open]')) render();
  });
  on('history', (h) => {
    if (S.history) S.history.unshift(h);
    if (cur().name === 'lich-su') render();
  });
}

// ----- Đăng nhập bằng mã PIN (khi backend đặt IRHUB_PIN) -----
export function showLogin() {
  const d = $('#login');
  S.auth = { required: true, ok: false };
  if (d.open) return;
  d.innerHTML = '<form id="lf" novalidate><h2 id="login-t">Nhập mã PIN</h2>' +
    '<p class="muted small" style="margin-top:6px">Bộ trung tâm yêu cầu mã PIN trước khi điều khiển. Trình duyệt này sẽ được nhớ.</p>' +
    '<div class="field" style="margin-top:16px"><label for="pin">Mã PIN</label>' +
    '<input id="pin" class="inp pin" type="password" inputmode="numeric" autocomplete="current-password" maxlength="12"></div>' +
    '<p class="err" id="le" role="alert" style="margin-top:6px"></p>' +
    '<div class="dlg-act"><button class="btn pri full">Đăng nhập</button></div></form>';
  d.setAttribute('aria-labelledby', 'login-t');
  $('#lf', d).onsubmit = async (e) => {
    e.preventDefault();
    const inp = $('#pin', d), pin = inp.value.trim();
    if (!pin) { $('#le', d).textContent = 'Nhập mã PIN.'; return; }
    try {
      S.auth = await api('POST', '/api/login', { pin });
      d.close();
      await loadBase();
      render();
      connectEvents();
      poll();
    } catch (err) {
      $('#le', d).textContent = err.status === 0 ? 'Không kết nối được bộ trung tâm.' : err.message;
      inp.select();
    }
  };
  d.showModal();
  $('#pin', d).focus();
}
$('#login').addEventListener('cancel', (e) => e.preventDefault());   // không đóng được bằng phím Esc
onAuthRequired(showLogin);
S.hooks.login = showLogin;

window.addEventListener('hashchange', () => { render(); window.scrollTo(0, 0); $('#view').focus({ preventScroll: true }); });

render();
api('GET', '/api/auth').then((a) => {
  S.auth = a;
  if (a.required && !a.ok) showLogin();
  else { loadBase(); connectEvents(); }
}, () => { loadBase(); connectEvents(); });
poll();
setInterval(poll, 5000);
