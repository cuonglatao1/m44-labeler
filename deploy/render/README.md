# Bản demo trên Render (gói miễn phí)

Bản demo công khai giống bản Hugging Face ([../hf/README.md](../hf/README.md)): 2 scene val của nuScenes-mini, mỗi người
xem có nhãn riêng, trợ lý Claude tắt. Đo trên Linux: ~340 MB RAM (gói free 512 MB), khởi động ~4 s; gói free ngủ sau
15 phút không ai vào, lần mở sau chờ ~1 phút.

Dữ liệu demo nằm ở dataset Hugging Face `cuonglatao/m44-demo-data` (CC BY-NC-SA 4.0 như nuScenes), Docker tải về lúc
build:

```bash
.venv\Scripts\python.exe deploy/hf/make_demo_data.py --nusc-root D:/data/nuscenes --out D:/m44-demo-data
cd /d D:\m44-demo-data && tar -cf D:\m44-demo-upload\m44-demo-data.tar dets nuscenes
.venv\Scripts\hf.exe repos create cuonglatao/m44-demo-data --repo-type dataset --public --exist-ok
.venv\Scripts\hf.exe upload cuonglatao/m44-demo-data D:\m44-demo-upload . --repo-type dataset
```

Dữ liệu được gói thành một file `m44-demo-data.tar` (~160 MB) vì upload 666 file nhỏ qua mạng chậm dễ hỏng giữa chừng;
`D:\m44-demo-upload` chứa file tar và `README.md` (thẻ dataset, ghi nguồn nuScenes).

Triển khai: dashboard.render.com → **New → Blueprint** → chọn repo `cuonglatao1/m44-labeler` → Render đọc
[`render.yaml`](../../render.yaml) (web service Docker, gói free, `deploy/render/Dockerfile`) → **Apply**. Lần build đầu
~10 phút. Health check: `GET /api/config`.
