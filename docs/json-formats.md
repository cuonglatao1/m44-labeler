# Định dạng file giữa các module

Các module chỉ trao đổi qua những file này. Muốn đổi định dạng phải báo cả nhóm và sửa file này trước.

`gt_boxes.json` / `noisy_boxes.json` – cuboid theo frame (hệ toạ độ LiDAR, tâm đáy, mét, radian)
```json
[{"sample": "ca9a282c…", "boxes": [
  {"box_id": "ca9a282c_002", "cls": "car", "center": [x, y, z_bottom], "size": [l, w, h], "yaw": 3.09,
   "num_lidar_pts": 5, "visibility": 4}
]}]
```
`visibility` (nuScenes, 1 = 0–40% … 4 = 80–100%) và cờ `night` của frame chỉ có khi thư mục dữ liệu chứa bảng
`v1.0-mini/`; frame demo không có → `null`.

`proj_2d.json` – cuboid sau khi chiếu lên từng camera (pixel, ảnh 1600×900)
```json
{"sample": "…", "cam": "CAM_FRONT", "box_id": "ca9a282c_002", "cls": "car",
 "bbox": [x1, y1, x2, y2], "depth": 63.8, "visible_frac": 0.92, "corners_2d": [[u, v], …, null]}
```

`det_2d.json` – YOLO (chỉ class có tương ứng nuScenes: person, bicycle, car, motorcycle, bus, truck)
```json
{"sample": "…", "cam": "CAM_FRONT", "cls": "car", "bbox": [x1, y1, x2, y2], "score": 0.87}
```

`flags.json` – cảnh báo của tool
```json
{"flag_id": "F0006", "sample": "…", "cam": "CAM_FRONT", "type": "LOW_IOU|SIZE_MISMATCH|CLASS_MISMATCH|NO_2D_MATCH|MISSING_3D",
 "box_id": "ca9a282c_013", "cls_3d": "car", "cls_2d": "car", "iou": 0.41, "p_bbox": […], "det_bbox": […]}
```
`MISSING_3D` có `box_id: null` và thêm `score`.

Trong app, mỗi cờ có thêm `source`: `camera` (các loại trên), `lidar` (`LIDAR_EMPTY|LIDAR_FREE|LIDAR_SPILL|
LIDAR_HEADING|SIZE_IMPLAUSIBLE|FLOATING|SUNKEN|BEV_OVERLAP`, `labeler/lidar_qc.py`) hoặc `track` (`TRACK_SIZE|
TRACK_JUMP|TRACK_YAW|TRACK_CLASS`, `labeler/track.py`). Vật bị quên gán (`labeler/missing.py`): `TRACK_MISSING`
(track) và `LIDAR_UNBOXED` (lidar) có `box_id: null`, `group` (`miss:<mã vật>`, chung cho mọi nguồn thấy cùng vật) và
`detail.box` = cuboid dự đoán. Cờ `lidar` / `track` có `cam` = camera thấy cuboid lớn nhất
(hoặc `null`), `detail` (số liệu, giá trị sửa) và `msg` (giải thích tiếng Việt); `BEV_OVERLAP` thêm `other_id`.
Kết quả check của app còn có `qc[box_id]` = `{camera, lidar, track: ok|flagged|none, level: high|medium|flagged|none,
rays: {rays, hit, pass, occ, none}, n_inside, n_spill, ground_gap, n_obs, pass_xy}` và `coverage` = tỉ lệ cuboid mỗi
nguồn kiểm được (`camera`, `lidar`, `track`, `any`).

`injected_errors.json` – đáp án lỗi đã cài
```json
{"sample": "…", "box_id": "ca9a282c_013", "type": "OFFSET|SCALE|ROTATE|CLASS_SWAP|DELETE", "detail": "size x1.6", "caught": true}
```
