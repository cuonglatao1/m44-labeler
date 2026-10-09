# Pilot P4 – gán nhãn trên M44 Labeler so với CVAT + M44 Check

Câu hỏi: gán một frame từ đầu trên app (check 2D–3D chạy ngay khi gán + gợi ý cuboid từ ảnh) có **nhanh hơn và ít lỗi
hơn** quy trình CVAT → bấm M44 Check → sửa không? Và trong đó phần nào là nhờ trợ giúp (cờ + gợi ý), phần nào chỉ là
giao diện mới?

Chấm điểm giống hệt phần 2 pilot CVAT (`labeler/score.py` = `pilot_score.py` + `pilot_label_score.py` của repo M44):
mục tiêu là mọi `car` và `pedestrian` nhìn thấy ≥ 60 % trong 30 m; một cuboid **đúng** khi tâm lệch ≤ 0,7 m, mỗi
cạnh lệch ≤ 25 %, hướng lệch ≤ 20° (bỏ qua hướng với người); **lệch** = đúng class trong 2 m nhưng ngoài dung sai;
**sai / thừa** = không có vật cùng class gần đó.

## Thiết kế

| | Frame | Mục tiêu | Ai |
|---|---|---|---|
| **A** – CVAT + M44 Check (phần 2 của `PILOT.md` repo M44) | val 25 (scene-0103) | 17 (10 car, 7 người) | cả 4 người |
| **B1** – app **có** trợ giúp | val 60 (scene-0916) | 18 (11 car, 7 người) | Thúy, Trọng |
| **B2** – app **không** trợ giúp | val 60 | 18 | Duy, Tùng |

- Mini val chỉ có 2 scene; frame cạnh val 25 có gần như cùng các vật nên không dùng được cho lượt thứ hai. Val 60 là
  frame của scene kia có thành phần gần val 25 nhất. Hai frame khó tương đương theo mốc "máy" (chỉ Shift+G, không
  chỉnh): val 25 được 5 / 17 đúng, val 60 được 5 / 18.
- Val 60 đã xuất hiện trong pilot phần 1 (bộ B, review nhãn có sẵn). Ghi lại ai đã xem bộ B khi đọc kết quả.
- Làm A trước (đã nằm trong lịch pilot CVAT), B sau, cách nhau ít nhất một buổi nếu được.
- B1 – B2 so được "trợ giúp có tác dụng không" trên cùng frame. A – B1 so "cả quy trình" nhưng khác frame: đọc kèm mốc máy.

## Chuẩn bị (tech lead, một lần)

1. Máy chạy app: `run_app.bat` (cần `cache\dets` – xem README). Mỗi người dùng máy mình thì cài theo README.
2. Mở thử link của mình, bấm qua vài thao tác, **không nộp**.
3. Link cho từng người (thay tên, không dấu, không cách):
   - Thúy, Trọng: `http://localhost:8770/?pilot=Thuy&frame=60`
   - Duy, Tùng: `http://localhost:8770/?pilot=Duy&frame=60&assist=0`

   `frame` là số thứ tự trong danh sách của app (val trước, train sau), nên `frame=60` = val 60.

## Người làm (~30 phút)

1. 5 phút làm quen trên một frame khác (link không có `pilot=`): kéo, xoay, W A S D, Q / E, B để thêm, khung nhìn
   ngang. Có trợ giúp thì thử thêm: bấm ô cam, Shift+G, N / P.
2. Mở link pilot. Đồng hồ chạy từ lần mở đầu tiên (tải lại trang không reset).
3. **Gán tối đa 25 phút**: cuboid cho **tất cả `car` và `pedestrian` nhìn rõ trong 30 m**. App tự lưu nháp mỗi 3 giây.
   Có trợ giúp: nên bấm **Gợi ý mọi ô cam** trước, rồi sửa từng cuboid; đi qua cờ bằng N, xong khi không còn cờ đỏ
   / ô cam nào đáng tin.
4. Bấm **Nộp bài** → đồng hồ dừng, kết quả hiện ngay ở cột phải. Chụp màn hình gửi tech lead.

## Tổng hợp (tech lead)

```
cd backend
..\.venv\Scripts\python.exe -m labeler.pilot_report --cvat-dir D:\m44-consistency-checker\out\pilot
```

In bảng: mỗi lượt app, mỗi lượt CVAT (trước / sau sửa / tổng thời gian gán + sửa) và mốc máy của mỗi frame app;
ghi `cache\pilot_report.csv`. Bài nộp cũng xem được ở `GET /api/pilot/results`.

Nên báo cáo: phút / mục tiêu, % mục tiêu đúng, % bỏ sót, số cuboid thừa – theo A, B1, B2 – và đọc kèm 2 mốc máy.
Với 2 người mỗi nhóm, đây là **số liệu định hướng**, không đủ để kết luận thống kê.
