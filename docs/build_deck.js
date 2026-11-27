// UEH C1.1.2 project overview deck (EN / VI). Numbers are read from the pipeline outputs.
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const Fa = require("react-icons/fa");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const REPO = "/home/user/UEHAIDashBoard";
const OUT = process.argv[2];
const metrics = JSON.parse(fs.readFileSync(`${REPO}/artifacts/output/metrics.json`, "utf8"));
const alerts = JSON.parse(fs.readFileSync(`${REPO}/artifacts/output/alerts.json`, "utf8"));
const payload = JSON.parse(fs.readFileSync(`${REPO}/artifacts/output/dashboard_payload.json`, "utf8"));
const record = JSON.parse(fs.readFileSync(`${REPO}/artifacts/output/predictions_course.jsonl`, "utf8").split("\n")[0]);

// ------------------------------------------------------------------ theme
const THEME = {
  name: "UEH Trajectory",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1B2A30", lt1: "FFFFFF", dk2: "0B4F5C", lt2: "EAF3F4",
    accent1: "137A8A", accent2: "F28C28", accent3: "0AAC23", accent4: "257DE0",
    accent5: "DC3C3D", accent6: "6A4CE2", hlink: "137A8A", folHlink: "6A4CE2",
  },
};
const HEX = { teal: "0B4F5C", teal2: "137A8A", orange: "F28C28", amberText: "B45309", ink: "1B2A30", muted: "56676C", soft: "EAF3F4", line: "C9D8DB", white: "FFFFFF", paleOrange: "FDE7D2" };
const STATE = {
  ON_TRACK: { en: "On track", vi: "Đúng tiến độ", c: "0AAC23", s: "✓" },
  IMPROVING: { en: "Improving", vi: "Đang cải thiện", c: "257DE0", s: "↗" },
  STABLE_FRAGILE: { en: "Stable but fragile", vi: "Ổn định nhưng mong manh", c: "F2A600", s: "~" },
  DIVERGING: { en: "Diverging", vi: "Lệch khỏi mục tiêu", c: "DC3C3D", s: "↘" },
  PLAN_ADJUSTED: { en: "Plan adjusted", vi: "Theo kế hoạch điều chỉnh", c: "6A4CE2", s: "⇄" },
  INSUFFICIENT_EVIDENCE: { en: "Insufficient evidence", vi: "Chưa đủ bằng chứng", c: "8C8C8C", s: "?" },
};
const pct = (x, d = 0) => (x * 100).toFixed(d).replace(".", ",") + "%";
const dec = (x, d = 2) => x.toFixed(d).replace(".", ",");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.title = "UEH C1.1.2 Academic Success Trajectory Dashboard";
pres.subject = "Project overview (EN / VI)";
pres.author = "Digital and Data Governance Division";
pres.company = "UEH";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;
const W = 13.333;

// ------------------------------------------------------------------ layouts
const FOOT = "UEH · C1.1.2 Academic Success Trajectory · MVP (synthetic data / dữ liệu mô phỏng)";
pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: HEX.teal },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.7, y: 1.55, w: 7.4, h: 1.7, fontSize: 40, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "vi", type: "body", x: 0.7, y: 3.35, w: 7.4, h: 0.9, fontSize: 24, color: "F6B26B", valign: "top", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "meta", type: "body", x: 0.7, y: 4.75, w: 7.4, h: 1.6, fontSize: 14, color: "CFE3E6", valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: HEX.white },
  margin: [0.5, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.32, w: 12.1, h: 0.66, fontSize: 30, bold: true, color: C.text2, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "vi", type: "body", x: 0.6, y: 0.98, w: 12.1, h: 0.46, fontSize: 18, color: HEX.amberText, valign: "top", margin: 0 }, text: "" } },
    { text: { text: FOOT, options: { x: 0.6, y: 7.02, w: 10.5, h: 0.3, fontSize: 10, color: HEX.muted, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.02, w: 0.5, h: 0.3, fontSize: 10, color: HEX.muted, align: "right" },
});

// ------------------------------------------------------------------ helpers
async function iconPng(Icon, color = "#FFFFFF") {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Icon, { color, size: 256 }));
  const buf = await sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}
async function iconCircle(slide, Icon, x, y, d = 0.62, fill = C.text2) {
  slide.addShape(pres.ShapeType.ellipse, { x, y, w: d, h: d, fill: { color: fill }, line: { type: "none" }, objectName: "icon-circle" });
  const pad = d * 0.24;
  slide.addImage({ data: await iconPng(Icon), x: x + pad, y: y + pad, w: d - 2 * pad, h: d - 2 * pad, objectName: "icon" });
}
function card(slide, x, y, w, h, fill = C.background2, name = "card") {
  slide.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { type: "none" }, objectName: name });
}
// bilingual block: EN (bold, ink) then VI (muted)
function bi(en, vi, size = 14, opts = {}) {
  return [
    { text: en, options: { bold: true, fontSize: size, color: opts.enColor || HEX.ink, breakLine: true } },
    { text: vi, options: { fontSize: size - 1, color: opts.viColor || HEX.muted } },
  ];
}
function text(slide, runs, x, y, w, h, extra = {}) {
  slide.addText(runs, { x, y, w, h, isTextBox: true, margin: 0, valign: "top", paraSpaceAfter: 2, ...extra });
}
function content(title, vi, section) {
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  s.addText(vi, { placeholder: "vi" });
  return s;
}
const chartText = { catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", dataLabelFontFace: "+mn-lt", titleFontFace: "+mn-lt", catAxisLabelColor: HEX.muted, valAxisLabelColor: HEX.muted, dataLabelColor: HEX.ink, catAxisLabelFontSize: 12, valAxisLabelFontSize: 11, dataLabelFontSize: 12 };

(async () => {
  // ================================================================ 1 title
  pres.addSection({ title: "Introduction / Giới thiệu" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Introduction / Giới thiệu" });
  s.addText("Academic Success Trajectory Dashboard", { placeholder: "title" });
  s.addText("Dashboard Quỹ đạo Tiến trình Học tập", { placeholder: "vi" });
  s.addText([
    { text: "UEH Project C1.1.2 · Demo Predictive Analytics Dashboard", options: { breakLine: true, bold: true } },
    { text: "Digital and Data Governance Division", options: { breakLine: true } },
    { text: "Project lead / Trưởng nhóm: Nhiêu Nhật Lương", options: { breakLine: true } },
    { text: "06/2026 – 03/2027 · Version 1.0 · 27/11/2026" },
  ], { placeholder: "meta" });
  // example trajectory of one (synthetic) student, drawn as a native chart
  const ex = payload.students.find((x) => x.id === "S854EF1C0") || payload.students[0];
  const exPts = ex.timeline.map((k) => ex.snapshots[k]);
  card(s, 8.55, 1.55, 4.15, 4.7, "0E5F6E", "example-card");
  text(s, bi("Example trajectory", "Ví dụ quỹ đạo một sinh viên (mô phỏng)", 14, { enColor: HEX.white, viColor: "CFE3E6" }), 8.8, 1.75, 3.7, 0.7);
  s.addChart(pres.ChartType.line, [{ name: "P(plan completion)", labels: exPts.map((p) => (p.type === "EVENT" ? `Event W${p.week}` : `W${p.week}`)), values: exPts.map((p) => p.p_plan) }], {
    x: 8.7, y: 2.5, w: 3.85, h: 3.0, ...chartText, catAxisLabelColor: "CFE3E6", valAxisLabelColor: "CFE3E6", dataLabelColor: "FFFFFF",
    chartColors: ["F6B26B"], lineSize: 3, lineDataSymbol: "circle", lineDataSymbolSize: 9, showValue: true, dataLabelPosition: "t", dataLabelFormatCode: "0%",
    valAxisMinVal: 0, valAxisMaxVal: 1, valAxisLabelFormatCode: "0%", valGridLine: { color: "2B7584", size: 0.5 }, catGridLine: { style: "none" }, showLegend: false,
  });
  text(s, [{ text: "Diverging after week 10 · Lệch sau tuần 10", options: { fontSize: 11, color: "CFE3E6" } }], 8.8, 5.62, 3.7, 0.4);
  s.addNotes("EN: The project builds an AI system that forecasts each student's academic trajectory during the current term and helps advisors decide where support is needed.\nVI: Dự án xây dựng hệ thống AI dự báo quỹ đạo học tập của từng sinh viên trong học kỳ hiện tại và giúp cố vấn xác định nơi cần hỗ trợ.");

  // ================================================================ 2 goals
  s = content("Why this project", "Vì sao cần dự án này", "Introduction / Giới thiệu");
  text(s, [
    { text: "Advisors usually learn about difficulties after final grades are locked, when little can still change.", options: { fontSize: 16, color: HEX.ink, breakLine: true } },
    { text: "Cố vấn thường chỉ biết sinh viên gặp khó khăn khi điểm đã khóa, lúc đó khó thay đổi được gì.", options: { fontSize: 15, color: HEX.muted, breakLine: true } },
    { text: " ", options: { fontSize: 10, breakLine: true } },
    { text: "The system forecasts outcomes at meaningful points in the term and shows them as a trajectory, so support can start early.", options: { fontSize: 16, color: HEX.ink, breakLine: true } },
    { text: "Hệ thống dự báo kết quả tại các mốc có ý nghĩa trong học kỳ và trình bày dưới dạng quỹ đạo, để hỗ trợ sớm.", options: { fontSize: 15, color: HEX.muted } },
  ], 0.6, 1.8, 5.6, 3.2);
  card(s, 0.6, 5.2, 5.6, 1.5, HEX.paleOrange, "callout");
  text(s, bi("Decision support, not automated decisions", "Hỗ trợ ra quyết định, không tự động quyết định học vụ và không gắn nhãn cố định cho người học", 15, { enColor: "7C2D12", viColor: "7C2D12" }), 0.85, 5.38, 5.1, 1.2);
  const goals = [
    [Fa.FaChartLine, "Forecast", "Dự báo", "Course completion, pass, final score, GPA, earned credits, plan completion", "Hoàn thành, đạt học phần, điểm cuối kỳ, GPA, tín chỉ đạt, hoàn thành kế hoạch"],
    [Fa.FaRoute, "Track the trajectory", "Theo dõi quỹ đạo", "Update at 4 milestones and on critical events; show change over time", "Cập nhật tại 4 mốc và khi có sự kiện quan trọng; thể hiện thay đổi"],
    [Fa.FaHandsHelping, "Support advisors", "Hỗ trợ cố vấn", "Prioritised review queue, evidence, owner routing, early-warning alerts", "Danh sách ưu tiên, bằng chứng, đơn vị phụ trách, cảnh báo sớm"],
  ];
  for (let i = 0; i < goals.length; i++) {
    const [ic, en, vi, den, dvi] = goals[i];
    const y = 1.8 + i * 1.65;
    await iconCircle(s, ic, 6.8, y + 0.05, 0.7);
    text(s, [
      { text: `${en} · ${vi}`, options: { bold: true, fontSize: 17, color: HEX.teal, breakLine: true } },
      { text: den, options: { fontSize: 14, color: HEX.ink, breakLine: true } },
      { text: dvi, options: { fontSize: 13, color: HEX.muted } },
    ], 7.75, y, 4.95, 1.5);
  }
  s.addNotes("EN: Three goals: forecast, track the trajectory, support advisors. The system never makes academic decisions.\nVI: Ba mục tiêu: dự báo, theo dõi quỹ đạo, hỗ trợ cố vấn. Hệ thống không tự ra quyết định học vụ.");

  // ================================================================ 3 definition
  s = content("What counts as a successful trajectory", "Thế nào là tiến trình học tập thành công", "Introduction / Giới thiệu");
  const defs = [
    [Fa.FaBullseye, "Learning outcomes", "Đạt hoặc tiến bộ hướng tới chuẩn đầu ra học phần"],
    [Fa.FaLayerGroup, "Credits with quality", "Hoàn thành học phần, tích lũy tín chỉ với chất lượng chấp nhận được"],
    [Fa.FaCalendarCheck, "Pace that fits the plan", "Tiến độ phù hợp kế hoạch chuẩn hoặc kế hoạch cá nhân được duyệt"],
    [Fa.FaGraduationCap, "Moving toward goals", "Tiếp tục hướng tới mục tiêu giáo dục khi được hỗ trợ phù hợp"],
    [Fa.FaSeedling, "Growing autonomy", "Tự chủ, tìm kiếm hỗ trợ, hợp tác, thích ứng với khó khăn"],
  ];
  const cw = (12.1 - 4 * 0.25) / 5;
  for (let i = 0; i < defs.length; i++) {
    const [ic, en, vi] = defs[i];
    const x = 0.6 + i * (cw + 0.25);
    card(s, x, 1.8, cw, 2.75);
    await iconCircle(s, ic, x + 0.25, 2.05, 0.66);
    text(s, bi(en, vi, 15), x + 0.25, 2.9, cw - 0.45, 1.85);
  }
  const rules = [
    ["Attendance, submissions and LMS activity are predictive signals, not proof of success.", "Chuyên cần, nộp bài, LMS là tín hiệu dự báo, không tự thân chứng minh thành công."],
    ["Approved leave, reduced load, exchange or plan changes are never treated as failure.", "Bảo lưu, giảm tải, trao đổi hoặc điều chỉnh kế hoạch được duyệt không bị xem là thất bại."],
  ];
  for (let i = 0; i < rules.length; i++) {
    await iconCircle(s, i ? Fa.FaBalanceScale : Fa.FaInfo, 0.6, 5.2 + i * 0.85, 0.5, C.accent2);
    text(s, bi(rules[i][0], rules[i][1], 14), 1.3, 5.17 + i * 0.85, 11.4, 0.8);
  }
  s.addNotes("EN: Success is a dynamic trajectory with five elements, defined in section 2 of the project spec.\nVI: Thành công là một quỹ đạo động gồm năm yếu tố, theo mục 2 của tài liệu dự án.");

  // ================================================================ 4 scope
  s = content("MVP scope: three measurable dimensions", "Phạm vi MVP: ba chiều đo lường được", "Introduction / Giới thiệu");
  const dims = [
    [Fa.FaBook, "Learning attainment", "Kết quả học phần", ["P(course completion) · XS hoàn thành", "P(pass) · XS đạt", "Final score + 80% interval · Điểm và khoảng dự báo"]],
    [Fa.FaTachometerAlt, "Academic momentum", "Đà học tập", ["Expected credits · Tín chỉ kỳ vọng", "Term GPA · GPA học kỳ", "Progress gap vs plan · Khoảng cách tiến độ"]],
    [Fa.FaClipboardCheck, "Semester plan completion", "Hoàn thành kế hoạch", ["P(plan completion) · XS hoàn thành KH", "Academic standing · Trạng thái học vụ", "Trajectory state · Trạng thái quỹ đạo"]],
  ];
  const dw = (8.6 - 2 * 0.25) / 3;
  for (let i = 0; i < 3; i++) {
    const [ic, en, vi, items] = dims[i];
    const x = 0.6 + i * (dw + 0.25);
    card(s, x, 1.8, dw, 4.9);
    await iconCircle(s, ic, x + 0.25, 2.05, 0.66);
    text(s, bi(en, vi, 17, { enColor: HEX.teal }), x + 0.25, 2.9, dw - 0.45, 0.85);
    text(s, items.map((t, j) => ({ text: t, options: { bullet: true, fontSize: 14, color: HEX.ink, breakLine: j < items.length - 1, paraSpaceAfter: 8 } })), x + 0.25, 3.9, dw - 0.45, 2.6);
  }
  text(s, bi("Not in the MVP", "Chưa đưa vào MVP", 16, { enColor: HEX.muted }), 9.55, 1.85, 3.15, 0.7);
  const outs = ["Long-term dropout prediction · Dự báo bỏ học dài hạn", "Well-being inferred from LMS · Suy luận well-being từ LMS", "Causal impact of interventions · Mô hình nhân quả", "LLM-computed risk scores · LLM tính điểm rủi ro", "Composite Student Success Score · Điểm tổng hợp"];
  outs.forEach((t, i) => {
    card(s, 9.55, 2.65 + i * 0.8, 3.15, 0.66, "F3F5F6", "out-chip");
    text(s, [{ text: t, options: { fontSize: 12, color: HEX.muted } }], 9.7, 2.71 + i * 0.8, 2.9, 0.56, { valign: "middle" });
  });
  s.addNotes("EN: The MVP focuses on dimensions with reliable data. Excluded items are deliberate.\nVI: MVP tập trung vào các chiều có dữ liệu đáng tin cậy; các nội dung loại trừ là chủ đích.");

  // ================================================================ 5 architecture
  pres.addSection({ title: "AI model / Mô hình AI" });
  s = content("Model architecture", "Kiến trúc mô hình: UEH Hierarchical Calibrated CatBoost Trajectory Model", "AI model / Mô hình AI");
  const box = (x, y, w, h, en, vi, fill, enC = HEX.white, viC = "DCEBEE") => {
    s.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { type: "none" }, objectName: "arch-box" });
    text(s, [{ text: en, options: { bold: true, fontSize: 14, color: enC, breakLine: true, align: "center" } }, { text: vi, options: { fontSize: 12, color: viC, align: "center" } }], x + 0.1, y, w - 0.2, h, { valign: "middle" });
  };
  const arrow = (x1, y1, x2, y2) => s.addShape(pres.ShapeType.line, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1), flipV: y2 < y1, line: { color: HEX.muted, width: 1.5, endArrowType: "triangle" }, objectName: "arrow" });
  box(0.6, 2.75, 2.0, 2.0, "Snapshot data", "SV × học phần × kỳ × snapshot", C.text1);
  box(3.0, 2.75, 1.8, 2.0, "Q1 Data quality gate", "Mức đủ dữ liệu", C.accent1);
  box(5.2, 1.75, 2.4, 1.15, "M1 Completion", "XS hoàn thành học phần", C.text2);
  box(5.2, 3.18, 2.4, 1.15, "M2 Pass | completed", "XS đạt khi đã hoàn thành", C.text2);
  box(5.2, 4.61, 2.4, 1.15, "M3 Final score", "Q10 · Q50 · Q90", C.text2);
  box(8.0, 2.75, 2.1, 2.0, "Semester roll-up", "E[TC] = Σ TC × p_pass · Gap = KH − E[TC]", C.accent1);
  box(10.5, 1.75, 2.2, 1.15, "M4 Plan completion", "XS hoàn thành KH", C.text2);
  box(10.5, 3.18, 2.2, 1.15, "R1 Standing", "Học vụ (mô phỏng 400 lần)", "8A5A12");
  box(10.5, 4.61, 2.2, 1.15, "R2 Trajectory state", "6 trạng thái quỹ đạo", "8A5A12");
  arrow(2.6, 3.75, 3.0, 3.75);
  [2.33, 3.75, 5.18].forEach((y) => { arrow(4.8, 3.75, 5.2, y); arrow(7.6, y, 8.0, 3.75); arrow(10.1, 3.75, 10.5, y); });
  s.addShape(pres.ShapeType.roundRect, { x: 0.6, y: 6.05, w: 12.1, h: 0.75, rectRadius: 0.08, fill: { color: HEX.paleOrange }, line: { type: "none" }, objectName: "band" });
  text(s, [{ text: "Reason codes (SHAP + value check) → owner routing → events & alerts → dashboard", options: { bold: true, fontSize: 14, color: "7C2D12", breakLine: true } }, { text: "Mã lý do (SHAP + kiểm tra giá trị thực) → đơn vị phụ trách → sự kiện & cảnh báo → dashboard", options: { fontSize: 13, color: "7C2D12" } }], 0.85, 6.08, 11.6, 0.7, { valign: "middle" });
  text(s, [{ text: "p_pass = p_complete × p_pass|complete", options: { fontSize: 12, color: HEX.muted, italic: true } }], 5.2, 5.8, 3.2, 0.25);
  s.addNotes("EN: Two levels. Course level: M1 to M3. Semester level: M4 plus two rule engines. Rules are deterministic so they can be audited.\nVI: Hai tầng. Tầng học phần: M1–M3. Tầng học kỳ: M4 và hai bộ quy tắc. Quy tắc cố định để dễ kiểm tra.");

  // ================================================================ 6 module table
  s = content("Seven modules", "Bảy khối của hệ thống", "AI model / Mô hình AI");
  const hdr = (t) => ({ text: t, options: { bold: true, color: HEX.white, fill: { color: HEX.teal }, fontSize: 14 } });
  const cell = (t, b = false) => ({ text: t, options: { fontSize: 13, color: HEX.ink, bold: b } });
  const rows = [
    [hdr("Module"), hdr("Output (EN)"), hdr("Đầu ra (VI)"), hdr("Method / Phương pháp")],
    [cell("M1 Course Completion", true), cell("P(complete course)"), cell("XS hoàn thành học phần"), cell("Calibrated CatBoost classifier")],
    [cell("M2 Course Attainment", true), cell("P(pass | completed)"), cell("XS đạt khi đã hoàn thành"), cell("Calibrated CatBoost classifier")],
    [cell("M3 Final Score", true), cell("Score + 80% interval"), cell("Điểm và khoảng dự báo 80%"), cell("CatBoost quantile + conformal")],
    [cell("M4 Plan Completion", true), cell("P(complete term plan)"), cell("XS hoàn thành kế hoạch"), cell("Calibrated CatBoost (stacked)")],
    [cell("R1 Academic Standing", true), cell("GPA band, P(standing OK)"), cell("Khoảng GPA, XS đạt học vụ"), cell("Monte Carlo + UEH rules")],
    [cell("R2 Trajectory State", true), cell("1 of 6 states"), cell("1 trong 6 trạng thái"), cell("Trajectory rule engine")],
    [cell("Q1 Data Quality", true), cell("HIGH / MEDIUM / LOW"), cell("Cao / Trung bình / Thấp"), cell("Coverage, freshness, conflicts")],
  ];
  s.addTable(rows, { x: 0.6, y: 1.8, w: 12.1, colW: [2.9, 3.0, 3.1, 3.1], rowH: 0.52, border: { type: "solid", pt: 0.75, color: HEX.line }, fill: { color: HEX.white }, valign: "middle", margin: [0, 0.1, 0, 0.1] });
  text(s, bi("All features are known at the snapshot date; student IDs and section IDs are never model inputs.", "Mọi biến đều có tại ngày snapshot; mã sinh viên và mã lớp không bao giờ là biến đầu vào.", 14), 0.6, 6.15, 12.1, 0.7);
  s.addNotes("EN: Four learned models, two rule engines, one data quality gate.\nVI: Bốn mô hình học máy, hai bộ quy tắc, một cổng chất lượng dữ liệu.");

  // ================================================================ 7 data & snapshots
  s = content("Data and snapshots", "Dữ liệu và các snapshot", "AI model / Mô hình AI");
  const X = (wk) => 1.0 + ((wk - 4) / 10) * 11.2;
  s.addShape(pres.ShapeType.line, { x: X(4), y: 2.75, w: X(14) - X(4), h: 0, line: { color: HEX.line, width: 3 }, objectName: "timeline" });
  [["Week 4", "Tuần 4", 4], ["Post-midterm", "Sau giữa kỳ", 8], ["Week 10", "Tuần 10", 10], ["Pre-final", "Trước thi cuối kỳ", 14]].forEach(([en, vi, wk]) => {
    s.addShape(pres.ShapeType.ellipse, { x: X(wk) - 0.17, y: 2.58, w: 0.34, h: 0.34, fill: { color: C.text2 }, line: { color: HEX.white, width: 2 }, objectName: "milestone" });
    text(s, [{ text: en, options: { bold: true, fontSize: 13, color: HEX.ink, align: "center", breakLine: true } }, { text: vi, options: { fontSize: 12, color: HEX.muted, align: "center" } }], X(wk) - 0.9, 1.75, 1.8, 0.7);
  });
  [6, 9, 11, 12].forEach((wk) => {
    s.addShape(pres.ShapeType.diamond, { x: X(wk) - 0.15, y: 2.6, w: 0.3, h: 0.3, fill: { color: C.accent2 }, line: { color: HEX.white, width: 1.5 }, objectName: "event" });
    text(s, [{ text: `W${wk}`, options: { fontSize: 11, color: HEX.amberText, align: "center" } }], X(wk) - 0.35, 2.98, 0.7, 0.25);
  });
  text(s, [{ text: "● fixed milestone · mốc cố định    ◆ event-triggered snapshot (only when a new critical condition appears) · snapshot theo sự kiện", options: { fontSize: 12, color: HEX.muted } }], 1.0, 3.3, 11.3, 0.3);
  const groups = [
    [Fa.FaIdCard, "Identity & time", "Định danh, thời gian", "hashed ID, term, course, snapshot week"],
    [Fa.FaHistory, "Academic history", "Lịch sử học tập", "prior GPA, credit ratio, failed courses, warnings"],
    [Fa.FaBookOpen, "Current term", "Học kỳ hiện tại", "current score, coverage, missing work, trend"],
    [Fa.FaUserCheck, "Attendance & LMS", "Chuyên cần & LMS", "rate, absence streak, required LMS activity"],
    [Fa.FaDatabase, "Data quality", "Chất lượng dữ liệu", "freshness, completeness, source conflicts"],
  ];
  const gw = (12.1 - 4 * 0.25) / 5;
  for (let i = 0; i < groups.length; i++) {
    const [ic, en, vi, ex2] = groups[i];
    const x = 0.6 + i * (gw + 0.25);
    card(s, x, 3.85, gw, 2.5);
    await iconCircle(s, ic, x + 0.22, 4.05, 0.56);
    text(s, bi(en, vi, 15), x + 0.22, 4.75, gw - 0.4, 0.8);
    text(s, [{ text: ex2, options: { fontSize: 12, color: HEX.muted } }], x + 0.22, 5.65, gw - 0.4, 1.0);
  }
  s.addNotes("EN: One row = student x course x term x snapshot. Weekly feeds are checked between milestones; a feed becomes a snapshot only when a new critical condition appears.\nVI: Mỗi dòng = SV × học phần × kỳ × snapshot. Dữ liệu hằng tuần được kiểm tra giữa các mốc; chỉ thành snapshot khi xuất hiện điều kiện quan trọng mới.");

  // ================================================================ 8 training
  s = content("How the models are trained", "Quy trình huấn luyện", "AI model / Mô hình AI");
  const terms = [["2023.1 – 2025.1", "Train · Huấn luyện", C.text2, 5.0], ["2025.2", "Calibrate · Hiệu chỉnh", C.accent1, 2.2], ["2026.1", "Test · Kiểm định", C.accent2, 2.2], ["2026.2", "Score · Dự báo", "8C8C8C", 2.2]];
  let tx = 0.6;
  terms.forEach(([t, l, col, w]) => {
    s.addShape(pres.ShapeType.roundRect, { x: tx, y: 1.8, w: w, h: 0.95, rectRadius: 0.06, fill: { color: col }, line: { type: "none" }, objectName: "term" });
    text(s, [{ text: t, options: { bold: true, fontSize: 15, color: HEX.white, align: "center", breakLine: true } }, { text: l, options: { fontSize: 13, color: HEX.white, align: "center" } }], tx, 1.8, w, 0.95, { valign: "middle" });
    tx += w + 0.17;
  });
  const steps = [
    ["Temporal split", "Chia theo thời gian", "Learn from past terms, predict later ones: no leakage across terms.", "Học từ các kỳ trước, dự báo kỳ sau, không rò rỉ dữ liệu."],
    ["Out-of-fold stacking", "Stacking out-of-fold", "M1–M3 predictions for M4 come from 3 student-grouped folds.", "Dự báo M1–M3 cho M4 lấy từ 3 fold chia theo sinh viên."],
    ["Guarded calibration", "Hiệu chỉnh có kiểm soát", "Isotonic or Platt, kept only if grouped CV beats raw output.", "Isotonic hoặc Platt, chỉ giữ khi tốt hơn xác suất thô."],
    ["Conformal intervals", "Khoảng conformal", "Q10–Q90 widened on the calibration term to reach 80% coverage.", "Nới khoảng Q10–Q90 để phủ đúng 80% điểm thực."],
  ];
  const sw = (12.1 - 3 * 0.25) / 4;
  steps.forEach(([en, vi, den, dvi], i) => {
    const x = 0.6 + i * (sw + 0.25);
    card(s, x, 3.05, sw, 3.0);
    s.addShape(pres.ShapeType.ellipse, { x: x + 0.22, y: 3.25, w: 0.5, h: 0.5, fill: { color: C.accent2 }, line: { type: "none" }, objectName: "step-no" });
    text(s, [{ text: String(i + 1), options: { bold: true, fontSize: 16, color: HEX.white, align: "center" } }], x + 0.22, 3.25, 0.5, 0.5, { valign: "middle" });
    text(s, bi(en, vi, 16, { enColor: HEX.teal }), x + 0.22, 3.9, sw - 0.4, 0.75);
    text(s, [{ text: den, options: { fontSize: 13, color: HEX.ink, breakLine: true } }, { text: dvi, options: { fontSize: 12, color: HEX.muted } }], x + 0.22, 4.7, sw - 0.4, 1.3);
  });
  text(s, bi("CatBoost: 400 trees, depth 6, learning rate 0.06, fixed seed · full pipeline ≈ 3 minutes on CPU", "CatBoost: 400 cây, độ sâu 6, learning rate 0,06, seed cố định · toàn bộ quy trình ≈ 3 phút trên CPU", 14), 0.6, 6.25, 12.1, 0.65);
  s.addNotes("EN: Models are trained on the four fixed milestones only; event snapshots are scored by the same models with the teaching week as a numeric input.\nVI: Mô hình chỉ huấn luyện trên 4 mốc cố định; snapshot sự kiện được chấm bằng cùng mô hình, với tuần học là biến số.");

  // ================================================================ 9 results
  s = content("Validation on the held-out term (synthetic data)", "Kết quả kiểm định trên học kỳ 2026.1 (dữ liệu mô phỏng)", "AI model / Mô hình AI");
  const M4 = metrics.M4_plan_completion, M2 = metrics.M2_course_attainment, M3 = metrics.M3_final_score, R1 = metrics.R1_standing;
  const stats = [
    [dec(M4.auc), "M4 plan completion AUC", `vs ${dec(metrics.M4_baselines.prior_cum_gpa_only_auc)} with prior GPA only · so với chỉ dùng GPA`],
    [dec(M2.auc), "M2 pass AUC", `Overall pass (M1×M2) ${dec(metrics.course_pass_overall.auc)} · AUC đạt tổng thể`],
    [pct(M3.coverage_80, 1), "M3 80% interval coverage", `Median error ${dec(M3.mae_median)} points · sai số trung vị`],
    [dec(R1.auc), "R1 standing AUC", `GPA error ${dec(metrics.R1_term_gpa.mae)} · sai số GPA học kỳ`],
  ];
  stats.forEach(([big, en, vi], i) => {
    const x = 0.6 + (i % 2) * 3.05, y = 1.8 + Math.floor(i / 2) * 2.45;
    card(s, x, y, 2.85, 2.25);
    text(s, [{ text: big, options: { bold: true, fontSize: 40, color: HEX.teal, fontFace: "Cambria" } }], x + 0.22, y + 0.15, 2.5, 0.85);
    text(s, [{ text: en, options: { bold: true, fontSize: 13, color: HEX.ink, breakLine: true } }, { text: vi, options: { fontSize: 12, color: HEX.muted } }], x + 0.22, y + 1.05, 2.45, 1.1);
  });
  const ms = metrics.M4_by_milestone;
  const msName = { WEEK_4: "W4", POST_MIDTERM: "Post-mid", WEEK_10: "W10", PRE_FINAL: "Pre-final" };
  s.addChart(pres.ChartType.bar, [{ name: "AUC", labels: [...ms.map((r) => msName[r.group]), "GPA only"], values: [...ms.map((r) => r.auc), metrics.M4_baselines.prior_cum_gpa_only_auc] }], {
    x: 6.9, y: 1.75, w: 5.8, h: 4.6, ...chartText, barDir: "col", chartColors: ["137A8A", "137A8A", "137A8A", "137A8A", "A9B4B7"], barGapWidthPct: 60,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00", valAxisMinVal: 0.5, valAxisMaxVal: 1, valAxisLabelFormatCode: "0.0",
    valGridLine: { color: "E3EAEC", size: 0.5 }, catGridLine: { style: "none" }, showLegend: false,
    showTitle: true, title: "M4 AUC by snapshot · AUC theo snapshot", titleFontSize: 14, titleColor: HEX.ink,
  });
  text(s, [{ text: "W4 = Tuần 4 · Post-mid = Sau giữa kỳ · Pre-final = Trước thi · GPA only = baseline chỉ dùng GPA tích lũy. Accuracy rises as evidence accumulates · Độ chính xác tăng khi có thêm bằng chứng", options: { fontSize: 12, color: HEX.muted } }], 6.9, 6.4, 5.8, 0.4);
  s.addNotes(`EN: All figures are computed on synthetic data and must be recomputed on real UEH data. M4 calibration error on the test term is ${dec(M4.ece, 3)} (raw ${dec(M4.ece_uncalibrated, 3)}), a term-to-term shift to recalibrate each term.\nVI: Mọi số liệu tính trên dữ liệu mô phỏng, cần tính lại trên dữ liệu UEH thật. ECE của M4 trên kỳ kiểm định là ${dec(M4.ece, 3)} (thô ${dec(M4.ece_uncalibrated, 3)}), cần hiệu chỉnh lại mỗi kỳ.`);

  // ================================================================ 10 states
  pres.addSection({ title: "Use / Ứng dụng" });
  s = content("Six trajectory states", "Sáu trạng thái quỹ đạo", "Use / Ứng dụng");
  const order = ["ON_TRACK", "IMPROVING", "STABLE_FRAGILE", "DIVERGING", "PLAN_ADJUSTED", "INSUFFICIENT_EVIDENCE"];
  const meaning = {
    ON_TRACK: "P(plan) ≥ 80% and gap ≤ 1 credit · XS ≥ 80%, thiếu ≤ 1 TC",
    IMPROVING: "P(plan) up ≥ 10 points or gap down · XS tăng hoặc gap giảm",
    STABLE_FRAGILE: "Still on course, thin margin · Còn đúng hướng, biên mỏng",
    DIVERGING: "Drop ≥ 10 points or P < 50% · Giảm mạnh hoặc XS < 50%",
    PLAN_ADJUSTED: "Fits an approved personal plan · Hợp kế hoạch được duyệt",
    INSUFFICIENT_EVIDENCE: "Q1 rates the data LOW · Dữ liệu chưa đủ tin cậy",
  };
  order.forEach((k, i) => {
    const y = 1.78 + i * 0.85, st = STATE[k];
    s.addShape(pres.ShapeType.ellipse, { x: 0.6, y: y + 0.08, w: 0.52, h: 0.52, fill: { color: st.c }, line: { type: "none" }, objectName: "state-dot" });
    text(s, [{ text: st.s, options: { bold: true, fontSize: 16, color: k === "STABLE_FRAGILE" ? HEX.ink : HEX.white, align: "center" } }], 0.6, y + 0.08, 0.52, 0.52, { valign: "middle" });
    text(s, [{ text: `${st.en} · ${st.vi}`, options: { bold: true, fontSize: 14, color: HEX.ink, breakLine: true } }, { text: meaning[k], options: { fontSize: 12, color: HEX.muted } }], 1.3, y, 5.4, 0.78);
  });
  const so = metrics.state_outcomes;
  const soOrder = order.filter((k) => so.find((r) => r.state === k));
  s.addChart(pres.ChartType.bar, [{ name: "Plan completed", labels: soOrder.map((k) => STATE[k].en), values: soOrder.map((k) => so.find((r) => r.state === k).plan_completed_rate) }], {
    x: 7.0, y: 1.75, w: 5.7, h: 4.75, ...chartText, barDir: "bar", chartColors: soOrder.map((k) => STATE[k].c), barGapWidthPct: 50, catAxisOrientation: "maxMin",
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0%", valAxisMinVal: 0, valAxisMaxVal: 1, valAxisLabelFormatCode: "0%",
    valGridLine: { color: "E3EAEC", size: 0.5 }, catGridLine: { style: "none" }, showLegend: false,
    showTitle: true, title: "Actually completed the plan · Thực tế hoàn thành KH", titleFontSize: 14, titleColor: HEX.ink,
  });
  text(s, [{ text: "Test term 2026.1: state assigned at each snapshot vs final outcome · Trạng thái tại snapshot so với kết quả cuối kỳ", options: { fontSize: 12, color: HEX.muted } }], 7.0, 6.5, 5.7, 0.4);
  s.addNotes("EN: Every state carries a colour, an icon and a label, so meaning never depends on colour alone. Thresholds are starting values to be tuned with advisor capacity.\nVI: Mỗi trạng thái có màu, biểu tượng và nhãn chữ. Ngưỡng là giá trị khởi điểm, cần hiệu chỉnh theo năng lực cố vấn.");

  // ================================================================ 11 early warning
  s = content("Early warning for managers", "Cảnh báo sớm cho người quản lý", "Use / Ứng dụng");
  text(s, bi("Event triggers", "Sự kiện kích hoạt snapshot", 16, { enColor: HEX.teal }), 0.6, 1.75, 3.9, 0.7);
  const evs = [[Fa.FaUserSlash, "Absence streak ≥ 3", "Vắng liên tiếp ≥ 3 buổi"], [Fa.FaFileExcel, "≥ 2 mandatory items missing", "Thiếu ≥ 2 bài bắt buộc"], [Fa.FaArrowDown, "Sharp score decline", "Điểm thành phần giảm rõ rệt"], [Fa.FaClipboardList, "Registration incomplete", "Đăng ký chưa hoàn tất"], [Fa.FaExchangeAlt, "Source conflict", "Dữ liệu mâu thuẫn"]];
  for (let i = 0; i < evs.length; i++) {
    await iconCircle(s, evs[i][0], 0.6, 2.5 + i * 0.85, 0.5, C.accent2);
    text(s, bi(evs[i][1], evs[i][2], 14), 1.25, 2.5 + i * 0.85, 3.3, 0.75);
  }
  text(s, bi("Alert scopes", "Phạm vi cảnh báo", 16, { enColor: HEX.teal }), 4.75, 1.75, 3.9, 0.7);
  const nStu = alerts.filter((a) => a.scope === "STUDENT").length, nHigh = alerts.filter((a) => a.scope === "STUDENT" && a.severity === "HIGH").length;
  const scopes = [[Fa.FaUserGraduate, "Student", "Sinh viên: sự kiện có tác động, rơi vào lệch, XS giảm mạnh"], [Fa.FaSitemap, "Program", "Chương trình: tỷ lệ lệch mục tiêu tăng"], [Fa.FaBook, "Course", "Học phần: SV khó đạt cao bất thường"], [Fa.FaDatabase, "Data", "Dữ liệu: thiếu bằng chứng, nguồn chưa cập nhật"], [Fa.FaClock, "Overdue review", "Quá hạn: khẩn 3 ngày, cần chú ý 7 ngày"]];
  for (let i = 0; i < scopes.length; i++) {
    await iconCircle(s, scopes[i][0], 4.75, 2.5 + i * 0.85, 0.5);
    text(s, bi(scopes[i][1], scopes[i][2], 14), 5.4, 2.5 + i * 0.85, 3.3, 0.75);
  }
  const E = metrics.events;
  const evStats = [[pct(E.share_students_with_event), "students with ≥ 1 event", "SV có ít nhất một sự kiện"], [`${pct(E.plan_completed_rate_with_event)} vs ${pct(E.plan_completed_rate_without_event)}`, "plan completed: with vs without event", "hoàn thành KH: có / không có sự kiện"], [`${dec(E.mean_lead_weeks, 1)} wk`, "ahead of the next fixed milestone", "sớm hơn mốc cố định kế tiếp"]];
  evStats.forEach(([big, en, vi], i) => {
    const y = 1.8 + i * 1.62;
    card(s, 9.0, y, 3.7, 1.45);
    text(s, [{ text: big, options: { bold: true, fontSize: 28, color: HEX.teal, fontFace: "Cambria" } }], 9.22, y + 0.12, 3.3, 0.6);
    text(s, [{ text: en, options: { bold: true, fontSize: 12, color: HEX.ink, breakLine: true } }, { text: vi, options: { fontSize: 12, color: HEX.muted } }], 9.22, y + 0.75, 3.3, 0.65);
  });
  text(s, [{ text: `Current term: ${nStu} student alerts (${nHigh} urgent), ${alerts.length - nStu} course/data alerts · Học kỳ hiện tại: ${nStu} cảnh báo sinh viên (${nHigh} khẩn)`, options: { fontSize: 12, color: HEX.muted } }], 0.6, 6.75, 12.1, 0.25);
  s.addNotes("EN: An event becomes a manager alert only when the forecast also worsens; otherwise it stays visible in the student detail. The same condition cannot re-trigger within four weeks.\nVI: Sự kiện chỉ thành cảnh báo khi dự báo cũng xấu đi; nếu không, chỉ hiện trong chi tiết sinh viên. Cùng một điều kiện không kích hoạt lại trong 4 tuần.");

  // ================================================================ 12 dashboard tour
  s = content("The dashboard", "Giao diện dashboard", "Use / Ứng dụng");
  const shots = [["img_overview.png", 1400 / 860, "Overview", "Tổng quan: KPI, phân bố và chuyển trạng thái"], ["img_alerts.png", 1400 / 900, "Alerts", "Cảnh báo: mức độ, phụ trách, quá hạn"], ["img_drawer.png", 859 / 900, "Student detail", "Chi tiết SV: quỹ đạo theo tuần, sự kiện ◆"]];
  const ih = 2.85;
  let ix = 0.6;
  shots.forEach(([f, ar, en, vi]) => {
    const iw = ih * ar;
    s.addImage({ path: path.join(__dirname, f), x: ix, y: 1.75, w: iw, h: ih, altText: `${en} screen of the dashboard`, objectName: "screenshot", shadow: { type: "outer", blur: 6, offset: 2, angle: 90, color: "000000", opacity: 0.18 } });
    text(s, bi(en, vi, 14), ix, 1.75 + ih + 0.15, iw, 0.7);
    ix += iw + 0.2;
  });
  const feats = [["Views: 4 milestones + latest (events included)", "Xem theo 4 mốc và \"Mới nhất\" (gồm sự kiện)"], ["Review queue sorted by priority, filters, owner", "Danh sách ưu tiên, bộ lọc, đơn vị phụ trách"], ["Model card: metrics, calibration, fairness", "Thẻ mô hình: chỉ số, hiệu chỉnh, công bằng"], ["Light / dark, phone-ready, colour + icon + label", "Sáng/tối, điện thoại, màu + biểu tượng + nhãn"]];
  feats.forEach(([en, vi], i) => {
    const x = 0.6 + (i % 2) * 6.15, y = 5.55 + Math.floor(i / 2) * 0.68;
    s.addShape(pres.ShapeType.ellipse, { x, y: y + 0.08, w: 0.2, h: 0.2, fill: { color: C.accent2 }, line: { type: "none" }, objectName: "dot" });
    text(s, [{ text: en, options: { bold: true, fontSize: 13, color: HEX.ink, breakLine: true } }, { text: vi, options: { fontSize: 12, color: HEX.muted } }], x + 0.35, y, 5.6, 0.62);
  });
  s.addNotes("EN: Static web page, no server needed; works offline from one HTML file or from a web host.\nVI: Trang web tĩnh, không cần máy chủ; chạy từ một file HTML hoặc trên web host.");

  // ================================================================ 13 outputs
  s = content("System outputs", "Đầu ra của hệ thống", "Use / Ứng dụng");
  const keys = ["student_id_hash", "term_id", "course_id", "snapshot_milestone", "p_course_completion", "p_course_pass", "predicted_final_score", "predicted_score_lower", "predicted_score_upper", "expected_earned_credits", "approved_plan_credits", "p_plan_completion", "progress_gap_credits", "trajectory_state", "data_confidence", "support_reason_codes", "recommended_owner", "review_status"];
  const json = "{\n" + keys.map((k) => `  "${k}": ${JSON.stringify(record[k])}`).join(",\n") + "\n}";
  s.addShape(pres.ShapeType.roundRect, { x: 0.6, y: 1.75, w: 6.3, h: 5.1, rectRadius: 0.06, fill: { color: "13242B" }, line: { type: "none" }, objectName: "code-box" });
  text(s, [{ text: json, options: { fontFace: "Courier New", fontSize: 11.5, color: "D7E7EA" } }], 0.85, 1.9, 5.9, 4.85);
  const files = [[Fa.FaFileCode, "predictions_course.jsonl", "One record per student × course × snapshot (spec §11 schema)", "Một dòng / SV × học phần × snapshot"], [Fa.FaBell, "alerts.json", "Current alerts with Vietnamese titles; feeds the e-mail digest later", "Cảnh báo hiện hành; đầu vào cho email sau này"], [Fa.FaChartBar, "metrics.json", "Model card: AUC, Brier, ECE, coverage, subgroups, events", "Thẻ mô hình: chỉ số, nhóm con, sự kiện"], [Fa.FaDesktop, "dashboard/", "Static dashboard (index.html + data.js) or one bundled HTML", "Dashboard tĩnh hoặc một file HTML"]];
  for (let i = 0; i < files.length; i++) {
    const y = 1.75 + i * 1.3;
    await iconCircle(s, files[i][0], 7.2, y + 0.1, 0.56);
    text(s, [{ text: files[i][1], options: { bold: true, fontSize: 14, color: HEX.teal, fontFace: "Courier New", breakLine: true } }, { text: files[i][2], options: { fontSize: 13, color: HEX.ink, breakLine: true } }, { text: files[i][3], options: { fontSize: 12, color: HEX.muted } }], 7.95, y, 4.75, 1.2);
  }
  s.addNotes("EN: The JSON record follows section 11 of the spec exactly; the example is a real record from the synthetic run.\nVI: Bản ghi JSON theo đúng mục 11 của tài liệu dự án; ví dụ lấy từ lần chạy mô phỏng.");

  // ================================================================ 14 governance
  pres.addSection({ title: "Governance & next steps / Quản trị & bước tiếp theo" });
  s = content("Responsible AI by design", "Quản trị AI có trách nhiệm", "Governance & next steps / Quản trị & bước tiếp theo");
  const gov = [
    [Fa.FaUserTie, "Human decides", "Con người quyết định", "The system routes cases for review; it never takes academic action."],
    [Fa.FaTags, "No fixed labels", "Không gắn nhãn cố định", "States change each snapshot; no \"at-risk student\" label."],
    [Fa.FaBalanceScale, "Fair to approved paths", "Công bằng với lộ trình được duyệt", "Leave, reduced load, exchange and withdrawals are not failures."],
    [Fa.FaSearch, "Explainable", "Giải thích được", "Reason codes from SHAP, checked against the student's real values."],
    [Fa.FaShieldAlt, "Privacy", "Quyền riêng tư", "Hashed IDs; no well-being inference; IDs are not model inputs."],
    [Fa.FaClipboardCheck, "Audited fairness", "Rà soát công bằng", "Calibration and AUC checked per program; gaps over 5 points flagged."],
  ];
  const gw2 = (12.1 - 2 * 0.3) / 3;
  for (let i = 0; i < gov.length; i++) {
    const [ic, en, vi, d] = gov[i];
    const x = 0.6 + (i % 3) * (gw2 + 0.3), y = 1.8 + Math.floor(i / 3) * 2.3;
    card(s, x, y, gw2, 2.05);
    await iconCircle(s, ic, x + 0.25, y + 0.25, 0.6);
    text(s, bi(en, vi, 16, { enColor: HEX.teal }), x + 1.05, y + 0.22, gw2 - 1.3, 0.8);
    text(s, [{ text: d, options: { fontSize: 13, color: HEX.ink } }], x + 0.25, y + 1.15, gw2 - 0.5, 1.05);
  }
  s.addNotes("EN: Governance principles from the spec are encoded in the rules and tested.\nVI: Các nguyên tắc quản trị trong tài liệu được mã hóa thành quy tắc và có kiểm thử.");

  // ================================================================ 15 limitations & next steps
  s = content("Limitations and path to production", "Giới hạn hiện tại và lộ trình triển khai", "Governance & next steps / Quản trị & bước tiếp theo");
  card(s, 0.6, 1.8, 5.9, 4.4, "F3F5F6", "limits");
  text(s, bi("Current limitations", "Giới hạn hiện tại", 17, { enColor: HEX.muted }), 0.85, 1.98, 5.4, 0.75);
  const lim = [["Synthetic data only", "Chỉ dùng dữ liệu mô phỏng"], ["Standing rules use the TT 08/2021 template", "Quy tắc học vụ theo khung TT 08/2021, cần đối chiếu quy chế UEH"], ["M4 calibration shifts between terms", "Hiệu chỉnh M4 dịch chuyển giữa các kỳ"], ["GPA band assumes independent courses (71% vs 80%)", "Khoảng GPA giả định HP độc lập (71% so với 80%)"], ["Review status stored per browser", "Trạng thái xem xét lưu trên trình duyệt"]];
  text(s, lim.flatMap(([en, vi], i) => [{ text: en, options: { bullet: true, bold: true, fontSize: 14, color: HEX.ink, breakLine: true } }, { text: vi, options: { fontSize: 13, color: HEX.muted, indentLevel: 1, breakLine: i < lim.length - 1, paraSpaceAfter: 8 } }]), 0.85, 2.8, 5.45, 3.9);
  card(s, 6.8, 1.8, 5.9, 4.4, C.background2, "next");
  text(s, bi("Next steps", "Bước tiếp theo", 17, { enColor: HEX.teal }), 7.05, 1.98, 5.4, 0.75);
  const nxt = [["Data-sharing agreement; SIS, LMS, attendance extract", "Thỏa thuận dữ liệu; trích xuất SIS, LMS, chuyên cần"], ["Confirm pass mark, grade scale, standing rules", "Đối chiếu ngưỡng đạt, thang điểm, quy tắc học vụ"], ["Retrain, tune thresholds to advisor capacity", "Huấn luyện lại, chỉnh ngưỡng theo năng lực cố vấn"], ["Shared case API, weekly feeds, e-mail digest", "API ca hỗ trợ, dữ liệu hằng tuần, bản tin email"], ["Pilot with advisors, then review fairness", "Thí điểm với cố vấn, rà soát công bằng"]];
  text(s, nxt.flatMap(([en, vi], i) => [{ text: en, options: { bullet: { type: "number" }, bold: true, fontSize: 14, color: HEX.ink, breakLine: true } }, { text: vi, options: { fontSize: 13, color: HEX.muted, indentLevel: 1, breakLine: i < nxt.length - 1, paraSpaceAfter: 8 } }]), 7.05, 2.8, 5.45, 3.9);
  s.addNotes("EN: The MVP proves the pipeline end to end; real-data validation and advisor pilots come next.\nVI: MVP chứng minh quy trình chạy trọn vẹn; tiếp theo là kiểm định trên dữ liệu thật và thí điểm với cố vấn.");

  // ================================================================ 16 closing
  s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Governance & next steps / Quản trị & bước tiếp theo" });
  s.addText("Thank you", { placeholder: "title" });
  s.addText("Cảm ơn quý thầy cô và đồng nghiệp", { placeholder: "vi" });
  s.addText([
    { text: "MVP dashboard: nnluongiem-code.github.io/UEHAIDashBoard", options: { breakLine: true, bold: true } },
    { text: "Source code / Mã nguồn: github.com/nnluongiem-code/UEHAIDashBoard", options: { breakLine: true } },
    { text: "Partners / Phối hợp: Ban Quản trị hạ tầng, Ban Đào tạo, DSA" },
  ], { placeholder: "meta" });
  card(s, 8.55, 1.55, 4.15, 4.7, "0E5F6E", "summary-card");
  const sums = [[`${payload.students.length}`, "students scored this term", "SV được dự báo kỳ này"], [dec(M4.auc), "M4 AUC on the test term", "AUC M4 trên kỳ kiểm định"], [`${dec(E.mean_lead_weeks, 1)} wk`, "earlier warning from events", "cảnh báo sớm nhờ sự kiện"]];
  sums.forEach(([big, en, vi], i) => {
    const y = 1.8 + i * 1.45;
    text(s, [{ text: big, options: { bold: true, fontSize: 30, color: "F6B26B", fontFace: "Cambria" } }], 8.85, y, 3.6, 0.6);
    text(s, [{ text: en, options: { fontSize: 13, color: HEX.white, breakLine: true } }, { text: vi, options: { fontSize: 12, color: "CFE3E6" } }], 8.85, y + 0.62, 3.6, 0.65);
  });
  s.addNotes("EN: Questions and discussion.\nVI: Hỏi đáp và thảo luận.");

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})().catch((e) => { console.error(e); process.exit(1); });
