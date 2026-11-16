// Trạng thái chung của giao diện và các hàm tải dữ liệu từ bộ trung tâm.
import { api } from './api.js';
import { by, esc, ago, toast } from './util.js';
import { TYPES } from './types.js';

export const store = {
  get(k, d) { try { const v = localStorage.getItem('irhub.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('irhub.' + k, JSON.stringify(v)); } catch (e) { /* trình duyệt chặn bộ nhớ */ } },
};

export const S = {
  online: null,        // còn kết nối bộ trung tâm?
  system: null,        // GET /api/system
  rooms: null, devices: null, slaves: null,
  scenes: null,        // GET /api/scenes: ngữ cảnh kèm các bước
  schedules: null,     // GET /api/schedules (tải khi mở trang Hẹn giờ)
  auth: null,          // GET /api/auth: {required, ok}
  types: null,         // GET /api/device-types: [{code, label}] theo thứ tự hiển thị
  cmds: {},            // device_id → danh sách nút
  history: null, histFilter: 'all',
  voice: null, vnow: { state: 'idle' }, vT: null,
  room: store.get('room', null),   // phòng đang chọn (nhớ theo trình duyệt)
  edit: false,         // chế độ "Sửa nút" trên remote
  fb: null, fbDev: null,           // phản hồi lệnh vừa gửi
  formRoom: null, formType: null,  // giá trị mặc định cho form thêm thiết bị
  waiting: false,      // trang đang chờ dữ liệu nền để vẽ lại
  cleanup: null,       // hàm dọn dẹp khi rời trang
  hooks: { render() {}, poll() {}, login() {} },   // main.js gán
};

export async function loadBase() {
  try {
    const [rooms, devices, slaves, voice, types, scenes] = await Promise.all([
      api('GET', '/api/rooms'), api('GET', '/api/devices'), api('GET', '/api/slaves'), api('GET', '/api/voice').catch(() => null),
      S.types ? S.types : api('GET', '/api/device-types'), api('GET', '/api/scenes').catch(() => []),
    ]);
    Object.assign(S, { rooms, devices, slaves, voice, types, scenes });
    if (!rooms.some(by('id', S.room))) S.room = rooms[0] ? rooms[0].id : null;
    if (S.waiting) S.hooks.render();
  } catch (e) { /* poll() sẽ báo mất kết nối */ }
}

export async function loadCmds(id) {
  S.cmds[id] = await api('GET', `/api/devices/${id}/commands`);
  return S.cmds[id];
}

export function handleErr(e) {
  if (e.code === 'auth') return;   // hộp nhập mã PIN đã hiện
  if (e.status === 429 || e.code === 'busy') return toast('Hệ thống đang bận, thử lại sau 1 giây');
  if (e.status === 0) { S.hooks.poll(); return toast('Không kết nối được bộ trung tâm'); }
  toast(e.message || 'Có lỗi xảy ra');
}

/** Khung chờ trong lúc tải; trang sẽ tự vẽ lại khi loadBase() xong */
export function skel(v, n = 3) {
  S.waiting = true;
  let h = '<span class="sr">Đang tải…</span>';
  for (let i = 0; i < n; i++) h += '<div class="card" aria-hidden="true"><div class="sk" style="width:40%"></div><div class="sk" style="height:48px"></div></div>';
  v.innerHTML = h;
}

export function roomName(id) {
  const r = (S.rooms || []).find(by('id', id));
  return r ? r.name : 'Chưa gán phòng';
}

/**
 * Thông tin hiển thị của một loại thiết bị: tên lấy từ bảng device_types (CSDL),
 * biểu tượng và bố cục remote lấy từ types.js. Loại chưa có bố cục dùng bố cục "Thiết bị khác".
 */
export function typeInfo(code) {
  const base = TYPES[code] || TYPES.other;
  const row = (S.types || []).find(by('code', code));
  return row ? { ...base, label: row.label } : base;
}

/** Các bộ phát đặt ở một phòng, bộ đang hoạt động lên trước */
export function slavesIn(roomId) {
  return (S.slaves || []).filter((s) => s.room_id === roomId)
    .sort((a, b) => (b.online - a.online) || ((b.last_seen || 0) - (a.last_seen || 0)) || (a.id < b.id ? -1 : 1));
}

/** Bộ phát sẽ dùng cho thiết bị — cùng quy tắc với backend (Hub.slave_for_device) */
export function slaveForDevice(d) {
  if (d.slave_id) {
    const s = (S.slaves || []).find(by('id', d.slave_id));
    if (s) return s;
  }
  return slavesIn(d.room_id)[0] || null;
}

const lineOk = (style, text) => `<p class="slave" style="${style}"><span class="dot ok"></span>${text}</p>`;
const lineBad = (style, text) => `<p class="slave" style="color:var(--danger);${style}"><span class="dot bad"></span>${text}</p>`;
const lineNone = (style) => `<p class="slave" style="${style}"><span class="dot warn"></span>Phòng này chưa có bộ phát. <a href="#bo-phat">Gán bộ phát</a></p>`;

/** Dòng tóm tắt bộ phát ESP8266 của một phòng (có thể nhiều bộ) */
export function slaveLine(roomId, style = '') {
  const list = slavesIn(roomId);
  if (!list.length) return lineNone(style);
  if (list.length === 1) {
    const s = list[0];
    return s.online ? lineOk(style, `${esc(s.name)} · đang hoạt động`) : lineBad(style, `${esc(s.name)} mất kết nối từ ${ago(s.last_seen)}`);
  }
  const on = list.filter((s) => s.online).length;
  if (on === list.length) return lineOk(style, `${list.length} bộ phát · tất cả đang hoạt động`);
  if (!on) return lineBad(style, `${list.length} bộ phát · tất cả mất kết nối`);
  const off = list.filter((s) => !s.online).map((s) => esc(s.name)).join(', ');
  return `<p class="slave" style="${style}"><span class="dot warn"></span>${on}/${list.length} bộ phát hoạt động · ${off} mất kết nối</p>`;
}

/** Dòng trạng thái bộ phát mà một thiết bị sẽ dùng */
export function deviceSlaveLine(d, style = '') {
  const s = slaveForDevice(d);
  if (!s) return lineNone(style);
  const multi = slavesIn(d.room_id).length > 1;
  const how = d.slave_id ? ' (gán riêng)' : multi ? ' (tự chọn)' : '';
  return s.online ? lineOk(style, `Phát qua ${esc(s.name)}${how} · đang hoạt động`)
    : lineBad(style, `${esc(s.name)}${how} mất kết nối từ ${ago(s.last_seen)}`);
}
