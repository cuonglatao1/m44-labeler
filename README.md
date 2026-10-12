# M44 Labeler

**Công cụ gán nhãn cuboid 3D cho dữ liệu lái xe tự động (nuScenes), kiểm tra chất lượng ngay trong lúc gán.**

Mỗi cuboid được kiểm bằng ba nguồn bằng chứng độc lập – **ảnh camera**, **point cloud LiDAR** và **chính vật đó ở các
frame trước / sau** – nên lỗi hiện thành cờ ngay khi người gán kéo cuboid, kèm gợi ý sửa một chạm, thay vì phải chạy công
cụ kiểm tra sau rồi quay lại sửa.

![Python](https://img.shields.io/badge/python-3.10–3.12-3776AB) ![Node](https://img.shields.io/badge/node-20%2B-339933)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688) ![React](https://img.shields.io/badge/frontend-React%20%2B%20three.js-61DAFB)
![nuScenes](https://img.shields.io/badge/data-nuScenes-555)

## Mục lục

- [Vấn đề](#vấn-đề)
- [Tính năng](#tính-năng)
- [Kết quả chính](#kết-quả-chính)
- [Bắt đầu nhanh](#bắt-đầu-nhanh)
- [Sử dụng](#sử-dụng)
- [Cách hoạt động](#cách-hoạt-động)
- [Cấu trúc dự án](#cấu-trúc-dự-án)
- [Phát triển](#phát-triển)
- [API](#api)
- [Giới hạn và lộ trình](#giới-hạn-và-lộ-trình)
- [Nguồn gốc, dữ liệu và giấy phép](#nguồn-gốc-dữ-liệu-và-giấy-phép)

## Vấn đề

Cách kiểm tra nhãn 3D phổ biến là chiếu cuboid lên ảnh và so với vật mà detector 2D (YOLO) nhìn thấy – đó là dự án
[M44 – 2D–3D Consistency Checker](https://github.com/cuonglatao1/T054-M44-3d-to-2d-tool). Nhưng camera chỉ kết luận được
khi vật nhìn rõ: trên nuScenes, **65 % cuboid camera không kiểm được** (bị che, ở xa, nhìn thấy dưới 60 %, hoặc thuộc class
YOLO không nhận như barrier, cọc giao thông). Đó lại chính là những cuboid khó gán nhất.

M44 Labeler kiểm chúng bằng một chuỗi bổ sung cho nhau:

| cuboid | được kiểm bằng |
|---|---|
| nhìn rõ trên ảnh | **camera**: hình chiếu so với box YOLO (M44) |
| camera bó tay nhưng LiDAR thấy | **hình học point cloud**: bắn tia laser qua cuboid, kích thước, mặt đất, đám điểm |
| cả hai đều yếu (bị che, ban đêm) | **thời gian**: so với chính vật đó ở các frame trước / sau |

## Tính năng

**Gán nhãn**
- BEV point cloud lớn, 6 camera, khung nhìn ngang / từ sau / **từ trên** của cuboid đang chọn.
- Kéo, xoay, co giãn cuboid trên BEV, trong các khung nhìn, hoặc **kéo thẳng trên ảnh camera**; phím tắt kiểu tool chuyên
  nghiệp; hoàn tác / làm lại.
- **Chép cuboid từ frame trước** (Ctrl+B): bù chuyển động xe ego và vận tốc của từng vật, giữ mã vật – 97 % cuboid chép
  sang đúng ngay trên dữ liệu mới.
- **Gợi ý cuboid từ ảnh**: bấm một box YOLO là có cuboid dựng từ điểm LiDAR trong vùng đó.

**Kiểm tra chất lượng (chạy live, ~60 ms / frame)**
- Camera: lệch vị trí, sai kích thước, sai class, không khớp ảnh, thiếu cuboid.
- LiDAR: cuboid rỗng, lấn khoảng trống, điểm tràn ra ngoài, lệch hướng so với đám điểm, kích thước phi lý, lơ lửng / chìm,
  chồng nhau.
- Thời gian: nhảy vị trí, nhảy kích thước, nhảy hướng (bắt cả quay ngược 180°), nhảy độ cao, đổi class giữa các frame.
- **Vật bị quên gán**, kể cả khi camera không thấy: vật có ở frame trước và sau mà frame này thiếu (thời gian), xác nhận
  bằng điểm LiDAR ở chỗ đó; gợi ý tạo cuboid ở vị trí nội suy (phím `G`).
- Cờ được chia **Chắc chắn** (≥ 2 nguồn cùng báo – trúng lỗi thật 98 %) / **Cần xem** (1 nguồn); mỗi cuboid có **mức tin
  cậy QC** và thẻ tổng quan cho biết độ phủ của từng nguồn.
- **Gợi ý sửa** cho mọi loại cờ, có xem trước nét đứt; cờ một nguồn phải xem trước mới áp dụng được.
- Người gán bấm ✓ / ✗ để xác nhận hoặc bác cờ; phán quyết ✗ đi theo vật khi chép sang frame sau.
- Trợ lý **Claude** (tuỳ chọn) giải thích cờ và đề xuất sửa dựa trên số liệu thật của frame.

**Khác**
- Chế độ **pilot** để đo người gán: frame bắt đầu rỗng, không lộ nhãn gốc, đồng hồ, chấm điểm khi nộp.
- Xuất nuScenes detection results, JSON, hoặc tạo task trên **CVAT**.
- Chạy hoàn toàn offline trên Windows, không cần GPU.

## Kết quả chính

Đo bằng lỗi cài có đáp án (dời 1–2,5 m, kích thước ×0,6 / ×1,6, xoay 90°, đổi class) như dự án M44; chi tiết, giao thức
và cách chạy lại ở [docs/EVALUATION.md](docs/EVALUATION.md).

| | camera (M44) | **M44 Labeler** |
|---|---|---|
| tỉ lệ cuboid kiểm được (độ phủ, mini val) | 35 % | **100 %** |
| lỗi bắt được trên cuboid camera không kiểm được (mini val) | 4 % | **99 %** |
| vật bị quên gán mà camera không thấy được phát hiện (mini val) | 7 % | **70 %** |
| lỗi bắt được, 146 scene val **mới** (ngày / mưa / **đêm**)¹ | – | **98 % / 98 % / 99 %** |
| vật bị quên gán được phát hiện, 146 scene mới¹ | – | **77 %** (0,06 báo nhầm / frame) |
| lỗi **nhỏ** giống người thật (lệch 0,3–0,6 m, xoay 10–20°, quay ngược, sai dài / cao 25 %), 146 scene mới¹ | – | **85 %** |
| cờ nhóm "Chắc chắn" trúng lỗi thật (mini val) | – | **98 %** (0,14 báo nhầm / frame) |
| cuboid chép sang frame sau đúng ngay, 146 scene mới | – | **97 %** |
| gán cả scene từ đầu (người gán mô phỏng, mini val): thao tác tay so với vẽ tay mọi vật | 100 % | **9 %** (tool đặt đúng ngay 94 % cuboid) |

¹ Kiểm tra theo thời gian + kích thước + chồng nhau, tool đóng băng trước khi đo; kiểm tra LiDAR và camera chưa được đo
trên dữ liệu mới.

## Bắt đầu nhanh

Cần Windows 10/11, **Python 3.11**, **Node.js 20+** và **nuScenes-mini** (~4 GB, tải miễn phí tại
<https://www.nuscenes.org/nuscenes#download> sau khi đăng ký).

```bash
git clone https://github.com/cuonglatao1/m44-labeler.git
cd m44-labeler
```

1. Giải nén `v1.0-mini.tgz` vào `data\nuscenes` trong repo (phải có `data\nuscenes\v1.0-mini`, `samples`, `sweeps`), hoặc
   để ở `D:\data\nuscenes`, hoặc trỏ biến môi trường `NUSC_ROOT` tới đó.
2. Bấm đúp **`setup_windows.bat`**: tạo môi trường Python, cài thư viện, nạp kết quả YOLO có sẵn, build giao diện.
3. Bấm đúp **`run_app.bat`** → trình duyệt tự mở <http://localhost:8770>.

Hướng dẫn từng bước cho người không chuyên (kèm "thử nhanh 5 phút" và các lỗi thường gặp):
[docs/HUONG_DAN_CAI_DAT.md](docs/HUONG_DAN_CAI_DAT.md).

<details>
<summary>Cài thủ công (Linux / macOS / Windows)</summary>

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\...
cd backend && ../.venv/bin/python -m labeler.precompute --bundled && cd ..
cd frontend && npm install && npm run build && cd ..
cd backend && NUSC_ROOT=/path/to/nuscenes ../.venv/bin/python -m uvicorn labeler.main:app --port 8770
```
</details>

## Sử dụng

**Bố cục.** Thanh công cụ bên trái (thu gọn bằng `\`), BEV ở giữa với các khung nhìn của cuboid đang chọn, cột camera
(một ảnh lớn tự theo cuboid / cờ đang chọn và 6 ảnh nhỏ), panel phải gồm **Đối tượng**, **Kiểm tra** (cờ, lọc theo
nguồn), **Trợ lý** (gợi ý sửa, chat) và bảng thuộc tính. Kéo đường ranh giữa các vùng để đổi kích thước. Bấm vào ảnh lớn
để xem toàn màn hình.

**Phím tắt** (bấm `?` trong app để xem đầy đủ)

| phím | thao tác |
|---|---|
| `V` · `B` (rồi bấm lên BEV) | chọn · thêm cuboid |
| `W A S D` (Shift ×5) · `Q E` · `R F` · `T` | dịch 10 cm · xoay 1° · nâng hạ 5 cm · quay đầu 180° |
| kéo trên BEV / ảnh camera / khung nhìn | dời, co giãn, xoay cuboid đang chọn |
| `Ctrl+B` · `Ctrl+Shift+B` | chép cuboid từ frame trước / sau |
| bấm ô cam · `Shift`+bấm box YOLO · `G` · `Shift+G` | gợi ý cuboid từ ảnh |
| `N` / `P` · `1` / `2` | cờ tiếp / trước · cờ đúng / báo động giả |
| `G` trên cờ "Thiếu cuboid" | tạo cuboid ở vị trí dự đoán |
| `Del` · `Esc` · `Ctrl+Z` / `Ctrl+Y` · `Ctrl+S` | xoá · bỏ chọn · hoàn tác / làm lại · lưu |
| `←` `→` · `C` · `3` · `\` | đổi frame · căn giữa · xoay 3D · thu gọn thanh công cụ |

**Hai cách làm việc**
- *Gán từ đầu:* chọn "Frame mới: Rỗng" (menu ⋯). Ở frame đầu, các ô cam "Thiếu cuboid" là danh sách vật cần gán
  (`Shift+G` gợi ý tất cả); sang frame sau thì `Ctrl+B` rồi chỉnh các cuboid có cờ, vật mới thì bấm từng ô cam (Shift+G ở
  frame sau chủ yếu gợi ý vật YOLO nhận nhầm – xem [đánh giá](docs/EVALUATION.md#5b-công-sức-gán-cả-scene-từ-đầu-người-gán-mô-phỏng)).
- *Kiểm tra nhãn có sẵn:* mở frame với nhãn gốc (hoặc nhãn đã lưu), xử lý nhóm cờ **Chắc chắn** trước, rồi xem nhóm
  **Cần xem**; bấm ✗ cho cờ báo nhầm.

**Trợ lý Claude (tuỳ chọn).** Tạo file `.anthropic.env` ở thư mục repo với dòng `ANTHROPIC_API_KEY=...` (hoặc đặt biến
môi trường). Không có khoá thì thẻ gợi ý sửa vẫn chạy bình thường, chỉ không có chat.

**Xuất.** Menu ⋯ → *Xuất nuScenes* (detection results, hệ global) hoặc *Xuất JSON* (hệ LiDAR). Lên CVAT:
`pip install -r requirements-cvat.txt`, đặt `CVAT_URL` + `CVAT_ACCESS_TOKEN`, rồi
`python -m labeler.export_cvat --name "..."` trong `backend`.

## Cách hoạt động

```
                          ┌──────────── trình duyệt (React + three.js) ─────────────┐
                          │ BEV · 6 camera · khung nhìn · danh sách cờ · trợ lý      │
                          └───────────────┬──────────────────────────▲──────────────┘
                     cuboid (mỗi lần sửa) │                          │ cờ + mức tin cậy + gợi ý
                          ┌───────────────▼──────────────────────────┴──────────────┐
                          │ FastAPI  labeler/main.py                                 │
                          │  ├ camera   m44/match.py      chiếu ↔ box YOLO           │
                          │  ├ LiDAR    labeler/lidar_qc.py  bắn tia, kích thước…    │
                          │  ├ thời gian labeler/track.py   so với frame trước/sau   │
                          │  ├ gộp      labeler/qc.py       chắc chắn / cần xem      │
                          │  └ sửa      labeler/fix.py, fix_qc.py, propagate.py      │
                          └──────────────────────────────────────────────────────────┘
```

- **Camera** (`backend/m44/`): chiếu 8 đỉnh cuboid lên 6 camera, ghép với box YOLO bằng Hungarian trên IoU, gắn cờ khi
  IoU thấp, tỉ lệ kích thước lệch, class không tương thích, cuboid không có box hoặc box không có cuboid. Chỉ kết luận
  khi vật đủ gần, đủ to và không bị che quá nửa.
- **LiDAR** (`labeler/lidar_qc.py`): file LiDAR của nuScenes lưu đủ mọi phát laser (32 tia × ~1086 cột), cả phát không có
  phản hồi. Mỗi cuboid được *bắn tia* bằng đúng các phát đó: phản hồi **trước** cuboid là bị che (không phải bằng chứng
  sai), **trong** cuboid là chạm vật, **sau** cuboid là laser đi xuyên qua chỗ cuboid khai là có vật. Nhờ vậy phân biệt
  được "bị che" với "cuboid rỗng". Thêm: điểm cùng vật tràn ra ngoài, trục đám điểm, đáy so với mặt đất, kích thước so với
  khoảng của class, hai xe chồng nhau.
- **Vật bị quên gán** (`labeler/missing.py`): vật có cuboid ở frame trước và frame sau mà frame này không có → dự đoán
  cuboid bằng nội suy; LiDAR có điểm ở đó thì thêm một nguồn xác nhận, còn tia laser xuyên qua trống trơn thì bỏ (vật
  thật sự không ở đó); YOLO thấy vật chưa có cuboid đúng chỗ đó thì gộp làm một.
- **Thời gian** (`labeler/track.py`): vật được nối qua các keyframe (±2 s) bằng mã vật (`instance_token` của nuScenes, hoặc
  mã `obj_…` mà app gán và giữ khi chép cuboid), sau khi bù chuyển động xe ego. Kích thước phải gần trung vị của chuỗi; vị
  trí và hướng gần dự đoán nội suy / ngoại suy tốt nhất (một frame bên cạnh sai không làm cuboid đúng bị cờ); class phải
  giống đa số frame khác.
- **Mức chắc chắn** (`labeler/qc.py`): ba nguồn độc lập, nên cuboid bị ≥ 2 nguồn cùng cờ gần như chắc chắn sai.
- **Ngưỡng** chỉnh trên tập train, mỗi kiểm tra lấy cấu hình bắt nhiều lỗi nhất với báo nhầm ≤ 0,5 % cuboid sạch
  (`configs/lidar_qc.json`, `labeler/calib_lidar.py`); ngưỡng camera là `configs/tuned.json` của M44.
- Lý do của từng lựa chọn và các phương án đã thử rồi bỏ: [docs/decision-log.md](docs/decision-log.md).

## Cấu trúc dự án

```
backend/
  m44/                lõi kiểm tra camera của dự án M44 (loader, chiếu, ghép cặp, cài lỗi, đánh giá, CVAT I/O)
  labeler/
    main.py           API FastAPI, gộp ba nguồn kiểm tra
    dataset.py        frame nuScenes, point cloud, ảnh, cache YOLO
    store.py          SQLite: nhãn đã lưu, nhật ký, phán quyết ✓/✗, bài pilot
    lidar_qc.py       kiểm tra LiDAR            track.py      kiểm tra theo thời gian
    missing.py        vật bị quên gán (thời gian + LiDAR + camera)
    qc.py             mức chắc chắn của cờ      propagate.py  chép cuboid sang frame sau
    propose.py        gợi ý cuboid từ box 2D    fix.py, fix_qc.py  gợi ý sửa
    assistant.py      trợ lý Claude (tuỳ chọn)  precompute.py cache YOLO
    calib_lidar.py    chỉnh ngưỡng              eval_*.py     các bài đo (docs/EVALUATION.md)
    score.py, pilot_report.py   chấm điểm và báo cáo pilot
    export.py, export_cvat.py   xuất nuScenes / CVAT
frontend/src/         React + react-three-fiber: App.jsx, BevView, CameraView, SideView, panels, assistant
configs/              tuned.json (ngưỡng camera), lidar_qc.json (ngưỡng LiDAR + thời gian)
precomputed/          kết quả YOLO của 404 keyframe nuScenes-mini (nạp bằng precompute --bundled)
docs/                 hướng dẫn cài đặt, đánh giá, pilot, định dạng JSON, nhật ký quyết định
tests/                test chiếu, loader, kiểm tra LiDAR / thời gian (sweep tổng hợp)
cache/  data/         sinh ra khi chạy / dữ liệu nuScenes – không đưa lên git
```

## Phát triển

```bash
run_dev.bat                                   # giao diện ở http://localhost:5173, tự nạp lại khi sửa frontend
python tests/test_lidar_qc.py                 # test kiểm tra LiDAR + thời gian, không cần dữ liệu
```

Sửa code backend thì phải chạy lại `run_app.bat` (đóng cửa sổ cũ trước). Chỉnh lại ngưỡng và chạy các bài đo: xem
[docs/EVALUATION.md](docs/EVALUATION.md#7-chạy-lại).

| biến môi trường | mặc định | |
|---|---|---|
| `NUSC_ROOT` | `data/nuscenes` (hoặc `D:\data\nuscenes`) | thư mục nuScenes |
| `NUSC_VERSION` | `v1.0-mini` | phiên bản nuScenes |
| `M44_CFG` | `configs/tuned.json` | ngưỡng kiểm tra camera |
| `ANTHROPIC_API_KEY` | – | bật chat với Claude (hoặc file `.anthropic.env`) |
| `M44_LLM_MODEL`, `M44_LLM_EFFORT` | `claude-opus-5-5`, `low` | model và mức suy nghĩ của trợ lý |

Định dạng dữ liệu trao đổi giữa các module: [docs/json-formats.md](docs/json-formats.md).

## API

| | |
|---|---|
| `GET /api/frames` | danh sách frame (val trước, rồi train) |
| `GET /api/frames/{i}?init=gt\|empty` | calib, cuboid hiện tại, box YOLO, kết quả kiểm tra |
| `GET /api/frames/{i}/points` · `/image/{cam}` | point cloud (float32 x, y, z, intensity) · ảnh camera |
| `POST /api/frames/{i}/check` | kiểm tra cuboid chưa lưu: cờ ba nguồn, `qc` từng cuboid, `coverage` |
| `PUT /api/frames/{i}/boxes` | lưu cuboid |
| `POST /api/frames/{i}/propagate` | chép cuboid từ frame trước / sau |
| `POST /api/frames/{i}/propose` · `/propose_missing` | gợi ý cuboid từ một box 2D · cho mọi vật thiếu cuboid |
| `POST /api/frames/{i}/suggest` | gợi ý sửa cho một cờ |
| `POST /api/frames/{i}/events` · `GET /api/feedback/summary` | ghi / tổng hợp phán quyết ✓ / ✗ |
| `POST /api/assistant/chat` | chat với Claude (server-sent events) |
| `POST /api/frames/{i}/pilot_submit` · `GET /api/pilot/results` | nộp bài và kết quả pilot |
| `GET /api/export?fmt=raw\|nuscenes` · `GET /api/config` | xuất mọi frame đã lưu · cấu hình |

## Giới hạn và lộ trình

**Giới hạn hiện tại**
- Số đo dùng lỗi **cài tổng hợp** (cả bộ lỗi nhỏ giống người thật); lỗi của người gán thật chưa được đo.
- Kiểm tra theo thời gian chặt hơn từ bản v3: bắt lỗi nhỏ tốt hơn nhiều nhưng báo nhầm ~0,4 / frame (~2 / frame khi
  cuboid không có mã vật – nên dùng Ctrl+B).
- Kiểm tra LiDAR và camera mới được đo trên nuScenes-mini; kiểm tra LiDAR còn báo nhầm khá nhiều (~2,9 / frame, chủ yếu
  xe tối màu cho tia laser xuyên qua) – nhóm cờ "Chắc chắn" che phần lớn nhược điểm này.
- Chỉ hỗ trợ nuScenes (một LiDAR 32 tia + 6 camera); Windows được kiểm nhiều nhất.

**Lộ trình**
- [x] Xem, sửa, gợi ý cuboid từ ảnh, xuất nuScenes / CVAT
- [x] Kiểm tra camera trong lúc gán, gợi ý sửa, trợ lý Claude
- [x] Kiểm tra LiDAR và theo thời gian, mức chắc chắn, độ phủ
- [x] Chép cuboid sang frame sau, mã vật
- [x] Kiểm tra trên 146 scene nuScenes mới (theo thời gian, kích thước, chồng nhau, chép cuboid)
- [x] Phát hiện vật bị quên gán không cần camera (thời gian + LiDAR)
- [ ] Pilot với người gán thật: nhiều frame liên tiếp, có / không có trợ giúp ([docs/PILOT_APP.md](docs/PILOT_APP.md))
- [ ] Đo kiểm tra LiDAR + camera trên dữ liệu mới; chỉnh ngưỡng LiDAR trên tập lớn hơn
- [ ] Cộng dồn nhiều sweep LiDAR; vận tốc ngay từ frame đầu scene; chỉnh ngưỡng từ phán quyết ✓ / ✗

## Nguồn gốc, dữ liệu và giấy phép

- Lõi kiểm tra camera (`backend/m44/`) lấy từ dự án
  [T054-M44-3d-to-2d-tool](https://github.com/cuonglatao1/T054-M44-3d-to-2d-tool) (commit `4149620`); loader được bổ sung
  `lidar2global`, `scene`, `timestamp` và mã vật. Sửa logic kiểm tra camera thì cần sửa ở cả hai repo.
- Dữ liệu: [nuScenes](https://www.nuscenes.org/) (Motional), theo điều khoản sử dụng của nuScenes – dùng cho mục đích phi
  thương mại; repo không chứa dữ liệu, mỗi người tự tải bằng tài khoản của mình.
- Phát hiện 2D: [Ultralytics YOLO](https://github.com/ultralytics/ultralytics) (`yolo11m`, COCO); repo kèm sẵn kết quả
  YOLO cho nuScenes-mini.
- Thực hiện trong khuôn khổ đề tài M44 – chương trình AI20K. Mã nguồn chưa gắn giấy phép.
