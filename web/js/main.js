// Khởi động giao diện: đăng ký trang, kiểm tra kết nối 5 s/lần, nhận sự kiện thời gian thực (SSE).
import { api } from './api.js';
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
    S.online = false;
  }
  applyOnline();
}
S.hooks.poll = poll;
S.hooks.render = render;

function connectEvents() {
  if (!window.EventSource) return;
  const es = new EventSource('/api/events');   // trình duyệt tự kết nối lại khi rớt
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

window.addEventListener('hashchange', () => { render(); window.scrollTo(0, 0); $('#view').focus({ preventScroll: true }); });

render();
loadBase();
poll();
setInterval(poll, 5000);
connectEvents();
