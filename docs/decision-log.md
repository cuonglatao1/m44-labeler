# Decision log

Mỗi quyết định kỹ thuật: bối cảnh → quyết định → lý do → hệ quả. Mới nhất ở trên cùng.

## D-017 · Cuboid camera không kiểm được: thêm kiểm tra bằng LiDAR và theo thời gian (không tách thành đề N2-04C)
- **Bối cảnh:** ở val 65 % cuboid không qua được `_checkable` của M44 (bị che, xa, class YOLO không nhận); phần lớn là
  vật bị che 45–70 %. Mentor đồng ý mở rộng sang point cloud miễn có cách giải quyết riêng.
- **Quyết định:** trình bày là *chuỗi kiểm tra bổ sung* (camera → LiDAR → thời gian), chỉ số chính là độ phủ và recall
  trên nhóm camera không kiểm được, so sánh camera / LiDAR / thời gian / kết hợp – không phải "QC bằng LiDAR" độc lập.
  LiDAR dùng ray casting trên range image có tổ chức của nuScenes (biết cả phát không về) để tách "bị che" khỏi
  "rỗng"; thời gian dùng instance token (GT) hoặc nối theo vị trí sau bù ego-motion.
- **Lý do:** đếm điểm trong cuboid không phân biệt được vật bị che với cuboid sai; ray casting thì có. Thời gian là bằng
  chứng mạnh nhất cho vật bị che vì mượn được frame vật hiện rõ.
- **Ngưỡng:** chỉnh trên train với ngân sách báo động giả 0,5 % / kiểm tra; kích thước chọn bỏ-một-scene vì mini lặp vật.
- **Kết quả (val):** recall trên cuboid camera không kiểm được 4 % → 99 % (LiDAR 52 %, thời gian 98 %); độ phủ 35 % →
  100 %; báo động giả LiDAR 2,93 / frame, thời gian 0,07 / frame. Không có instance token: thời gian 71 %, kết hợp 92 %.
- **Hệ quả:** loader thêm `scene`, `timestamp`, `instance` (phải chép sang repo M44 nếu dùng ở đó). `LIDAR_EMPTY` có báo
  động giả trên xe tối màu / kính (tia xuyên qua) – đã chặn bằng điểm thân xe, còn lại để người gán bấm ✗ và chỉnh
  lại ngưỡng từ phản hồi.

## D-016 · Pilot phần 2: gán nhãn từ đầu, chấm trước / sau khi sửa theo M44 Check
- **Bối cảnh:** phần 1 chỉ đo review nhãn có lỗi giả; quy trình thật là annotator tự gán rồi bấm M44 Check, với lỗi
  thật của người gán.
- **Quyết định:** task trống 1 frame (val 25, Boston: 10 ô tô + 7 người đi bộ ≥ 60 % nhìn thấy trong 30 m), gán tối đa
  25 phút, chấm `truoc`, bấm M44 Check, sửa tối đa 10 phút, chấm `sau`. `pilot_label_score.py` xếp mỗi cuboid
  car/pedestrian thành đúng (dung sai như phần 1) / lệch (đúng class, cách ≤ 2 m) / sai-thừa, và mỗi vật cần gán
  thành đúng / lệch / bỏ sót; lần `sau` đối chiếu cờ của tool với ảnh chụp `truoc` → độ chính xác và độ phủ của tool
  trên nhãn người thật.
- **Kiểm chứng (task 64):** chưa gán: 0/17, 17 bỏ sót; gán giả lập có 3 lệch, 1 sai class, 2 bỏ sót, 1 cuboid ma →
  chấm đúng 11 đúng / 3 lệch / 3 bỏ sót / 2 sai-thừa; M44 Check gắn cờ 4, trong đó 3 thực sự chưa đúng, bắt 3/5.

## D-015 · Thiết kế pilot: chéo 2×2, giới hạn 20 phút, chấm tự động bằng nhãn gốc
- **Người tham gia:** Thúy, Trọng, Duy, Tùng (tech lead không review).
- **Thiết kế:** 2 bộ 5 frame có lỗi cài (A: val 10–14 Boston, 25 lỗi; B: val 60–64 Singapore, 18 lỗi; seed 0) –
  chưa dùng trong task 52/53. Mỗi người làm mỗi bộ một lần, một lượt tay một lượt tool, thứ tự đảo chéo để trung
  hoà khác biệt tay nghề và độ khó dữ liệu. Mỗi lượt tối đa 20 phút → chỉ số chính: lỗi sửa được / phút.
- **Chấm:** `pilot_score.py` so cuboid sau review với nhãn gốc (khớp 1–1, tâm ≤ 0,7 m, cạnh ±25 %, hướng ±20°,
  bỏ qua lật 180°): lỗi cài → đã sửa / chưa; cuboid vốn đúng → còn đúng / bị làm hỏng. Mỗi máy tự tạo task
  bằng `pilot_setup.bat`; dữ liệu giống nhau kiểm bằng số lỗi cài (25 / 18).
- **Kiểm chứng bộ chấm:** task 56/57 trên CVAT local – không sửa gì: 0/25, 0/18, làm hỏng 0; đưa nhãn về nhãn gốc:
  25/25, 18/18, làm hỏng 0.

## D-014 · Mỗi người dùng CVAT local của mình
- **Bối cảnh:** nhóm chốt mỗi người chạy CVAT local; tool phải chịu được CVAT khác phiên bản, label đặt tên khác,
  task thiếu thuộc tính `qc`/`visibility`, và báo rõ khi task không tạo từ tool.
- **Quyết định:** tên label ánh xạ không phân biệt hoa thường + bảng alias (`Person`→pedestrian, `motorbike`→
  motorcycle…), label lạ bị bỏ qua; thiếu `qc` thì chỉ ghi Score; tên frame không khớp `<4 số>_<token>` thì dừng
  với thông báo tiếng Việt. SDK mặc định chỉ cảnh báo khi lệch phiên bản server. Thêm `create_task.bat`.
- **Kiểm chứng:** task 54 (label `Car/Person/Bicycle/Truck`, không có thuộc tính): đọc 170 cuboid, 5 bị gắn cờ =
  5 cuboid Score 0 trên CVAT. Task 55 (frame `scan0000/…`): dừng đúng với thông báo giải thích.

## D-013 · Nút "M44 Check" = bookmarklet + dịch vụ cục bộ, không sửa CVAT
- **Bối cảnh:** người dùng muốn "label xong bấm một nút là tool kiểm tra và hiện danh sách lỗi".
- **Phương án loại:** thêm nút vào giao diện CVAT (React) – phải build lại image `cvat_ui` (ổ C còn ~12 GB), chỉ
  chạy trên CVAT tự host, không dùng được với CVAT chung của nhóm/BTC, phải sửa lại khi nâng cấp CVAT.
  Webhook khi job "completed" – CVAT đẩy webhook qua proxy smokescreen chặn địa chỉ nội bộ, phải cấu hình
  `SMOKESCREEN_OPTS`; và không mở được danh sách lỗi cho người bấm.
- **Quyết định:** `scripts/m44_server.py` (chỉ thư viện chuẩn) chạy ở `localhost:8765`; bookmarklet đọc ID
  task/job từ URL CVAT và mở `/check?task=…`; trang tiến trình hỏi `/status` mỗi 2 giây rồi chuyển sang
  `/report/<task>/`. Mỗi lúc chỉ một lần kiểm tra (YOLO dùng chung GPU/CPU).
- **Kiểm chứng:** `/check?job=58` → nhận ra task 52 → kiểm tra → tự mở báo cáo (~10 giây khi YOLO đã cache), ảnh
  hiển thị qua HTTP; mã bookmarklet chạy trên trang `/tasks/52/jobs/58` tạo đúng `…/check?task=52`.

## D-012 · Tích hợp CVAT 3D qua thuộc tính `qc` trên cuboid
- **Bối cảnh:** CVAT 3D (v2.75) không hiển thị Issue: tab Issues chỉ có cho 2D
  (`objects-side-bar.tsx`, điều kiện `is2D`) và task 3D chỉ có workspace `STANDARD3D`, không có Review.
- **Quyết định:**
  - Task tạo bằng SDK theo layout "Custom 2" của CVAT: `<index>_<sample token>/<…>.pcd` + 6 ảnh camera làm
    related images. Tự ghi `.pcd` (x y z intensity) vì bộ đổi `.bin` của CVAT giả định 4 số/điểm (KITTI), còn
    nuScenes 5 số/điểm. Tên frame chứa sample token → tìm lại calibration và ảnh trong nuScenes.
  - Cuboid CVAT = [tâm khối x y z, rx ry rz, sx sy sz] trong hệ point cloud = hệ LiDAR → yaw = rz, kích thước = (dài,
    rộng, cao). Mỗi label có thuộc tính `visibility` (để tool lọc vật bị che như với nuScenes) và `qc`.
  - Kết quả ghi vào `qc`; `MISSING_3D` không có cuboid để gắn nên chỉ nằm trong báo cáo HTML, có link mở frame.
- **Kiểm chứng:** task 3 frame: đọc ngược 86/86 cuboid khớp tuyệt đối, mỗi frame đủ 6 ảnh. Task 52 (10 frame,
  41 lỗi cài, 386 cuboid): `cvat_check.py` bắt 25/41 (61%), ghi `qc` cho 386 cuboid (49 bị gắn cờ) và đọc lại đúng
  trên CVAT.
- **Kiểm tra trên giao diện CVAT 3D (task 52, frame 1):** nhìn từ trên, cuboid ô tô nằm trên làn đường và song
  song mép đường, cuboid người ở vỉa hè/góc giao lộ; chọn một người thì hình chiếu Side/Front cho hộp cao, hẹp
  ôm đúng đám điểm. Bảng chi tiết hiện kích thước (vd ô tô 4,96 × 2,04 × 1,64 m), `visibility`, `qc`.
- **Sửa sau khi thử lọc (D-012b):** luật `Attributes → car → qc != OK` vẫn hiện mọi người đi bộ – bộ lọc CVAT
  (json-logic trên `attr.<label>.<thuộc tính>`) coi thuộc tính không tồn tại là "khác OK". Tool ghi thêm
  **Score** = 0 (bị gắn cờ) / 1 (OK); Score chung cho mọi label nên reviewer chỉ cần một luật `Score < 1`.
  Task 52: 49 cuboid Score 0 đúng bằng 49 cuboid bị gắn cờ.

## D-011 · Chế độ "chỉ kiểm tra" (`scripts/check.py`) và ngưỡng ghép cặp khác class
- **Bối cảnh:** `run_all.py` luôn cài lỗi giả nên chưa kiểm được nhãn thật. Chạy `check.py` trên nhãn gốc nuScenes
  (val, 81 frame) ra 205 cảnh báo; xem 11 cảnh báo `CLASS_MISMATCH` thì gần như tất cả là **người đứng trước xe
  đỗ**: YOLO không thấy người, cuboid người bị ghép với box "car" của xe phía sau dù chỉ chồng lên một phần nhỏ.
- **Quyết định:** cặp khác nhóm class chỉ được ghép khi IoU ≥ `mismatch_min_iou` = 0,3 (lỗi sai class thật thì
  cuboid vẫn nằm khớp vật thể). Chọn 0,3 trên train: báo nhầm CLASS_MISMATCH 33 → 18, recall CLASS_SWAP giữ 98%;
  0,5 bắt đầu mất lỗi thật (93%).
- **Kết quả val:** báo động giả 2,53 → 2,48/frame (CLASS_MISMATCH 11 → 5); recall 62,9% → 63,1%.
- **Bài học:** chạy chế độ kiểm tra trên nhãn thật và **nhìn ảnh** tìm ra kiểu báo nhầm mà số liệu tổng không
  cho thấy – nên lặp lại việc này với nhãn của nhóm ở pilot.

## D-010 · Đọc nuScenes trực tiếp bằng nuscenes-devkit, bỏ phụ thuộc mmdet3d / WSL khi chạy tool
- **Bối cảnh:** môi trường cũ (WSL + PyTorch CUDA + mmcv + mmdet3d, ~9 GB, nhiều lỗi phiên bản) chỉ cần mmdet3d để
  sinh file info `.pkl`. Thành viên không có nền tảng kỹ thuật không thể tự cài.
- **Quyết định:** `loader.load_frames_nusc` đọc thẳng bảng nuScenes; `requirements.txt` chỉ còn numpy, scipy,
  pillow, nuscenes-devkit, ultralytics; thêm `setup_windows.bat`, `run_demo.bat` chạy Python Windows, CPU được.
  `run_all.py` dùng `configs/tuned.json` làm mặc định để không ai quên.
- **Kiểm chứng:** `tests/test_loader_nusc.py` – 81 frame / 4.441 cuboid val khớp loader cũ tuyệt đối (lidar2cam
  lệch 5·10⁻⁸ do pkl lưu float32). Cài từ bản sao sạch của repo trên Windows: chạy được, kết quả demo giống hệt bản
  GPU trong WSL (482 detection, 42/59 lỗi, 90 cảnh báo); 10 frame mất ~2 phút trên CPU.

## D-009 · Chọn cấu hình `configs/tuned.json`, kiểm chứng trên tập val
- **Quy trình:** chỉnh mọi ngưỡng trên nuScenes-mini **train** (323 frame, 8 cảnh); đo cuối trên **val** (81 frame,
  2 cảnh) chưa dùng khi chỉnh. Recall = trung bình 10 lần cài lỗi ngẫu nhiên (30% cuboid kiểm tra được).
- **Kết quả val:** báo động giả 11,01 → **2,53 cảnh báo/frame** (÷4,4); recall 70,1% → **62,9%**.
  Theo loại: CLASS_SWAP 95%, SCALE 90%, OFFSET 48%, DELETE 45%, ROTATE 30%.
- **Lựa chọn trên train (sweep, `configs/sweep*.json`):**

  | Cấu hình | Báo động giả/frame | Recall |
  |---|---|---|
  | A mặc định | 7,12 | 71,5% |
  | E lọc visibility ≥ 3, kích thước ≥ 60 px, bỏ đêm, IoU theo class p2 | 0,66 | 37,1% |
  | G2 = E + IoU p5 + `SIZE_MISMATCH` (p2–p98) → **chọn** | 1,30 | 58,9% |
- **Giới hạn:** val chỉ có 2 cảnh → con số còn dao động; cần đo lại trên batch pilot thật ở tuần 6.

## D-008 · Thêm cảnh báo `SIZE_MISMATCH` (so chiều cao / chiều rộng) và lọc theo dữ liệu nuScenes
- **Bối cảnh:** trên train, GT sạch sinh 7,1 báo động giả/frame. Phân tích (`scripts/calibrate.py`):
  54% là `NO_2D_MATCH` do YOLO không thấy (ban đêm, mờ, vật bị cây/biển hiệu che, người xa);
  `LOW_IOU` với ngưỡng 0,5 báo nhầm 31–48% người / xe máy / xe đạp đúng nhãn.
  Siết IoU theo class giảm báo nhầm nhưng làm recall SCALE 85% → 28%, ROTATE 44% → 6%: IoU quá thô.
- **Quyết định:**
  1. Loader gắn `visibility` (1–4) và cờ `night` từ bảng nuScenes; kiểm tra tính khớp: 18.538 nhãn, lệch 0.
  2. Chỉ kiểm tra cuboid visibility ≥ 3; `NO_2D_MATCH`/`MISSING_3D` (chỉ dựa vào việc YOLO thấy hay không) cần
     vật thể ≥ 60 px, `MISSING_3D` cần độ tin ≥ 0,7, và tắt ở cảnh đêm.
  3. `SIZE_MISMATCH`: log(cao chiếu / cao YOLO) và log(rộng chiếu / rộng YOLO) nằm ngoài khoảng p2–p98 của GT sạch
     theo từng class. Cuboid phóng to ×1,6 hay xe xoay 90° làm tỉ lệ này lệch rõ, trong khi IoU vẫn "chấp nhận được".
- **Hệ quả:** ngưỡng sinh tự động bằng `calibrate.py --write`; muốn dùng YOLO khác hay dữ liệu khác thì chạy lại.

## D-007 · `MISSING_3D`: chỉ cuboid cùng nhóm class mới "giải thích" được một detection
- **Bối cảnh:** lỗi xoá cuboid chỉ bắt được 50,6% (100 lần cài lỗi ngẫu nhiên trên frame demo). Debug thấy detection
  "car" bị coi là đã có cuboid vì chạm 0,11 IoU với cuboid **cọc tiêu**, hoặc 0,15 với **người đi bộ ở xa phía sau**.
- **Quyết định:** detection không ghép cặp chỉ được bỏ qua khi (a) trùng ≥ 0,1 IoU với cuboid *không kiểm tra được*
  có class tương thích, hoặc (b) trùng ≥ 0,5 với bất kỳ cuboid nào (detection trùng lặp, vd car + truck).
- **Kết quả:** recall DELETE 50,6% → 79,0%; báo động giả trên GT sạch giữ nguyên (7); tổng recall 76,0% → 81,8%.
- **Còn lại (giới hạn đã biết):** (1) nhóm người đứng sát nhau mà YOLO chỉ thấy một phần – cuboid bên cạnh "nhận"
  detection của người bị xoá, nhìn từ 2D không còn mâu thuẫn; (2) vật thể xa YOLO kém tự tin (< `missing_conf` 0,5).

## D-006 · Chỉ cài lỗi vào cuboid tool "nhìn thấy được" khi đúng
- **Quyết định:** cuboid đủ điều kiện cài lỗi = khớp được với một detection YOLO và không bị cảnh báo trên GT sạch.
- **Lý do:** tách hai câu hỏi: (1) tool có phát hiện lỗi khi nhìn thấy vật thể không (recall), (2) tool báo động giả
  bao nhiêu (đo riêng trên GT sạch). Nếu cài lỗi vào vật thể bị che hoàn toàn thì recall đo cả khả năng của YOLO.
- **Hệ quả:** recall là "recall trên vùng kiểm tra được". Báo cáo phải nêu kèm tỉ lệ cuboid kiểm tra được.

## D-005 · Bỏ qua vật thể quá xa / quá nhỏ / bị che
- **Quyết định:** chỉ kiểm tra cuboid có depth ≤ 50 m, chiều cao chiếu ≥ 25 px, ≥ 50% nằm trong ảnh, bị cuboid gần
  hơn che ≤ 50%.
- **Lý do:** nuScenes có nhiều người đi bộ ở xa chỉ 1–5 điểm LiDAR, trên ảnh vài pixel – YOLO không thấy, sẽ thành
  báo động giả.
- **Hệ quả:** ngưỡng chỉnh ở `match.DEFAULT_CFG`, tinh chỉnh tuần 5 dựa trên kết quả chấm.

## D-004 · Ánh xạ class nuScenes ↔ COCO theo nhóm tương thích
- **Quyết định:** dùng YOLO pretrained COCO, một class nuScenes chấp nhận nhiều class COCO (car ↔ car/truck, …).
  `barrier`, `traffic_cone` không có trong COCO → không kiểm tra class/vị trí được, chỉ dùng để tránh báo
  `MISSING_3D` nhầm.
- **Lý do:** YOLO hay gọi SUV/bán tải là "truck"; bắt khớp tuyệt đối sẽ ra nhiều `CLASS_MISMATCH` giả.
- **Hệ quả:** lỗi đổi class giữa hai class cùng nhóm (car ↔ truck) không bắt được – nêu trong giới hạn.

## D-003 · Chấp nhận sai lệch ~1 px so với box 2D tham chiếu của mmdet3d
- **Bối cảnh:** so với box 2D mmdet3d tính sẵn: IoU trung vị 0,949, lệch ~1 px.
- **Sửa lại (khi làm D-010):** ban đầu ghi lý do là `lidar2cam` trong info không bù chuyển động của xe – **sai**.
  Đọc code mmdet3d (`obtain_sensor2top`) thấy `lidar2cam` đã đi qua ego-pose ở cả thời điểm LiDAR và camera, tức
  là đã bù. Nguyên nhân chính xác của ~1 px chưa xác định (có thể do cách mmdet3d lấy bao lồi rồi cắt theo ảnh).
- **Hệ quả:** không ảnh hưởng ngưỡng; loader D-010 tính cùng chuỗi biến đổi nên có bù chuyển động.

## D-002 · `bbox_3d` trong info pkl là tâm khối, không phải tâm đáy
- **Bối cảnh:** lần chiếu đầu IoU luôn ≈ 0,333 – đúng bằng IoU khi box bị dịch lên nửa chiều cao.
- **Quyết định:** loader đổi về tâm đáy (`z - h/2`), quy ước box LiDAR của mmdet3d.
- **Hệ quả:** có test `tests/test_projection.py` để không tái phát.

## D-001 · Đọc dữ liệu qua file info .pkl của mmdet3d thay vì nuscenes-devkit trực tiếp
- **Lý do:** frame demo của mmdet3d và nuScenes-mini (sau `create_data.py`) cùng một định dạng → một code path,
  chạy được ngay khi chưa tải dataset.
