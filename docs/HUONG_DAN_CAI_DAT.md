# Hướng dẫn cài và chạy thử M44 Labeler (cho cả nhóm)

Làm một lần khoảng 30–45 phút, phần lâu nhất là tải dữ liệu nuScenes (~4 GB). Chỉ cần Windows 10/11, không cần GPU.

## 0. Chuẩn bị

| Cần | Lấy ở đâu | Lưu ý khi cài |
|---|---|---|
| **Python 3.11** | <https://www.python.org/downloads/> (bản 3.11.x, "Windows installer 64-bit") | Màn hình đầu tiên: **tích "Add python.exe to PATH"** |
| **Node.js 20 LTS** (hoặc mới hơn) | <https://nodejs.org/> → nút LTS | Cứ Next đến hết |
| **Git** (khuyên dùng) | <https://git-scm.com/download/win> | Cứ Next đến hết |
| ~10 GB trống | ổ D nếu ổ C gần đầy | |

Cài xong mở **một cửa sổ cmd mới** và gõ thử `python --version`, `node --version`, `git --version` – cả ba phải in ra số
phiên bản.

## 1. Lấy code

```bat
cd /d D:\
git clone https://github.com/cuonglatao1/m44-labeler.git
```

→ code nằm ở `D:\m44-labeler`. Không có Git: trên trang GitHub bấm **Code → Download ZIP**, giải nén ra `D:\m44-labeler`.
Nếu repo đang để Private mà bạn không mở được trang: nhắn Cường thêm tài khoản GitHub của bạn vào *Collaborators*.

## 2. Tải dữ liệu nuScenes-mini

1. Vào <https://www.nuscenes.org/nuscenes#download>, **đăng ký / đăng nhập** (miễn phí, đồng ý điều khoản phi thương mại).
2. Mục **Full dataset (v1.0)** → phần **Mini** → tải `v1.0-mini.tgz` (~4 GB), chọn máy chủ **Asia** cho nhanh.
3. Giải nén vào thư mục `data\nuscenes` **bên trong repo** (cmd):

```bat
mkdir D:\m44-labeler\data\nuscenes
tar -xzf "%USERPROFILE%\Downloads\v1.0-mini.tgz" -C D:\m44-labeler\data\nuscenes
```

Giải nén xong phải thấy đúng các thư mục này:

```
D:\m44-labeler\data\nuscenes\
  maps\   samples\   sweeps\   v1.0-mini\
```

(Đã có nuScenes-mini ở `D:\data\nuscenes` thì bỏ qua bước này, app tự tìm thấy.)

## 3. Cài đặt

Bấm đúp **`setup_windows.bat`** trong `D:\m44-labeler`. Nó tạo môi trường Python riêng (`.venv`), cài thư viện, nạp sẵn kết
quả YOLO (không cần chạy YOLO, không cần GPU), và build giao diện. Mất 5–10 phút; cuối cùng in **"Xong"**.

## 4. Chạy

Bấm đúp **`run_app.bat`**. Cửa sổ đen hiện "Dang nap du lieu nuScenes…", khoảng 20 giây sau trình duyệt tự mở
<http://localhost:8770>. **Giữ cửa sổ đen mở** trong lúc dùng app – đóng nó là app tắt.

## 5. Thử nhanh 5 phút

1. Thanh trên cùng chọn frame **val 25**. Giữa là point cloud nhìn từ trên (BEV), bên phải là 6 camera.
2. Tab **Đối tượng** → gõ `_022` vào ô tìm → bấm chiếc xe đó → bấm **Shift+D** 4 lần (dời 2 m).
3. Sau chưa đến 1 giây, tab **Kiểm tra** hiện cờ trong nhóm **Chắc chắn**: *Không khớp ảnh* (camera), *Cuboid rỗng*
   (LiDAR, BEV có chấm đỏ là tia laser xuyên qua), *Nhảy vị trí* (so với frame trước/sau).
4. Bấm 🪄 cạnh một cờ → tab **Trợ lý** hiện gợi ý sửa → **Xem trước** (cuboid nét đứt) → **Áp dụng**. **Ctrl+Z** để hoàn tác.
5. Cờ nào bạn thấy là báo nhầm: bấm **✗** (phím 2). Đúng là lỗi: **✓** (phím 1).
6. Sang **val 26**, xoá vài cuboid (chọn rồi **Del**), bấm **Ctrl+B** – app chép cuboid từ frame trước sang.
7. Bấm **?** để xem toàn bộ phím tắt. **Ctrl+S** để lưu.

Nhãn bạn lưu nằm trong `cache\labels.db` **trên máy bạn** (không lên GitHub).

## 6. Cập nhật khi có bản mới

```bat
cd /d D:\m44-labeler
git pull
```

rồi bấm đúp lại `setup_windows.bat` (cài thêm thư viện / build lại giao diện nếu có) và `run_app.bat`.
**Nếu `run_app.bat` đang chạy thì đóng cửa sổ đen trước**, không thì app vẫn chạy bản cũ.

## Lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `[LOI] Chua cai Python` / `'python' is not recognized` | Cài lại Python, nhớ tích *Add python.exe to PATH*; mở cửa sổ cmd mới |
| `[LOI] Chua cai Node.js` | Cài Node.js LTS, mở cửa sổ cmd mới |
| `[LOI] Khong thay nuScenes-mini` / `khong co thu muc v1.0-mini` | Giải nén chưa đúng chỗ: phải có `data\nuscenes\v1.0-mini` (xem bước 2) |
| Trình duyệt báo *không kết nối được* | Chờ thêm 20–30 giây (đang nạp dữ liệu), hoặc xem cửa sổ đen có báo lỗi không |
| `error while attempting to bind on address ... 8770` | Đã có một `run_app.bat` khác đang chạy – đóng cửa sổ đen đó |
| Bấm nút báo **Method Not Allowed** / tính năng mới không chạy | App đang chạy bản cũ: đóng cửa sổ đen, chạy lại `run_app.bat`, trên trình duyệt bấm **Ctrl+F5** |
| Giao diện trống / lỗi sau khi `git pull` | Chạy lại `setup_windows.bat` rồi Ctrl+F5 |

## Không bắt buộc

- **Chat với Claude** trong tab Trợ lý: cần khoá API Anthropic (tạo file `.anthropic.env` ở thư mục repo với dòng
  `ANTHROPIC_API_KEY=...`). Không có thì các thẻ gợi ý sửa vẫn chạy bình thường.
- **Chạy YOLO lại từ đầu** thay vì dùng kết quả có sẵn: `pip install -r requirements-detect.txt` rồi
  `python -m labeler.precompute --split all` (trong thư mục `backend`, cần torch, chậm trên CPU).
