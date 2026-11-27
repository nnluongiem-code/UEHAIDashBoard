# UEH C1.1.2 – Academic Success Trajectory Dashboard

Mô hình AI và dashboard dự báo, theo dõi quỹ đạo tiến trình học tập của sinh viên trong học kỳ hiện tại.

> **Hệ thống hỗ trợ cố vấn, không tự động ra quyết định học vụ** và không gắn nhãn cố định cho người học.
> Bản hiện tại chạy trên **dữ liệu mô phỏng**; mọi chỉ số kiểm định phải được tính lại trên dữ liệu UEH thật.

## Chạy nhanh

```bash
pip install -r requirements.txt
python scripts/run_pipeline.py      # sinh dữ liệu mô phỏng → huấn luyện → kiểm định → dự báo → xuất (~3 phút)
python -m pytest -q tests           # kiểm thử quy tắc, cổng chất lượng và schema đầu ra
```

Mở `dashboard/index.html` trực tiếp bằng trình duyệt; không cần máy chủ, vì dữ liệu nằm trong `dashboard/data.js`.

Khi có dữ liệu thật:

```bash
python scripts/run_pipeline.py --course-csv course_snapshots.csv --term-csv term_labels.csv
```

Hai file phải theo đúng tên cột do `ueh_trajectory/synthetic.py` sinh ra. Đó là data contract của mục 9–10 trong đặc tả.

## Kiến trúc mô hình – *UEH Hierarchical Calibrated CatBoost Trajectory Model*

```
 dữ liệu snapshot (SV × HP × kỳ × snapshot)
        │
        ▼
  Q1 Data Quality Gate ──► data_confidence HIGH / MEDIUM / LOW
        │
        ├─► M1 Course Completion   CatBoost + hiệu chỉnh xác suất    p_complete
        ├─► M2 Course Attainment   CatBoost + hiệu chỉnh (HP đã HT)  p_pass|complete
        │                          p_pass = p_complete × p_pass|complete
        └─► M3 Final Score         CatBoost MultiQuantile + conformal  Q10 / Q50 / Q90
                │
                ▼  tổng hợp cấp học kỳ (stacking out-of-fold)
        E[tín chỉ đạt] = Σ credit_j × p_pass,j ;  ProgressGap = plan − E[tín chỉ]
                │
                ├─► M4 Plan Completion  CatBoost + hiệu chỉnh            p_plan
                ├─► R1 Academic Standing  Monte Carlo + quy tắc học vụ    GPA [Q10–Q90], P(đạt học vụ)
                └─► R2 Trajectory State   quy tắc Δp, gap, Q1             6 trạng thái
                        │
                        ▼
              Reason codes (SHAP + kiểm tra giá trị thực) → recommended_owner → review_status
```

| Module | Tệp | Ghi chú kỹ thuật |
|---|---|---|
| M1, M2, M4 | `models.py` | CatBoost; hiệu chỉnh trên học kỳ riêng: isotonic khi ≥ 5.000 dòng, Platt khi ít hơn; xác suất giới hạn trong [0,01; 0,99] |
| M3 | `models.py` | Phân vị 0,1 / 0,5 / 0,9 và conformal (CQR) để khoảng 80% phủ đúng khoảng 80% |
| Q1 | `quality.py` | Điểm chất lượng từ độ bao phủ điểm (so với kỳ vọng của mốc), chuyên cần, LMS, độ đầy đủ, độ mới và mâu thuẫn nguồn |
| R1 | `rules.py` | 400 lần mô phỏng kết quả học phần → GPA học kỳ và tích lũy → quy tắc học vụ (khung TT 08/2021, **cần đối chiếu quy chế UEH**) |
| R2 | `rules.py` | Thứ tự xét: Q1 thấp → kế hoạch điều chỉnh → giảm mạnh → đúng tiến độ → cải thiện → mong manh → lệch |
| Reason codes | `reasons.py` | Chỉ phát mã khi SHAP cùng chiều **và** giá trị thực nằm trong vùng tương ứng |
| Pipeline | `pipeline.py` | Chia theo thời gian: train 2023.1–2025.1, hiệu chỉnh 2025.2, kiểm định 2026.1, dự báo 2026.2 |

Mọi ngưỡng nằm trong `ueh_trajectory/config.py`.

### Nguyên tắc nghiệp vụ được mã hóa

- Rút học phần được phê duyệt giảm tín chỉ kế hoạch, không bị tính là không đạt.
- Giảm tải hoặc rút học phần được duyệt dẫn đến trạng thái `PLAN_ADJUSTED` nếu vẫn đúng kế hoạch mới. Nếu kế hoạch mới cũng gặp khó khăn, trường hợp vẫn được hiển thị.
- Bảo lưu và trao đổi học tập không tạo bản ghi học kỳ, nên không bao giờ bị gán nhãn bất lợi.
- LMS chỉ được dùng ở học phần thiết kế hoạt động LMS bắt buộc. Học phần khác để trống và không bị trừ điểm chất lượng.
- Mã định danh (`student_id_hash`, `section_id`) không bao giờ là biến đầu vào của mô hình.

## Đầu ra

| Tệp | Nội dung |
|---|---|
| `artifacts/output/predictions_course.jsonl` | Một dòng cho mỗi SV × HP × snapshot, đúng schema mục 11 của đặc tả (thêm `course_id`) |
| `artifacts/output/dashboard_payload.json` | Cấu trúc lồng SV → snapshot → học phần cho dashboard |
| `artifacts/output/metrics.json` | Model card: AUC, Brier, ECE, reliability, coverage, theo snapshot và chương trình, kết quả theo trạng thái |
| `dashboard/data.js` | Payload ở dạng script để mở dashboard không cần máy chủ |

## Dashboard (`dashboard/index.html`)

- **Tổng quan**: KPI có so sánh với snapshot trước, phân bố trạng thái qua các snapshot, ma trận chuyển trạng thái, lý do hỗ trợ phổ biến, phân tích theo chương trình.
- **Danh sách xem xét**: lọc theo trạng thái, chương trình, mức dữ liệu, đơn vị phụ trách và trạng thái xem xét. Danh sách sắp theo mức ưu tiên.
- **Chi tiết sinh viên** gồm:
  - quỹ đạo `p_plan` qua các snapshot;
  - tín chỉ kỳ vọng, GPA kèm khoảng dự báo, dự báo học vụ;
  - bằng chứng tích cực và lý do cần hỗ trợ;
  - bảng học phần có khoảng điểm Q10–Q90;
  - ghi nhận xem xét của cố vấn. Bản demo lưu ghi nhận trên trình duyệt; bản triển khai cần ghi vào hệ thống quản lý ca hỗ trợ.
- **Mô hình & kiểm định**: chỉ số M1–M4 và R1, biểu đồ hiệu chỉnh, AUC theo snapshot so với baseline, kết quả thực tế theo trạng thái, feature importance, kiểm tra công bằng theo chương trình, ngưỡng và giới hạn.

Dashboard hỗ trợ giao diện sáng/tối và màn hình điện thoại. Trạng thái luôn có nhãn chữ và biểu tượng, không chỉ dựa vào màu.

## Việc cần làm trước khi dùng với sinh viên thật

1. Ký thỏa thuận chia sẻ dữ liệu, lấy dữ liệu từ SIS, LMS và hệ thống chuyên cần, ánh xạ vào data contract.
2. Đối chiếu `PASS_SCORE`, thang quy đổi điểm và `STANDING_RULES` với quy chế UEH hiện hành (Ban Đào tạo).
3. Huấn luyện lại, đọc model card, hiệu chỉnh ngưỡng R2 theo năng lực xử lý của cố vấn (mục 7 của đặc tả).
4. Rà soát công bằng theo chương trình, khóa tuyển, giới tính và vùng miền nếu được phép dùng các biến này cho kiểm định.
5. Thay lưu trữ `localStorage` của phần ghi nhận bằng API có phân quyền và nhật ký truy cập.
