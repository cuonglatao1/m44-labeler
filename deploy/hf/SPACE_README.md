---
title: M44 Labeler
emoji: 🚗
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
license: cc-by-nc-sa-4.0
short_description: 3D cuboid labelling with live camera + LiDAR + temporal QC
---

# M44 Labeler – bản demo

Công cụ gán nhãn cuboid 3D cho dữ liệu lái xe tự động, kiểm tra chất lượng ngay trong lúc gán bằng ba nguồn: ảnh camera,
point cloud LiDAR và chính vật đó ở các frame trước / sau.

- Mã nguồn: <https://github.com/cuonglatao1/m44-labeler>
- Repo đội (AI20K Build Phase, P-054): <https://github.com/AI20K-Build-Phase-Cohort-4A/P-054>

**Bản demo:** 2 scene val của nuScenes-mini (81 keyframe). Nhãn bạn lưu chỉ trình duyệt của bạn thấy và có thể bị xoá khi
Space khởi động lại. Trợ lý Claude tắt trong bản demo.

**Thử nhanh:** chọn một xe → `W A S D` dời đi vài mét → cờ đỏ xuất hiện; bấm cờ để xem gợi ý sửa; `→` sang frame sau,
`Ctrl+B` chép cuboid từ frame trước; `?` xem phím tắt.

## Dữ liệu

nuScenes-mini © Motional, dùng theo [điều khoản nuScenes](https://www.nuscenes.org/terms-of-use)
(CC BY-NC-SA 4.0, phi thương mại). Bản demo không phải sản phẩm của Motional và không được Motional bảo trợ.
Phát hiện 2D: Ultralytics YOLO (`yolo11m`), tính sẵn.
