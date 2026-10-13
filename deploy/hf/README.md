# Bản demo trên Hugging Face Spaces

> Hiện tại (13/10/2026) Space Docker trên CPU miễn phí cần gói PRO; bản miễn phí dùng Render: [../render/README.md](../render/README.md).

Bản demo công khai: 2 scene val của nuScenes-mini (81 keyframe), mỗi người xem có nhãn riêng (`M44_DEMO=1`), trợ lý
Claude tắt. Dữ liệu nuScenes theo CC BY-NC-SA 4.0 (phi thương mại, ghi nguồn, không ngụ ý Motional bảo trợ) – ghi chú
nằm ở thanh trạng thái của app và ở `SPACE_README.md`.

```bash
.venv\Scripts\python.exe deploy/hf/make_demo_data.py --nusc-root D:/data/nuscenes --out D:/m44-demo-data   # ~160 MB
.venv\Scripts\python.exe deploy/hf/stage_space.py --data D:/m44-demo-data --out D:/m44-space
.venv\Scripts\hf.exe auth login                                    # token "write" tạo ở huggingface.co/settings/tokens
.venv\Scripts\hf.exe repos create <user>/m44-labeler --repo-type space --space-sdk docker --public
.venv\Scripts\hf.exe upload <user>/m44-labeler D:/m44-space . --repo-type space
```

Space tự build `Dockerfile` (frontend bằng Node 20, backend Python 3.11) và chạy ở cổng 7860. Chạy thử chế độ demo
không cần Docker:

```bash
cd backend
set M44_DEMO=1& set M44_SPLITS=val& set NUSC_ROOT=D:/m44-demo-data/nuscenes& set M44_DETS=D:/m44-demo-data/dets
..\.venv\Scripts\python.exe -m uvicorn labeler.main:app --port 8772
```

Biến môi trường: `M44_DEMO` (tách nhãn theo header `X-M44-Session` / `?session=`), `M44_SPLITS` (`val,train`),
`M44_DETS` (thư mục kết quả YOLO), `M44_DB` (file SQLite).
