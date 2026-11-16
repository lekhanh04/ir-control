// Gọi REST API của bộ trung tâm (cùng địa chỉ với trang web). Danh sách API: docs/api.md

let authHook = null;
/** Mã riêng của tab này: backend gửi kèm trong sự kiện "changed" để tab tự bỏ qua thay đổi do chính nó tạo ra */
export const CLIENT_ID = Math.random().toString(36).slice(2, 10);
/** main.js đăng ký: được gọi khi bộ trung tâm yêu cầu nhập mã PIN (401 "auth") */
export function onAuthRequired(fn) { authHook = fn; }

/**
 * @returns {Promise<any>} JSON trả về; lỗi ném Error có .status (0 = mất kết nối), .code, .message
 */
export async function api(method, path, body, timeoutMs = 5000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  let r;
  try {
    r = await fetch(path, {
      method,
      headers: body === undefined ? { 'X-Client-Id': CLIENT_ID } : { 'Content-Type': 'application/json', 'X-Client-Id': CLIENT_ID },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctl.signal,
      cache: 'no-store',
      credentials: 'same-origin',
    });
  } catch (e) {
    throw apiErr(0, e.name === 'AbortError' ? 'timeout' : 'network', 'Không kết nối được bộ trung tâm');
  } finally {
    clearTimeout(t);
  }
  const j = await r.json().catch(() => ({}));
  if (r.status === 401 && j.error === 'auth' && authHook) authHook();
  if (!r.ok) throw apiErr(r.status, j.error || 'http', j.message || 'Lỗi ' + r.status);
  return j;
}

function apiErr(status, code, message) {
  const e = new Error(message);
  e.status = status;
  e.code = code;
  return e;
}
