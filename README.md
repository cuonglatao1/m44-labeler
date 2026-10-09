# M44 Labeler

App gán nhãn cuboid 3D (nuScenes) có **kiểm tra 2D–3D ngay trong lúc gán**: mỗi cuboid được chiếu lên 6 camera và so
với vật thể YOLO thấy trên ảnh, cuboid lệch / sai class / thiếu hiện cờ ngay, không phải chạy tool sau rồi quay lại sửa.

Tách từ [T054-M44-3d-to-2d-tool](https://github.com/cuonglatao1/T054-M44-3d-to-2d-tool) (commit `4149620`):
`backend/m44/` là lõi của M44 (loader, chiếu, ghép cặp, cài lỗi, đánh giá, CVAT I/O) chép nguyên,
`configs/tuned.json` là ngưỡng đã chỉnh trên train. Sửa logic kiểm tra thì sửa ở cả hai repo.
Khác bản gốc duy nhất: `load_frames_nusc` trả thêm `lidar2global` (để xuất hệ global), `scene`, `timestamp` và
`instance` của mỗi cuboid (kiểm tra theo thời gian).

## Cấu trúc

```
backend/
  m44/          lõi M44 (chép từ repo cũ, không phụ thuộc web)
  labeler/      FastAPI: main.py (API), dataset.py (frame/point/ảnh), store.py (SQLite), precompute.py (cache YOLO),
                lidar_qc.py + track.py (kiểm tra LiDAR / thời gian), fix.py + fix_qc.py (gợi ý sửa), calib_lidar.py,
                eval_*.py (đo)
frontend/       React + Vite + react-three-fiber: BEV point cloud, 6 camera, danh sách cờ
configs/        tuned.json – ngưỡng của checker camera (đổi bằng biến môi trường M44_CFG);
                lidar_qc.json – ngưỡng LiDAR / thời gian (labeler/calib_lidar.py)
cache/          dets/<sample>.json (YOLO), labels.db (nhãn đã lưu + log) – không commit
precomputed/    yolo_dets_nuscenes_mini.json.gz – YOLO của 404 frame mini, nạp bằng precompute --bundled
tests/          test chiếu / loader chép từ repo cũ; test_lidar_qc.py (sweep tổng hợp, chạy bằng python)
```

## Chạy (Windows)

**Người mới trong nhóm: làm theo [docs/HUONG_DAN_CAI_DAT.md](docs/HUONG_DAN_CAI_DAT.md)** (cài Python + Node, tải
nuScenes-mini, bấm đúp hai file, thử nhanh 5 phút). Tóm tắt:

1. Python 3.11 + Node.js 20+, `git clone https://github.com/cuonglatao1/m44-labeler.git`.
2. nuScenes-mini (`v1.0-mini.tgz`) giải nén vào `data
uscenes` của repo (hoặc `D:\data
uscenes`, hoặc đặt `NUSC_ROOT`).
3. `setup_windows.bat`: cài thư viện, nạp kết quả YOLO có sẵn (`precomputed/yolo_dets_nuscenes_mini.json.gz`, không cần
   torch), build giao diện. Muốn chạy YOLO mới: `pip install -r requirements-detect.txt` rồi
   `cd backend && python -m labeler.precompute --split all`.
4. `run_app.bat` → <http://localhost:8770>. Khi sửa code: `run_dev.bat` (giao diện ở <http://localhost:5173>); sửa
   backend thì phải chạy lại `run_app.bat`.

## Giao diện

Bố cục theo các tool gán nhãn 3D chuyên nghiệp (Segments.ai, Supervisely, SageMaker Ground Truth, CVAT 3D):
thanh công cụ dọc bên trái (chọn `V`, thêm cuboid `B`, gợi ý, căn giữa `C`, xoay 3D `3`), BEV lớn ở giữa với 2 khung
nhìn ngang nổi ở đáy khi chọn cuboid, cột camera (một camera phóng to tự theo cuboid / cờ đang chọn + 6 ảnh nhỏ),
panel phải 2 tab **Đối tượng** (nhóm theo class, trạng thái kiểm tra, khoảng cách) / **Kiểm tra** (cờ, ✓ / ✗) và
bảng thuộc tính có ô nhập số X Y Z, L W H, hướng. Màu cuboid theo class, cuboid có cờ viền đỏ; chuyển sang tô theo
kết quả kiểm tra ở góc BEV. Chọn cuboid ở bất kỳ đâu (danh sách, ảnh, BEV, cờ) thì BEV trượt tới và phóng vào nó (nút ⌖ ở góc BEV để tắt). Bấm vào ảnh camera lớn (hoặc bấm đúp ảnh nhỏ) mở trình xem toàn màn hình: lăn chuột zoom, kéo để di chuyển, ← → đổi camera, Esc đóng. Thanh trạng thái gợi ý thao tác; `?` mở bảng phím tắt. Icon Lucide, font Inter (đóng
gói sẵn, chạy offline).

## Gán nhãn

| Thao tác | |
|---|---|
| Kéo thân cuboid đang chọn / chấm vàng / chấm xanh (BEV) | di chuyển / co giãn mặt đó / xoay |
| Kéo cạnh trên, dưới, trái, phải trong 2 view ngang; kéo thân | chiều cao, đáy, dài / rộng; nâng hạ |
| W A S D (Shift ×5) · Q / E · R / F | dịch 10 cm · xoay 1° · nâng hạ 5 cm |
| B rồi bấm lên BEV | thêm cuboid (class chọn ở thanh trên, kích thước điển hình, đặt sát mặt đất) |
| Bấm ô cam · Shift+bấm box YOLO · G · Shift+G | gợi ý cuboid từ ảnh (một vật · cờ đang chọn · mọi ô cam) |
| T · 1 / 2 | quay đầu 180° · cờ đúng / báo động giả (bấm lại để bỏ) |
| Del · Esc · Ctrl+Z / Ctrl+Y · Ctrl+S | xoá · bỏ chọn · hoàn tác / làm lại · lưu |
| N / P · ← → | cờ tiếp / trước · frame |
| Ctrl+B · Ctrl+Shift+B | chép cuboid từ frame trước / sau (giữ mã vật) |

"Frame mới: GT / rỗng" chọn cách mở frame chưa lưu. Gán từ đầu (rỗng) thì các ô cam `MISSING_3D` chính là danh sách
vật thể cần gán. Mỗi lần lưu ghi thời gian mở frame → lưu vào bảng `events` (dùng cho P4).

## Gợi ý cuboid từ ảnh (2D → 3D)

`backend/labeler/propose.py`: bỏ mặt đất (min-z lưới 1 m) → điểm LiDAR rơi trong box 2D → gom cụm 3D → với 4 cụm lớn
nhất: nới ra cả vật, xoay theo hình chữ nhật diện tích nhỏ nhất (thử cả 2 trục làm chiều dài), kéo kích thước tới cỡ
điển hình của class về phía LiDAR không thấy → chiếu lại lên ảnh, chọn ứng viên khớp box 2D nhất (trừ điểm nếu lệch
kích thước điển hình). Không có cụm nào thì đặt cỡ điển hình theo tia qua đáy box 2D chạm mặt đất.

Đo bằng `python -m labeler.eval_propose --split val` (val **không** dùng khi chỉnh; gợi ý từ box YOLO khớp với từng
cuboid GT, so với chính cuboid đó):

| class | n | IoU BEV trung vị | IoU ≥ 0,5 | lệch tâm trung vị | lệch hướng trung vị (mod 180°) |
|---|---|---|---|---|---|
| car | 707 | 0,53 | 55% | 0,56 m | 10° |
| pedestrian | 620 | 0,42 | 38% | 0,23 m | 40° (người không có hướng rõ) |
| truck | 57 | 0,51 | 51% | 1,04 m | 3° |
| bus | 24 | 0,48 | 38% | 1,10 m | 11° |

Tức là khoảng một nửa số xe chỉ cần chỉnh nhẹ sau khi bấm; hướng đầu xe (180°) phải tự kiểm (phím T).
Gợi ý hàng loạt bỏ ô trùng vật đã có cuboid và gợi ý có hình chiếu khớp box 2D dưới 0,1.

## Đo hiệu quả (P4)

Chấm theo đúng luật pilot phần 2 của repo M44: mục tiêu = `car`, `pedestrian` nhìn thấy ≥ 60 % trong 30 m; **đúng** =
tâm ≤ 0,7 m, cạnh ±25 %, hướng ≤ 20° (bỏ hướng với người); **lệch** = đúng class trong 2 m; còn lại **sai / thừa**.

Mốc máy – chỉ bấm Shift+G trên frame rỗng, không chỉnh gì (`python -m labeler.eval_assist --split val`):

| | mục tiêu | đúng | lệch (chỉ cần chỉnh) | bỏ sót | cuboid sai / thừa |
|---|---|---|---|---|---|
| cả val (81 frame) | 1505 | 32 % | 29 % | 39 % | 246 / 1404 |
| val 25 (frame pilot CVAT) | 17 | 5 | 8 | 4 | 4 |
| val 60 (frame pilot app) | 18 | 5 | 5 | 8 | 4 |

Bấm Shift+G lần hai không thêm được gì (`--rounds 2`): phần bỏ sót là vật YOLO không thấy hoặc không có điểm LiDAR –
annotator phải tự thêm.

## Trợ lý QC và gợi ý sửa

Tab **Trợ lý** (hoặc nút 🪄 ở mỗi cờ trong tab Kiểm tra): chọn một cờ là trợ lý đưa ngay **gợi ý sửa** dạng thẻ –
đổi class / dời-xoay-co giãn / xoá cuboid thừa / tạo cuboid còn thiếu / khuyên đánh dấu báo động giả – kèm số liệu
(khớp ảnh trước → sau, số điểm LiDAR) và mức tin cậy. **Xem trước** vẽ cuboid đã sửa nét đứt trên BEV và ảnh;
**Áp dụng** sửa thật (Ctrl+Z để hoàn tác), rồi Lưu như thường.

- Gợi ý tính bằng hình học (`backend/labeler/fix.py`), chạy offline, không cần mạng.
- Có khoá API Anthropic thì bật thêm **chat với Claude** (`backend/labeler/assistant.py`): hỏi "vì sao bị cờ này?",
  "frame còn vấn đề gì?", "cuboid này nên dài bao nhiêu?"… Claude đọc frame qua công cụ (tổng quan, chi tiết cuboid,
  `suggest_fix`) nên không bịa số; mọi đề xuất sửa hiện thành thẻ có nút Áp dụng. Trả lời stream dần về trình duyệt.
- Bật Claude: `ant auth login`, hoặc đặt `ANTHROPIC_API_KEY`, hoặc tạo file `.anthropic.env` ở thư mục repo với dòng
  `ANTHROPIC_API_KEY=...` (đã gitignore). Model mặc định `claude-opus-5-5`, effort `low` (trả lời nhanh, ngắn);
  đổi bằng `M44_LLM_MODEL` (ví dụ `claude-sonnet-5-5` rẻ hơn một nửa) và `M44_LLM_EFFORT`. Có bật fallback phía
  server (`fallbacks: "default"`) nên nếu Claude từ chối vì bộ lọc an toàn, yêu cầu được chạy lại trên model dự phòng.

Đo bằng `python -m labeler.eval_fix --split val`: cài lỗi có đáp án vào GT (dời 1–2,5 m, kích thước ×0,6/×1,6, xoay
90°, đổi class, xoá), áp dụng gợi ý cho mỗi lỗi bị cờ, chấm theo luật pilot (tâm 0,7 m, cạnh 25 %, hướng 20°):

| lỗi | bị cờ | gợi ý sửa đúng |
|---|---|---|
| đổi class | 85 | 93 % |
| xoay 90° | 14 | 79 % |
| sai kích thước | 82 | 74 % |
| dời chỗ | 79 | 43 % |
| xoá (tạo lại từ ảnh) | 152 | 18 % |
| **tất cả** | **412** | **51 %** |

Gợi ý "chỉnh cuboid" có **tin cậy cao** khi cuboid mới ôm thêm rõ rệt điểm LiDAR của vật: 86/90 lần (96 %) là lỗi
thật. **Tin cậy thấp** = chỉ dựa vào box YOLO: 65/89 (73 %) là lỗi thật – với cờ báo động giả trên cuboid đúng, áp
dụng mù quáng sẽ làm hỏng 33 % số đó, nên luôn xem trước. Gợi ý không thay người gán; nó rút ngắn việc đoán cần sửa gì.

## Kiểm tra bằng LiDAR và theo thời gian (cuboid camera không kiểm được)

Ở val, **65 % cuboid camera không kiểm được** (bị che, xa, nhìn thấy < 60 %, class YOLO không nhận). App kiểm chúng
bằng một chuỗi bổ sung cho nhau: cuboid nhìn rõ → camera (M44); camera bó tay → hình học point cloud; cả hai đều yếu →
chính vật đó ở các frame trước / sau. Cờ mới có nhãn nguồn **LiDAR** (xanh ngọc) / **Thời gian** (tím), lọc được ở tab
Kiểm tra; inspector có mục **Kiểm tra QC** (camera / LiDAR / thời gian kiểm được không, kết quả, số tia và điểm), thẻ
Tổng quan frame tô mỗi cuboid theo **mức tin cậy QC** (cao = ≥ 2 nguồn xác nhận, vừa = 1, có cờ, chưa kiểm) và hiện độ
phủ của từng nguồn. Chọn cuboid có cờ LiDAR thì BEV chấm đỏ chỗ các tia đi xuyên qua nó.

**LiDAR** (`backend/labeler/lidar_qc.py`). File `.bin` của nuScenes là range image có tổ chức: 32 tia × ~1086 cột, cả
phát không về cũng có chỗ (điểm giả sát cảm biến). Nên mỗi cuboid được *bắn tia* với đúng các phát LiDAR thật: phát nào
đi qua cuboid thì trả về **trước** cuboid (bị che – không phải bằng chứng sai), **trong** cuboid (chạm) hay **sau**
cuboid (xuyên qua chỗ cuboid nói là có vật). Số "điểm kỳ vọng" vì vậy đã tính che khuất, không cần mô hình 1/d².

| cờ | ý nghĩa | gợi ý sửa |
|---|---|---|
| `LIDAR_EMPTY` | đủ tia tới mà gần như không tia nào chạm, không có điểm thân vật – cuboid ma / dời chỗ | trượt về đám điểm gần nhất chưa có cuboid, không có thì xoá |
| `LIDAR_FREE` | phần lớn tia tới xuyên qua – quá to / lệch | dựng lại theo điểm hoặc trượt (chọn cái LiDAR thấy ổn hơn) |
| `LIDAR_SPILL` | điểm cùng vật (nối liền với điểm trong cuboid) nằm ngoài – quá nhỏ / lệch | như trên |
| `LIDAR_HEADING` | trục dài đám điểm lệch hướng cuboid (xe thấy rõ chiều dài) | xoay theo đám điểm |
| `SIZE_IMPLAUSIBLE` | dài / rộng / cao ngoài khoảng của class | khớp cỡ class khác loại (xe ↔ người) → đổi class; không thì dựng theo điểm / cỡ điển hình |
| `FLOATING` / `SUNKEN` | đáy cách mặt đất quanh cuboid quá xa | đặt sát mặt đất |
| `BEV_OVERLAP` | hai cuboid chồng đáy | cuboid rỗng chắc chắn → xoá, không thì xem cả hai |

**Thời gian** (`backend/labeler/track.py`). Cùng một vật qua các keyframe (±4 frame = ±2 s; nối bằng `instance_token`
của nuScenes, cuboid vẽ trong app thì nối bằng cuboid gần nhất sau khi bù chuyển động xe ego) phải giữ kích thước,
class và đi mượt: `TRACK_SIZE` (lệch trung vị chuỗi > 10 %, gợi ý: lấy trung vị), `TRACK_JUMP` (lệch vị trí nội suy /
ngoại suy, gợi ý: về vị trí đó), `TRACK_YAW` (lệch hướng, bắt cả quay ngược 180° – camera không bắt được), `TRACK_CLASS`
(gợi ý: class đa số). Dự đoán tốt nhất trong các cách (nội suy trước–sau, ngoại suy hai frame cùng phía) được dùng, nên
một frame bên cạnh sai không làm cuboid đúng bị cờ. Frame bên cạnh lấy nhãn đã lưu, chưa lưu thì GT; ở chế độ pilot
chỉ lấy nháp của chính người đó (không lộ GT).

**Ngưỡng** (`configs/lidar_qc.json`) chỉnh trên train bằng `python -m labeler.calib_lidar --split train`: mỗi cuboid GT
được đo nguyên vẹn và trên bản cài lỗi (dời 1–2,5 m, ×0,6 / ×1,6, xoay 90°, đổi class, nâng/hạ 0,6 m); mỗi kiểm tra × nhóm
class lấy cấu hình có recall cao nhất mà báo động giả trên cuboid sạch ≤ 0,5 %. Khoảng kích thước chọn kiểu bỏ-một-scene
(mini chỉ có 8 scene train, cùng vài vật lặp lại) → nới ×1,4. Kiểm tra chạy trong ~60 ms/frame nên vẫn live khi kéo.

Đo trên val (không dùng khi chỉnh), cùng giao thức cài lỗi của M44 (`python -m labeler.eval_lidar --split val`; 81 frame,
4441 cuboid, 1325 lỗi, seed 0, cài vào mọi frame nên frame bên cạnh cũng có lỗi):

| độ phủ trên GT sạch | camera | LiDAR | thời gian | ít nhất một |
|---|---|---|---|---|
| mọi cuboid | 35 % | 54 % | 100 % | 100 % |
| cuboid camera không kiểm được (65 %) | – | 44 % | 99 % | 100 % |

| recall, cuboid camera **không** kiểm được | n | camera | LiDAR | thời gian | LiDAR + thời gian |
|---|---|---|---|---|---|
| dời chỗ | 202 | 5 % | 18 % | 96 % | 96 % |
| sai kích thước | 165 | 5 % | 65 % | 99 % | 100 % |
| xoay 90° | 137 | 1 % | 28 % | 99 % | 99 % |
| đổi class | 168 | 4 % | 100 % | 99 % | 100 % |
| **tất cả** | **672** | **4 %** | **52 %** | **98 %** | **99 %** |

Với cuboid camera kiểm được, kết hợp nâng recall từ 67 % (camera) lên 100 %. Báo động giả trên GT sạch: camera 2,48 /
frame, LiDAR 2,93 / frame (nhiều nhất `LIDAR_EMPTY` 1,3 / frame – xe tối màu / kính cho tia xuyên qua; và mặt đất),
thời gian 0,07 / frame. Gợi ý sửa: theo thời gian đúng 92 % lỗi bị cờ, theo LiDAR 48 %; áp dụng gợi ý lên cờ báo động
giả sẽ làm hỏng cuboid đúng ~2/3 số lần → luôn **Xem trước**, hoặc bấm ✗.

**Mức chắc chắn của cờ** (`backend/labeler/qc.py`). Ba nguồn là bằng chứng độc lập, nên tab Kiểm tra chia cờ thành hai
nhóm, nhóm chắc chắn đứng trước (N / P cũng đi theo thứ tự này):

| nhóm | quy tắc | cờ trên dữ liệu có lỗi trúng lỗi thật | báo động giả trên GT sạch | lỗi bắt được |
|---|---|---|---|---|
| **Chắc chắn** | cuboid bị ≥ 2 nguồn cùng gắn cờ | 98 % | 0,14 / frame | 64 % |
| **Cần xem** | chỉ 1 nguồn | 45 % | 5,35 / frame | thêm 35 % (tổng 99 %) |

(val, cùng lần đo ở trên; nối chỉ bằng vị trí: 95 % / 0,21 / 48 %.) Với cờ **cần xem**, nút **Áp dụng** của gợi ý dời /
co giãn / tạo cuboid bị khoá cho tới khi bấm **Xem trước**; xoá cuboid thì phải xác nhận. Cờ chắc chắn áp dụng được ngay.

Giới hạn, nói thẳng khi trình bày: (1) recall thời gian ở trên dùng `instance_token` của GT; nối cuboid chỉ bằng vị trí
(như khi tự vẽ, `--no-instance`) thì thời gian còn 71 % (dời chỗ 71 %, đổi class 23 % vì xe ↔ người không nối được), báo
động giả 0,85 / frame, LiDAR + thời gian vẫn 92 %. (2) Lỗi cài là lỗi tổng hợp; LiDAR chỉ bắt được vật có điểm (54 %
cuboid). (3) Chưa làm: cộng dồn nhiều sweep (vật đứng yên), so với PointPillars làm "ý kiến thứ hai". Giới hạn (1)
được khắc phục khi người gán dùng **Ctrl+B** (mục dưới): cuboid chép mang theo mã vật.

## Chép cuboid sang frame sau và mã vật

**Ctrl+B** (hoặc nút ⧉ ở thanh công cụ trái) chép mọi cuboid của keyframe liền trước trong scene vào frame đang mở;
**Ctrl+Shift+B** chép từ frame sau (`backend/labeler/propagate.py`, `POST /api/frames/{i}/propagate`):

- bù chính xác chuyển động của xe ego (LiDAR frame trước → global → LiDAR frame này);
- vật có ở cả hai frame trước đó được đẩy tới theo vận tốc và tốc độ quay của nó;
- giữ **mã vật** (`instance`), bỏ qua vật đã có trong frame (cùng mã hoặc cùng chỗ). Cuboid chép có biểu tượng ⧉ tím.

Frame nguồn là nhãn đã lưu, chưa lưu thì GT; ở chế độ pilot chép chỉ được từ nháp của chính người đó (không có GT).
Mọi cuboid giờ có mã vật: GT giữ `instance_token` của nuScenes, cuboid vẽ / gợi ý / chép trong app nhận `obj_…`.
Inspector có ô **Mã vật** để sửa tay (ví dụ gộp hai mã khi một vật bị vẽ hai lần ở hai frame). Nhờ mã vật, kiểm tra theo
thời gian nối đúng vật cả khi gán từ đầu – không phải đoán bằng vị trí (71 % → mức của `instance_token`, 98 %).

Đo bằng `python -m labeler.eval_propagate --split val` – giả lập người gán làm xong mỗi frame (= GT) rồi chép sang frame
sau, chấm từng cuboid chép theo luật pilot (tâm 0,7 m, cạnh 25 %, hướng 20°):

| cách chép (val, 2 scene, 79 lần chép, 4361 cuboid) | đúng ngay | lệch nhẹ (≤ 2 m) | lệch xa |
|---|---|---|---|
| chép nguyên toạ độ | 3 % | 20 % | 78 % |
| + bù chuyển động xe ego | 89 % | 8 % | 3 % |
| **+ vận tốc của vật (app)** | **99 %** | 1 % | 0 % |
| + kéo theo điểm LiDAR (không dùng) | 91 % | 9 % | 0 % |

Vật đứng yên đúng 100 %, vật đang chạy 94 %. Mỗi lần chép người gán còn phải vẽ 3 % vật mới xuất hiện và xoá 3 % cuboid
của vật đã đi khỏi. Bước "kéo theo điểm LiDAR" bị tắt vì trên train nó làm kết quả kém đi ở mọi ngưỡng thử (97 % →
91–96 %): cuboid ôm cả vật còn điểm LiDAR chỉ nằm ở mặt hướng về cảm biến. Chép nối tiếp nhiều frame mà không sửa thì sai
dồn (còn 53 % đúng sau 5 frame, `--chain 5`) – công cụ để chép rồi kiểm từng frame, không phải để chép mù. Lưu ý: frame
nguồn ở đây là GT (rất mượt); với nhãn người gán, tỉ lệ đúng sẽ thấp hơn – đo được khi chạy pilot.

## Xuất

- `Xuất nuScenes` (`GET /api/export?fmt=nuscenes`): mọi frame đã lưu theo định dạng nuScenes detection results (hệ
  global, tâm hình học, wlh, quaternion chỉ yaw, score 1) – xuất GT ra khớp `sample_annotation` tới 1e-13 m.
- `Xuất JSON` (`fmt=raw`): `{sample: cuboid}` trong hệ LiDAR, đúng định dạng của app.
- CVAT: `pip install -r requirements-cvat.txt`, đặt `CVAT_URL` + `CVAT_ACCESS_TOKEN` (hoặc `.cvat.env`), rồi
  `cd backend && python -m labeler.export_cvat --name "..."` → tạo task point cloud mới (kèm 6 ảnh) và đẩy cuboid lên.

## API

| | |
|---|---|
| `GET /api/frames` | danh sách frame (val trước, rồi train – "val 25" giống repo M44) |
| `GET /api/frames/{i}?init=gt\|empty` | calib 6 camera, cuboid hiện tại (đã lưu, nếu chưa thì GT hoặc rỗng), YOLO, kết quả check |
| `GET /api/frames/{i}/points` | LiDAR float32 x, y, z, intensity |
| `GET /api/frames/{i}/image/{cam}` | ảnh camera |
| `POST /api/frames/{i}/check` | kiểm tra cuboid chưa lưu (gọi trong lúc kéo): cờ camera + LiDAR + thời gian, `qc`, `coverage` |
| `PUT /api/frames/{i}/boxes` | lưu cuboid |
| `POST /api/frames/{i}/propose` | gợi ý cuboid cho một box 2D `{cam, bbox, cls}` |
| `POST /api/frames/{i}/propose_missing` | gợi ý cho mọi `MISSING_3D` của các cuboid gửi lên |
| `POST /api/frames/{i}/events` | log phản hồi của reviewer (`flag_accept` / `flag_false_alarm` / `flag_clear`) |
| `GET /api/feedback/summary` | số cờ đúng / báo động giả theo loại cờ (để chỉnh lại ngưỡng) |
| `GET /api/export?fmt=raw\|nuscenes` | tải mọi frame đã lưu |

## Lộ trình

- [x] **P1 – xem:** BEV + 6 camera + cờ M44, chọn cuboid đồng bộ giữa BEV và ảnh, N/P đi qua cờ.
- [x] **P2 – sửa:** kéo / xoay / co giãn cuboid trên BEV + 2 view ngang, thêm / xoá / đổi class, chiếu lên camera ngay
  trong trình duyệt (khớp Python tới 1e-13 px), check lại sau 150 ms, hoàn tác, lưu (Ctrl+S), reset GT / xoá hết.
- [x] **P3 – gợi ý:** cuboid từ box YOLO (bấm ô cam, Shift+bấm box YOLO, G / Shift+G cho mọi ô cam), phản hồi cờ
  (1 đúng / 2 báo động giả, lưu lại, `GET /api/feedback/summary`), xuất nuScenes / JSON thô / CVAT.
- [x] **P4 – đo (công cụ):** chấm điểm giống pilot M44 (`labeler/score.py`), mốc "chỉ Shift+G" trên cả val
  (`labeler/eval_assist.py`), chế độ pilot trong app (`?pilot=<tên>&frame=60[&assist=0]`: frame cố định bắt đầu rỗng,
  không lộ GT, đồng hồ, tự lưu nháp, nút Nộp bài chấm ngay), báo cáo so với CVAT (`labeler/pilot_report.py`).
  Quy trình cho team: [docs/PILOT_APP.md](docs/PILOT_APP.md).
- [ ] **P4 – đo (người):** 4 người chạy pilot theo docs/PILOT_APP.md, rồi `pilot_report`.
- [x] **P5 – kiểm tra cuboid camera không thấy:** LiDAR (bắn tia, kích thước, mặt đất, chồng nhau, điểm tràn, hướng) +
  thời gian (kích thước / vị trí / hướng / class theo chuỗi), gợi ý sửa, mức tin cậy QC, độ phủ; chỉnh trên train,
  đo trên val (`labeler/calib_lidar.py`, `labeler/eval_lidar.py`).
- [x] **P6 – chép cuboid sang frame sau:** bù ego motion + vận tốc vật, giữ mã vật (Ctrl+B), ô mã vật trong inspector;
  đo bằng `labeler/eval_propagate.py` (val: 99 % cuboid chép đúng ngay).
- [ ] **P5 tiếp:** cộng dồn 3–5 sweep cho vật đứng yên; PointPillars làm ý kiến thứ hai; chỉnh lại ngưỡng từ phản hồi
  ✓ / ✗ của người gán (`GET /api/feedback/summary`).
