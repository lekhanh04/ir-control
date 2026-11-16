// Biểu tượng và bố cục remote cho từng loại thiết bị.
// Danh sách loại và tên hiển thị nằm trong bảng device_types của CSDL (GET /api/device-types).
// Thêm loại mới: INSERT vào device_types; muốn remote có bố cục riêng thì thêm một mục vào TYPES bên dưới (không bắt buộc).

/** Tên hiển thị mặc định của các mã nút chuẩn (cột commands.key) */
export const KEY_LABEL = {
  power: 'Nguồn', source: 'Nguồn vào', temp_up: 'Nhiệt độ +', temp_down: 'Nhiệt độ −', mode: 'Chế độ', fan_speed: 'Tốc độ gió', swing: 'Đảo gió',
  vol_up: 'Âm lượng +', vol_down: 'Âm lượng −', ch_up: 'Kênh +', ch_down: 'Kênh −', up: 'Lên', down: 'Xuống', left: 'Trái', right: 'Phải', ok: 'OK',
  back: 'Quay lại', home: 'Trang chủ', mute: 'Tắt tiếng', speed: 'Tốc độ', cool: 'Làm mát', timer: 'Hẹn giờ', menu: 'Menu', freeze: 'Dừng hình', blank: 'Tắt hình',
};

/**
 * groups: các khối trên remote, theo thứ tự từ trên xuống
 *   top  : hàng nút lớn (Nguồn tròn + nút phụ)
 *   pair : cặp −/+ có tiêu đề ở giữa
 *   dpad : phím điều hướng lên/trái/OK/phải/xuống
 *   grid : lưới nút thường
 */
export const TYPES = {
  ac: { label: 'Điều hòa', icon: 'snow', groups: [
    { kind: 'top', keys: ['power'] },
    { kind: 'pair', title: 'Nhiệt độ', keys: ['temp_down', 'temp_up'] },
    { kind: 'grid', keys: ['mode', 'fan_speed', 'swing'] },
  ] },
  tv: { label: 'Tivi', icon: 'tv', groups: [
    { kind: 'top', keys: ['power', 'source'] },
    { kind: 'pair', title: 'Âm lượng', keys: ['vol_down', 'vol_up'] },
    { kind: 'pair', title: 'Kênh', keys: ['ch_down', 'ch_up'] },
    { kind: 'dpad', keys: ['up', 'left', 'ok', 'right', 'down'] },
    { kind: 'grid', keys: ['back', 'home', 'mute'] },
  ] },
  fan: { label: 'Quạt điều hòa', icon: 'fan', groups: [
    { kind: 'top', keys: ['power'] },
    { kind: 'grid', keys: ['speed', 'mode', 'swing', 'cool', 'timer'] },
  ] },
  projector: { label: 'Máy chiếu', icon: 'proj', groups: [
    { kind: 'top', keys: ['power', 'source'] },
    { kind: 'dpad', keys: ['up', 'left', 'ok', 'right', 'down'] },
    { kind: 'pair', title: 'Âm lượng', keys: ['vol_down', 'vol_up'] },
    { kind: 'grid', keys: ['menu', 'freeze', 'blank'] },
  ] },
  other: { label: 'Thiết bị khác', icon: 'remote', groups: [{ kind: 'top', keys: ['power'] }] },
};
