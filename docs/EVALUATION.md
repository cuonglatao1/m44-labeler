# Đánh giá

Toàn bộ số liệu của M44 Labeler, cách đo và cách chạy lại. Tóm tắt nằm ở [README](../README.md#kết-quả-chính).

## 1. Giao thức

- **Dữ liệu.** Chỉnh ngưỡng trên **nuScenes-mini train** (8 scene, 323 keyframe). Đo trên **nuScenes-mini val** (2 scene,
  81 keyframe) và trên **146 scene val của nuScenes đầy đủ** (150 scene val chính thức trừ 4 scene có trong mini;
  5857 keyframe, 180 421 cuboid; 107 ngày, 24 mưa, 15 đêm). Không bộ đo nào được dùng khi chỉnh, trừ chỗ ghi rõ (bản v2).
- **Lỗi có đáp án.** Cài vào GT sạch bằng `m44.inject` (như repo M44): dời 1–2,5 m, kích thước ×0,6 / ×1,6, xoay 90°
  (chỉ vật dài), đổi class (xe ↔ người), xoá; 30 % cuboid mỗi frame, seed 0. Lỗi được cài vào **mọi frame**, nên
  kiểm tra theo thời gian cũng thấy frame bên cạnh có lỗi.
- **Recall** = tỉ lệ lỗi cài mà cuboid đó bị cờ (lỗi xoá: có cờ `MISSING_3D` đúng chỗ). **Báo động giả** = cờ trên GT
  sạch, tính theo frame. **Độ phủ** = tỉ lệ cuboid mà một nguồn có đủ bằng chứng để kết luận đúng / sai.
- **Luật chấm "đúng"** (giống pilot của M44): tâm lệch ≤ 0,7 m, mỗi cạnh lệch ≤ 25 %, hướng lệch ≤ 20° (mod 180°,
  bỏ qua với người); "lệch nhẹ" = đúng vật trong vòng 2 m.

## 1b. Chỉ số của đề M44: reprojection error và mismatch recall

**Reprojection error** – `python -m labeler.eval_reprojection --split val`: trên GT sạch của mini val (81 frame), mỗi
cuboid được chiếu lên camera và ghép với box YOLO (cấu hình `configs/tuned.json`); đo độ lệch tâm hình chiếu ↔ box
(px), độ lệch so với đường chéo box (rel) và IoU.

| | cặp | lệch tâm trung vị | lệch tâm p90 | rel trung vị | IoU trung vị |
|---|---|---|---|---|---|
| **tất cả** | **1581** | **8,1 px** | **25,6 px** | **4,1 %** | **0,69** |
| 0–20 m | 963 | 11,3 px | 31,1 px | 3,7 % | 0,69 |
| 20–35 m | 467 | 5,4 px | 13,3 px | 4,4 % | 0,69 |
| 35–50 m | 151 | 3,5 px | 9,2 px | 4,8 % | 0,74 |
| car | 750 | 9,3 px | 28,8 px | 3,5 % | 0,75 |
| pedestrian | 661 | 6,9 px | 18,6 px | 5,0 % | 0,58 |

Phần lệch này gồm cả sai số của YOLO (box 2D ôm sát phần nhìn thấy, cuboid gồm cả phần bị che). Riêng phép chiếu của
tool khớp box 2D mà mmdet3d tính sẵn từ cùng nhãn: IoU trung vị 0,949, 96 % cặp ≥ 0,9 (`tests/test_projection.py`). Cờ
camera trên GT sạch: 2,48 / frame.

**Mismatch recall** (tỉ lệ lỗi cài bị cờ, mục 3): chỉ camera bắt 67 % lỗi trên cuboid camera kiểm được và 4 % trên cuboid
camera không kiểm được; M44 Labeler (camera + LiDAR + thời gian) bắt 100 % và 99 %.

## 2. Kiểm tra trên dữ liệu mới (146 scene val nuScenes)

Tool **đóng băng** ở commit `0a2e424` (bản v1) rồi chạy **một lần**. Chỉ dùng gói metadata (nhãn + vị trí xe), nên đo
được các kiểm tra không cần cảm biến: theo thời gian, kích thước, chồng nhau, và chép cuboid. Kiểm tra LiDAR và camera
**chưa** được đo trên dữ liệu mới (cần gói dữ liệu cảm biến).

| nối vật bằng `instance_token` | ngày | mưa | **đêm** | tất cả | (mini val) |
|---|---|---|---|---|---|
| recall dời chỗ | 96 % | 96 % | 97 % | 96 % | 96–99 % |
| recall sai kích thước | 100 % | 100 % | 100 % | 100 % | 99–100 % |
| recall xoay 90° | 94 % | 96 % | 97 % | 95 % | 98–99 % |
| recall đổi class | 100 % | 100 % | 100 % | 100 % | 99–100 % |
| **recall mọi lỗi** | **98 %** | **98 %** | **99 %** | **98 %** | 98–99 % |
| báo động giả theo thời gian / frame | 0,09 | 0,06 | 0,03 | 0,08 | 0,07 |
| chép cuboid (Ctrl+B) đúng ngay | 97 % | 98 % | 94 % | 97 % | 99 % |

Nối vật chỉ bằng vị trí (`--no-instance`, như cuboid tự vẽ không dùng Ctrl+B): recall mọi lỗi 92 % (dời chỗ 80 %,
đổi class 17 % riêng phần thời gian – xe ↔ người không nối được – nhưng kiểm tra kích thước vẫn bắt 100 %).

**Bản v2** (commit `78ee4f0`) sửa hai kiểm tra không giữ được ở v1. Nó được làm **sau khi đã thấy** kết quả v1 trên các
scene này, nên số của v2 kém khách quan hơn:

- *Kích thước phi lý*: khoảng kích thước mỗi class học từ **700 scene train** của nuScenes đầy đủ (944 881 cuboid, không
  đụng tới val) thay vì 8 scene mini; độ nới chọn theo 10 nhóm scene (×1,225, v1 ×1,4).
- *Chồng nhau*: chỉ xe–xe (ngưỡng 0,3), trừ đầu kéo + rơ-moóc; class khác chỉ khi cùng class chồng ≥ 60 % (gán trùng).

| 146 scene val | v1 | **v2** |
|---|---|---|
| báo động giả kích thước phi lý / frame | 0,85 | **0,14** |
| báo động giả chồng nhau / frame | 0,46 | **0,03** |
| báo động giả mọi kiểm tra không cần cảm biến / frame (`instance_token`) | 1,39 | **0,25** (đêm 0,04) |
| như trên, nối bằng vị trí | 2,14 | **1,00** |
| recall mọi lỗi (`instance_token` / vị trí) | 98 % / 92 % | 98 % / 92 % |

## 3. nuScenes-mini val: camera + LiDAR + thời gian

`python -m labeler.eval_lidar --split val` (81 frame, 4441 cuboid, 1325 lỗi; cấu hình hiện tại = v2).

**Độ phủ trên GT sạch**

| | camera | LiDAR | thời gian | ít nhất một |
|---|---|---|---|---|
| mọi cuboid | 35 % | 54 % | 100 % | 100 % |
| cuboid camera không kiểm được (65 %) | – | 44 % | 99 % | 100 % |

**Recall trên cuboid camera không kiểm được**

| lỗi | n | camera | LiDAR | thời gian | LiDAR + thời gian |
|---|---|---|---|---|---|
| dời chỗ | 202 | 5 % | 16 % | 96 % | 96 % |
| sai kích thước | 165 | 5 % | 72 % | 99 % | 100 % |
| xoay 90° | 137 | 1 % | 28 % | 99 % | 99 % |
| đổi class | 168 | 4 % | 100 % | 99 % | 100 % |
| **tất cả** | **672** | **4 %** | **53 %** | **98 %** | **99 %** |

Trên cuboid camera kiểm được: camera 67 %, LiDAR 64 %, thời gian 99 %, kết hợp 100 %.

**Báo động giả trên GT sạch:** camera 2,48 / frame, LiDAR 2,88 / frame (nhiều nhất "cuboid rỗng" 1,3 / frame – xe tối
màu hoặc nhiều kính cho tia laser xuyên qua – rồi mặt đất), thời gian 0,07 / frame.

**Mức chắc chắn của cờ** (`labeler/qc.py`)

| nhóm | quy tắc | cờ trúng lỗi thật | báo động giả / frame | lỗi bắt được |
|---|---|---|---|---|
| **Chắc chắn** | cuboid bị ≥ 2 nguồn cùng cờ | 98 % | 0,14 | 64 % |
| **Cần xem** | 1 nguồn | 45 % | 5,30 | thêm 35 % (tổng 99 %) |

## 3b. Vật bị quên gán (lỗi "xoá cuboid")

Trước đây chỉ camera bắt được lỗi này (YOLO thấy vật mà không có cuboid). `labeler/missing.py` thêm hai nguồn: **thời
gian** (vật có cuboid ở frame trước và sau, frame này thiếu → dự đoán bằng nội suy) và **LiDAR** (có điểm ở chỗ dự đoán;
nếu tia laser xuyên qua trống trơn thì bỏ cờ). Cờ của cùng một vật từ các nguồn được gộp để tính mức chắc chắn.

| mini val, lỗi xoá | n | camera | LiDAR | thời gian | **tất cả** |
|---|---|---|---|---|---|
| vật camera kiểm được | 96 | 41 % | 65 % | 83 % | **92 %** |
| vật camera **không** kiểm được | 173 | 7 % | 25 % | 68 % | **70 %** |

Trên GT sạch của mini val không có cờ "thiếu" nào. Trên **146 scene val mới** (chỉ phần thời gian): phát hiện **77 %**
vật bị xoá (ngày 77 %, mưa 76 %, đêm 77 %), báo nhầm 0,06 / frame; nối chỉ bằng vị trí: 55 %, báo nhầm 0,45 / frame.
Phần không bắt được chủ yếu là vật ở đầu / cuối scene hoặc chỉ xuất hiện ở một phía (đi vào / ra khỏi tầm nhìn); nới
khoảng nhìn từ 1,1 s lên 1,6 s không thêm được gì.

Với mọi loại lỗi gộp lại (cả xoá), mini val: 98 % trên cuboid camera kiểm được, 93 % trên cuboid camera không kiểm được;
146 scene mới: 93 %.

## 3c. Lỗi nhỏ giống người thật (bản v3)

Lỗi của M44 cố ý lớn (dời 1–2,5 m, ×0,6 / ×1,6, xoay 90°). Người gán thật hay sai nhỏ, nên có thêm bộ lỗi
`labeler/inject_subtle.py` (`--errors subtle`): lệch 0,3–0,6 m, xoay 10–20°, quay ngược đầu 180°, chiều dài ×0,75 / ×1,3,
đáy nâng / hạ 0,25 m, nhầm class gần (car ↔ truck, bus → truck, xe đạp ↔ xe máy). Một số lỗi nằm trong dung sai "đúng"
của pilot nhưng vẫn là lỗi người duyệt muốn thấy.

Bản v2 bắt lỗi nhỏ kém (146 scene mới: 54 % – lệch 28 %, xoay 39 %, **độ cao 2 %**). Bản v3 (sửa **sau khi** thấy kết quả
này): thêm kiểm tra **Nhảy độ cao** (đáy so với chính vật đó ở frame bên cạnh) và **học lại ngưỡng thời gian trên 700
scene train** của nuScenes đầy đủ, ngân sách báo nhầm 0,5 % mỗi kiểm tra như mọi kiểm tra khác (hướng 15° → 5°, kích
thước 10 % → 5 %, độ cao 0,12–0,15 m, vị trí xe 0,46 m, người 0,22 m):
`python -m labeler.calib_lidar --annotations-from D:/data/nuscenes-trainval --temporal-budget 0.005`.

| lỗi nhỏ, recall | 146 scene mới v2 | **146 scene mới v3** | mini val v3, camera không thấy |
|---|---|---|---|
| lệch 0,3–0,6 m | 28 % | **65 %** | 74 % |
| xoay 10–20° | 39 % | **93 %** | 96 % |
| quay ngược 180° | 91 % | **91 %** | 92 % |
| chiều dài ×0,75 / ×1,3 | 100 % | **100 %** | 100 % |
| đáy ±0,25 m | 2 % | **80 %** | 78 % |
| nhầm class gần | 98 % | **98 %** | 98 % |
| **mọi lỗi nhỏ** | 54 % | **85 %** (đêm 84 %) | 87 % |

Lỗi lớn của M44 không giảm (146 scene mới, kể cả xoá: 94 %; mini val camera không thấy: 93 %).

**Cái giá:** báo nhầm theo thời gian trên GT sạch tăng từ 0,08 lên **0,42 / frame** (146 scene mới; nhảy vị trí 0,18,
nhảy độ cao 0,17, thiếu cuboid 0,06, nhảy hướng 0,02); mini val 0,07 → 0,31. Mọi kiểm tra không cần cảm biến cộng lại:
0,59 / frame (đêm 0,15). Nối chỉ bằng vị trí (không có mã vật): báo nhầm 2,0 / frame, recall lỗi nhỏ 82 %. Cờ nhóm
"Chắc chắn" vẫn trúng lỗi thật 97 % với lỗi lớn, 90 % với lỗi nhỏ (0,16 báo nhầm / frame).

## 4. Gợi ý sửa

Áp dụng gợi ý cho mỗi lỗi bị cờ rồi chấm theo luật "đúng".

| nguồn cờ | sửa đúng | ghi chú |
|---|---|---|
| thời gian | 92 % | lấy kích thước trung vị / vị trí nội suy / class đa số |
| thiếu cuboid (thời gian / LiDAR) | – | tạo cuboid nội suy; thử trên val 25: lệch 3–4 cm so với cuboid gốc |
| LiDAR | 47 % | trượt / dựng lại theo điểm, đổi class khi kích thước khớp class khác loại |
| camera (`eval_fix`) | 51 % | đổi class 93 %, xoay 79 %, kích thước 74 %, dời 43 %, tạo lại cuboid đã xoá 18 % |

Áp dụng gợi ý lên cờ **báo động giả** làm hỏng cuboid đúng khoảng 2/3 số lần; vì vậy app khoá nút Áp dụng của cờ
"cần xem" cho tới khi người gán bấm Xem trước. Với gợi ý camera, *tin cậy cao* (cuboid mới ôm thêm rõ rệt điểm LiDAR)
trúng lỗi thật 96 %, *tin cậy thấp* 73 %.

## 5. Chép cuboid sang frame sau (Ctrl+B)

`python -m labeler.eval_propagate --split val`: người gán được giả lập làm đúng frame trước (= GT) rồi chép sang.

| cách chép (mini val, 4361 cuboid) | đúng ngay | lệch nhẹ | lệch xa |
|---|---|---|---|
| chép nguyên toạ độ | 3 % | 20 % | 78 % |
| + bù chuyển động xe ego | 89 % | 8 % | 3 % |
| **+ vận tốc của vật (app)** | **99 %** | 1 % | 0 % |
| + kéo theo điểm LiDAR (không dùng) | 91 % | 9 % | 0 % |

Vật đứng yên đúng 100 %, đang chạy 94 %; mỗi lần chép còn ~3–4 % vật mới phải vẽ và ~3–4 % cuboid phải xoá. Bước kéo theo
điểm LiDAR làm kém đi ở mọi ngưỡng thử trên train nên bị tắt. Chép nối tiếp không sửa thì sai dồn (53 % đúng sau 5
frame, `--chain 5`). Trên 146 scene mới: 97 % (đêm 94 %).

## 5b. Công sức gán cả scene từ đầu (người gán mô phỏng)

Chưa có pilot người thật, nên một người gán được mô phỏng trên 2 scene mini val (81 keyframe, 4441 cuboid), frame nối
frame: frame đầu bấm Shift+G; mỗi frame sau bấm Ctrl+B rồi Shift+G; cái gì tool làm chưa đúng thì sửa tay; người gán làm
đúng hết một frame rồi mới sang frame sau (`python -m labeler.eval_effort --split val [--shift-g every|first|never]`).
Mỗi cuboid tool đặt được chấm theo luật "đúng"; mỗi thao tác tay (chỉnh / vẽ / xoá) tính là 1, gán tay hoàn toàn thì
mỗi vật là 1 lần vẽ.

| cách dùng | cuboid tool đặt đúng ngay | lệch nhẹ (chỉnh 1 lần) | phải vẽ tay | xoá | thao tác tay | **tiết kiệm** |
|---|---|---|---|---|---|---|
| Ctrl+B + Shift+G mọi frame | 94 % | 2 % | 4 % | 191 | 458 | 90 % |
| **Ctrl+B + Shift+G frame đầu** | **94 %** | 1 % | 5 % | 142 | **410** | **91 %** |
| chỉ Ctrl+B | 94 % | 1 % | 5 % | 135 | 406 | 91 % |

(car + người: 94 % đúng ngay, tiết kiệm 91 %.) Ctrl+B đặt 4361 cuboid, đúng 96 %, phải xoá 3 % (vật đã đi khỏi). Shift+G
gần như không thêm gì: ở frame đầu nó dựng đúng 5 %, lệch nhẹ 15 % số vật; ở các frame sau, các ô cam còn lại sau khi chép
phần lớn là YOLO nhận nhầm hoặc vật không được gán, nên 77 % gợi ý phải xoá – vì vậy nên bấm Shift+G ở frame đầu, còn sau
Ctrl+B chỉ bấm từng ô cam đáng tin.

Giới hạn: frame trước luôn đúng (= GT), trong khi người thật để lại lỗi và cuboid chép mang theo lỗi đó (các cờ kiểm tra
sẽ chỉ ra); "1 thao tác cho mỗi vật vẽ tay" đánh giá thấp công vẽ tay, nên con số tiết kiệm là ước lượng thận trọng về
số thao tác, không phải thời gian.

## 6. Gợi ý cuboid từ ảnh (2D → 3D)

`python -m labeler.eval_propose --split val`: gợi ý từ box YOLO khớp với một cuboid GT, so với chính cuboid đó.

| class | n | IoU BEV trung vị | IoU ≥ 0,5 | lệch tâm trung vị | lệch hướng trung vị |
|---|---|---|---|---|---|
| car | 707 | 0,53 | 55 % | 0,56 m | 10° |
| pedestrian | 620 | 0,42 | 38 % | 0,23 m | 40° (người không có hướng rõ) |
| truck | 57 | 0,51 | 51 % | 1,04 m | 3° |
| bus | 24 | 0,48 | 38 % | 1,10 m | 11° |

Mốc máy – chỉ bấm Shift+G trên frame rỗng, không chỉnh (`python -m labeler.eval_assist --split val`; mục tiêu = car và
người nhìn thấy ≥ 60 % trong 30 m): đúng 32 %, lệch 29 %, bỏ sót 39 % trên 1505 mục tiêu. Phần bỏ sót là vật YOLO không
thấy hoặc không có điểm LiDAR.

## 7. Chạy lại

Trong thư mục `backend` (`NUSC_ROOT` trỏ tới nuScenes-mini):

```bash
python -m labeler.calib_lidar --split train                                   # ngưỡng LiDAR + thời gian (~6 phút)
python -m labeler.calib_lidar --annotations-from D:/data/nuscenes-trainval    # v2: kích thước + chồng nhau
python -m labeler.eval_reprojection --split val                            # mục 1b
python -m labeler.eval_lidar --split val [--no-instance] [--errors subtle]  # mục 3, 3c, 4
python -m labeler.eval_heldout --nusc-root D:/data/nuscenes-trainval [--no-instance] [--errors subtle]   # mục 2, 3c
python -m labeler.eval_propagate --split val [--chain 5]                      # mục 5
python -m labeler.eval_effort --split val [--shift-g first]                 # mục 5b
python -m labeler.eval_fix --split val                                        # mục 4, gợi ý camera
python -m labeler.eval_propose --split val                                    # mục 6
python -m labeler.eval_assist --split val                                     # mục 6, mốc Shift+G
```

## 8. Giới hạn

- Mọi lỗi là lỗi **cài tổng hợp** (có cả bộ lỗi nhỏ, mục 3c); lỗi của người gán thật (lệch nhỏ, nhầm car ↔ truck, bỏ sót vật bị che) chưa được đo –
  cần pilot với người thật ([PILOT_APP.md](PILOT_APP.md)).
- Kiểm tra LiDAR và camera mới chỉ đo trên mini (2 scene val); ngưỡng LiDAR học từ 8 scene.
- Frame nguồn khi đo chép cuboid là GT (rất mượt); với nhãn người gán, tỉ lệ đúng sẽ thấp hơn.
- Chi tiết các quyết định và phương án đã thử: [decision-log.md](decision-log.md).
