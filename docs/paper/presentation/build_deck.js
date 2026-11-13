// Defense presentation for the wildfire study, following the structure of the course template:
// title -> problem statement -> input data -> models and methods -> results -> conclusion -> thanks.
// Every number comes from runs/public_hindcast; code-cell outputs come from cell_outputs.py.

const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");
const sharp = require("sharp");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const fa = require("react-icons/fa6");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const HERE = __dirname;
const FIG = path.join(HERE, "figs");
const CELLS = JSON.parse(fs.readFileSync(path.join(HERE, "cells.json"), "utf8"));
const TABLES = JSON.parse(fs.readFileSync(path.join(FIG, "tables.json"), "utf8"));
const OUT = process.argv[2] || path.join(HERE, "wildfire_presentation.pptx");

// ---------- palette and theme ----------
const INK = "1F2328", GREY = "4B5563", MUTED = "6B7280", LIGHT = "F3F4F6", LINE = "E5E7EB";
const EMBER = "D9480F", RED = "B2182B", TEAL = "2B6F77", AMBER = "F2A541", NAVY = "0F3B57";
const SOFT_EMBER = "FDE8DC", SOFT_TEAL = "E3F0F1";
const THEME = {
  name: "Wildfire Ember",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: INK, lt1: "FFFFFF", dk2: GREY, lt2: LIGHT,
    accent1: EMBER, accent2: RED, accent3: TEAL, accent4: AMBER, accent5: MUTED, accent6: NAVY,
    hlink: TEAL, folHlink: MUTED,
  },
};
const W = 13.333, H = 7.5, MX = 0.6, CW = W - 2 * MX;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.title = "Explainable multisource machine learning for next-day wildfire prediction in Kazakhstan";
pres.author = "Samat Zharylkap, Nurbek Bolarbek";
pres.subject = "Research defense presentation";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };

pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: "FFFFFF" },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.42, w: CW, h: 0.7,
      fontFace: "Cambria", fontSize: 32, color: INK, margin: 0, valign: "middle", align: "left" },
      text: "" } },
    { placeholder: { options: { name: "msg", type: "body", x: MX, y: 1.12, w: CW, h: 0.55,
      fontFace: "Calibri", fontSize: 19, italic: true, color: EMBER, margin: 0, valign: "middle" },
      text: "" } },
    { text: { text: "Next-day wildfire prediction in Kazakhstan", options: { x: MX, y: 7.02, w: 6,
      h: 0.28, fontSize: 10, color: MUTED, margin: 0 } } },
  ],
  slideNumber: { x: W - MX - 0.6, y: 7.02, w: 0.6, h: 0.28, fontSize: 10, color: MUTED,
    align: "right", margin: 0 },
});
pres.defineSlideMaster({ title: "COVER", background: { color: "FFFFFF" }, objects: [] });

// ---------- helpers ----------
const iconCache = {};
async function icon(name, color) {
  const key = name + color;
  if (!iconCache[key]) {
    const svg = ReactDOMServer.renderToStaticMarkup(
      React.createElement(fa[name], { color: "#" + color, size: 256 }));
    const png = await sharp(Buffer.from(svg)).png().toBuffer();
    iconCache[key] = "image/png;base64," + png.toString("base64");
  }
  return iconCache[key];
}
const dims = {};
async function loadDims() {
  for (const f of fs.readdirSync(FIG).filter((f) => f.endsWith(".png"))) {
    const m = await sharp(path.join(FIG, f)).metadata();
    dims[f] = m.width / m.height;
  }
}
function figure(slide, file, x, y, maxW, maxH, name) {
  const r = dims[file];
  let w = maxW, h = maxW / r;
  if (h > maxH) { h = maxH; w = maxH * r; }
  const fx = x + (maxW - w) / 2;
  slide.addImage({ path: path.join(FIG, file), x: fx, y, w, h, altText: name, objectName: name });
  return { x: fx, y, w, h };
}
function content(title, msg, section) {
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  s.addText(msg, { placeholder: "msg" });
  return s;
}
function card(slide, x, y, w, h, fill = LIGHT, name = "card") {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill },
    line: { color: fill, width: 0 }, rectRadius: 0.08, objectName: name });
}
async function iconCircle(slide, name, x, y, d, bg, fg = "FFFFFF") {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: bg }, line: { color: bg },
    objectName: "icon circle" });
  const p = d * 0.26;
  slide.addImage({ data: await icon(name, fg), x: x + p, y: y + p, w: d - 2 * p, h: d - 2 * p,
    altText: name.replace(/^Fa/, "") + " icon" });
}
function text(slide, t, x, y, w, h, o = {}) {
  slide.addText(t, { x, y, w, h, isTextBox: true, margin: 0, valign: "top", fontSize: 15,
    color: INK, ...o });
}
function numberBadge(slide, n, x, y, d, bg) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: bg }, line: { color: bg } });
  slide.addText(String(n), { x, y, w: d, h: d, isTextBox: true, margin: 0, align: "center",
    valign: "middle", fontSize: 16, bold: true, color: "FFFFFF", fontFace: "Calibri" });
}

// Jupyter-style code cell with simple Python syntax colours and its real output.
const KW = new Set(["from", "import", "as", "for", "in", "def", "return", "if", "else", "with",
  "True", "False", "None", "and", "or", "not", "lambda"]);
const BUILTIN = new Set(["print", "len", "abs", "sum", "range", "dict", "list", "int", "float"]);
function highlight(code, fs) {
  const runs = [];
  const lines = code.split("\n");
  const re = /(#.*$)|(f?"(?:[^"\\]|\\.)*"|f?'(?:[^'\\]|\\.)*')|\b(\d+(?:\.\d+)?)\b|([A-Za-z_]\w*)|(\s+)|(.)/g;
  lines.forEach((line, li) => {
    const parts = [];
    let m;
    re.lastIndex = 0;
    while ((m = re.exec(line)) !== null) {
      const [tok, com, str, num, word] = m;
      let o = { color: INK };
      if (com) o = { color: "3D7B7B", italic: true };
      else if (str) o = { color: "BA2121" };
      else if (num) o = { color: "666666" };
      else if (word && KW.has(word)) o = { color: "008000", bold: true };
      else if (word && BUILTIN.has(word)) o = { color: "008000" };
      parts.push({ text: tok, options: { ...o, fontFace: "Consolas", fontSize: fs } });
      if (m[0] === "") re.lastIndex++;
    }
    if (!parts.length) parts.push({ text: " ", options: { fontFace: "Consolas", fontSize: fs } });
    if (li < lines.length - 1) parts[parts.length - 1].options.breakLine = true;
    runs.push(...parts);
  });
  return runs;
}
function codeCell(slide, x, y, w, n, code, output, fs = 11) {
  const label = 0.78, pad = 0.09;
  // shrink the font until the longest code or output line fits on one line (Consolas: 0.55 em)
  const longest = Math.max(...(code + "\n" + (output || "")).split("\n").map((l) => l.length));
  fs = Math.min(fs, Math.floor(((w - label - 0.22) * 72 / (longest * 0.56)) * 2) / 2);
  const lh = fs * 1.25 / 72;
  const nCode = code.split("\n").length;
  const hCode = nCode * lh + 2 * pad;
  slide.addText(`In [${n}]:`, { x, y: y + pad, w: label - 0.08, h: lh, isTextBox: true,
    margin: 0, fontFace: "Consolas", fontSize: fs - 1, color: "303F9F", align: "right" });
  slide.addShape(pres.shapes.RECTANGLE, { x: x + label, y, w: w - label, h: hCode,
    fill: { color: "F7F7F7" }, line: { color: "CFCFCF", width: 0.75 }, objectName: "code cell" });
  slide.addText(highlight(code, fs), { x: x + label + 0.1, y: y + pad, w: w - label - 0.2,
    h: nCode * lh, isTextBox: true, margin: 0, valign: "top", lineSpacing: fs * 1.25,
    objectName: "code" });
  let bottom = y + hCode;
  if (output) {
    const nOut = output.split("\n").length;
    const oy = bottom + 0.08;
    slide.addText(`Out[${n}]:`, { x, y: oy, w: label - 0.08, h: lh, isTextBox: true, margin: 0,
      fontFace: "Consolas", fontSize: fs - 1, color: "D84315", align: "right" });
    slide.addText(output, { x: x + label + 0.1, y: oy, w: w - label - 0.2, h: nOut * lh,
      isTextBox: true, margin: 0, valign: "top", fontFace: "Consolas", fontSize: fs,
      color: INK, lineSpacing: fs * 1.25, objectName: "code output" });
    bottom = oy + nOut * lh;
  }
  return bottom;
}

// Tables: dark header, light zebra rows, optional highlighted row.
function table(slide, header, rows, x, y, w, colW, o = {}) {
  const fs = o.fontSize || 13;
  const head = header.map((h) => ({ text: h, options: { bold: true, color: "FFFFFF",
    fill: { color: INK }, fontSize: fs, valign: "middle", align: "center" } }));
  const body = rows.map((r, i) => r.map((c, j) => ({ text: c, options: {
    fill: { color: o.highlight === i ? SOFT_EMBER : (i % 2 ? "FFFFFF" : LIGHT) },
    bold: o.highlight === i, fontSize: fs, color: INK, valign: "middle",
    align: j === 0 || (o.leftCols || []).includes(j) ? "left" : "center" } })));
  slide.addTable([head, ...body], { x, y, w, colW, rowH: o.rowH || 0.38,
    border: { type: "solid", pt: 0.75, color: LINE }, margin: [0.04, 0.08, 0.04, 0.08],
    fontFace: "Calibri", objectName: o.name || "table" });
}
function noteBox(slide, x, y, w, h, title, body, fill = SOFT_TEAL, titleColor = TEAL) {
  card(slide, x, y, w, h, fill, "note");
  slide.addText([
    { text: title, options: { bold: true, color: titleColor, breakLine: !title.endsWith(" ") } },
    { text: body, options: { color: INK } },
  ], { x: x + 0.2, y: y + 0.12, w: w - 0.4, h: h - 0.24, isTextBox: true, margin: 0,
    valign: "middle", fontSize: 15 });
}
const chartText = { catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
  dataLabelFontFace: "+mn-lt", legendFontFace: "+mn-lt", titleFontFace: "+mn-lt",
  catAxisLabelColor: GREY, valAxisLabelColor: GREY, catAxisLabelFontSize: 12,
  valAxisLabelFontSize: 11, dataLabelFontSize: 12, titleFontSize: 14, titleColor: INK,
  valGridLine: { color: "E5E7EB", size: 0.75 }, catGridLine: { style: "none" } };

(async () => {
  await loadDims();

  // ===== 1. Title =====
  pres.addSection({ title: "Title" });
  let s = pres.addSlide({ masterName: "COVER", sectionTitle: "Title" });
  s.addShape(pres.shapes.RECTANGLE, { x: 7.75, y: 0, w: W - 7.75, h: H, fill: { color: INK },
    line: { color: INK }, objectName: "map panel" });
  figure(s, "hero_map.png", 7.95, 1.55, W - 7.95 - 0.2, 3.9, "Forecast map of Kazakhstan");
  text(s, "Model forecast for 8 June 2023. Darker red means a higher chance of a new fire.",
    8.1, 5.75, 4.9, 0.6, { fontSize: 12, color: "D1D5DB", italic: true });
  text(s, "RESEARCH PROJECT DEFENSE", MX, 0.75, 6.8, 0.35,
    { fontSize: 13, bold: true, color: EMBER, charSpacing: 3 });
  s.addText("An Explainable Multisource Machine Learning Framework for Next-Day Wildfire "
    + "Prediction and Mapping in Kazakhstan", { x: MX, y: 1.2, w: 6.75, h: 2.4, isTextBox: true,
    margin: 0, fontFace: "Cambria", fontSize: 32, color: INK, valign: "top", objectName: "title" });
  text(s, "Which 5 km squares of Kazakhstan are most likely to have a new fire tomorrow?",
    MX, 3.75, 6.6, 0.75, { fontSize: 17, italic: true, color: GREY });
  s.addText([
    { text: "Students: ", options: { bold: true } },
    { text: "Samat Zharylkap, Nurbek Bolarbek", options: { breakLine: true } },
    { text: "Group: ", options: { bold: true } }, { text: "________", options: { breakLine: true } },
    { text: "Supervisor: ", options: { bold: true } }, { text: "________" },
  ], { x: MX, y: 4.8, w: 6.6, h: 1.1, isTextBox: true, margin: 0, fontSize: 15, color: INK,
    paraSpaceAfter: 4 });
  text(s, "School of Data Science and Artificial Intelligence, Astana IT University", MX, 6.35,
    6.8, 0.4, { fontSize: 13, color: MUTED });
  s.addNotes("Good day. Our work asks a practical question: every day, which 5 km squares of "
    + "Kazakhstan are most likely to have a new vegetation fire tomorrow? The map on the right is "
    + "a real forecast of our model for 8 June 2023.");

  // ===== 2-4. Problem statement =====
  pres.addSection({ title: "Problem statement" });
  s = content("Problem statement", "Fires start often in Kazakhstan, and a daily warning map could help people prepare",
    "Problem statement");
  const stats = [
    ["14", "forestry workers died in the Semei Ormany fire, Abay Region, June 2023", "FaFire", RED],
    ["≈16,000", "new fire starts per year seen by satellite in 2015–2021", "FaSatellite", EMBER],
    ["110,129", "squares of 5 × 5 km cover the country and must be checked every day", "FaMap", TEAL],
  ];
  for (let i = 0; i < 3; i++) {
    const x = MX + i * (CW + 0.3) / 3, w = (CW - 0.6) / 3;
    card(s, x, 2.0, w, 2.2);
    await iconCircle(s, stats[i][2], x + 0.3, 2.25, 0.62, stats[i][3]);
    text(s, stats[i][0], x + 1.1, 2.22, w - 1.3, 0.7, { fontSize: 36, bold: true,
      color: stats[i][3], fontFace: "Cambria", valign: "middle" });
    text(s, stats[i][1], x + 0.3, 3.1, w - 0.6, 0.95, { fontSize: 16, color: INK });
  }
  card(s, MX, 4.55, CW, 2.15, SOFT_EMBER, "aim");
  await iconCircle(s, "FaBullseye", MX + 0.3, 5.26, 0.72, EMBER);
  s.addText([
    { text: "Aim of the study", options: { bold: true, color: EMBER, fontSize: 18, breakLine: true } },
    { text: "To build and honestly test a machine-learning model that, every day, estimates the "
      + "chance of a new vegetation fire in each 5 km square of Kazakhstan for the next day, and "
      + "explains which factors make the chance high.", options: { fontSize: 16, color: INK } },
  ], { x: MX + 1.3, y: 4.7, w: CW - 1.6, h: 1.85, isTextBox: true, margin: 0, valign: "middle" });
  s.addNotes("Why does this matter? In June 2023 the Semei Ormany fire killed 14 forestry "
    + "workers. Satellites see about 16 thousand new fires every year, and the country is "
    + "110 thousand squares of 5 km. Nobody can watch all of them, so a daily map that shows "
    + "where to look first can help.");

  s = content("Problem statement: input/output",
    "The model turns seven kinds of data into a daily fire-chance map", "Problem statement");
  const inputs = [
    ["FaSatellite", "Fire detections", "satellite hot spots, 2015–2024"],
    ["FaCloudSun", "Weather", "heat, rain, wind, humidity, soil moisture"],
    ["FaLeaf", "Vegetation", "how green the plants are (NDVI)"],
    ["FaWheatAwn", "Land cover", "forest, grassland, shrubland, cropland"],
    ["FaMountain", "Terrain", "elevation, slope, aspect"],
    ["FaPeopleGroup", "People", "population, distance to settlements"],
    ["FaCalendarDays", "Season", "month of the year"],
  ];
  text(s, "INPUT", MX, 1.9, 4.6, 0.3, { fontSize: 13, bold: true, color: MUTED, charSpacing: 2 });
  for (let i = 0; i < inputs.length; i++) {
    const y = 2.25 + i * 0.64;
    await iconCircle(s, inputs[i][0], MX, y, 0.5, i === 0 ? RED : TEAL);
    s.addText([
      { text: inputs[i][1] + "  ", options: { bold: true, color: INK } },
      { text: inputs[i][2], options: { color: GREY } },
    ], { x: MX + 0.65, y, w: 4.25, h: 0.5, isTextBox: true, margin: 0, valign: "middle",
      fontSize: 14 });
  }
  s.addShape(pres.shapes.RIGHT_ARROW, { x: 5.6, y: 3.95, w: 0.7, h: 0.6, fill: { color: "D1D5DB" },
    line: { color: "D1D5DB" } });
  card(s, 6.45, 2.55, 2.7, 3.4, INK, "model");
  await iconCircle(s, "FaBrain", 7.4, 2.85, 0.8, EMBER);
  text(s, "Machine-learning model", 6.6, 3.8, 2.4, 0.7, { fontSize: 17, bold: true,
    color: "FFFFFF", align: "center", valign: "middle" });
  text(s, "learns from 2015–2021 which conditions came before new fires", 6.65, 4.55, 2.3, 1.2,
    { fontSize: 13, color: "D1D5DB", align: "center" });
  s.addShape(pres.shapes.RIGHT_ARROW, { x: 9.3, y: 3.95, w: 0.7, h: 0.6, fill: { color: "D1D5DB" },
    line: { color: "D1D5DB" } });
  text(s, "OUTPUT", 10.15, 1.9, 2.6, 0.3, { fontSize: 13, bold: true, color: MUTED, charSpacing: 2 });
  card(s, 10.15, 2.25, W - MX - 10.15, 4.45, SOFT_EMBER, "output");
  figure(s, "hero_map.png", 10.25, 2.4, W - MX - 10.35, 1.6, "Daily forecast map");
  text(s, "For every 5 km square and every day: the chance of a new fire tomorrow", 10.35, 4.15,
    W - MX - 10.55, 1.2, { fontSize: 14, bold: true, color: INK });
  text(s, "Shown as a daily map with four warning levels", 10.35, 5.45, W - MX - 10.55, 0.9,
    { fontSize: 14, color: GREY });
  s.addNotes("Input: satellite fire detections and six groups of predictors. Output: for every "
    + "5 km square and every day, the probability that a new fire starts there tomorrow. We show "
    + "it as a daily map with four warning levels.");

  s = content("Problem statement: research questions", "Three questions guided the study",
    "Problem statement");
  const rqs = [
    ["Does combining weather, vegetation, terrain, land-cover and human data predict next-day fires better than seasonal fire frequency and a weather-only model?",
      "Is more data better than simple rules?"],
    ["How well do the models work on future years and on geographically separate regions of Kazakhstan?",
      "Does it still work next year and in a new place?"],
    ["Are the predicted probabilities well calibrated, and which factors explain the outputs in different regions and land covers?",
      "Can we trust the numbers, and why does the model say “high risk”?"],
  ];
  for (let i = 0; i < 3; i++) {
    const w = (CW - 0.6) / 3, x = MX + i * (w + 0.3);
    card(s, x, 2.0, w, 4.7);
    numberBadge(s, i + 1, x + 0.3, 2.25, 0.6, EMBER);
    text(s, "Research question " + (i + 1), x + 1.05, 2.3, w - 1.2, 0.5,
      { fontSize: 16, bold: true, color: EMBER, valign: "middle" });
    text(s, rqs[i][0], x + 0.3, 3.05, w - 0.6, 2.2, { fontSize: 17 });
    card(s, x + 0.2, 5.35, w - 0.4, 1.15, "FFFFFF", "plain version");
    s.addText([{ text: "In simple words: ", options: { bold: true, color: TEAL } },
      { text: rqs[i][1], options: { italic: true, color: INK } }],
      { x: x + 0.35, y: 5.45, w: w - 0.7, h: 0.95, isTextBox: true, margin: 0, valign: "middle",
        fontSize: 16 });
  }
  s.addNotes("We asked three questions. First: does more data beat simple rules? Second: does "
    + "the model still work in a later year and in a region it has never seen? Third: can we "
    + "trust its probabilities, and what makes it say high risk?");

  // ===== 5-9. Input data =====
  pres.addSection({ title: "Input data" });
  s = content("Collection, analysis and processing of input data",
    "We joined seven open data sources on one 5 km grid", "Input data");
  table(s, ["Data", "What it tells the model", "Source", "Detail"], [
    ["Fire detections", "Where and when a new fire was seen", "NASA FIRMS, VIIRS (Suomi-NPP)", "375 m, 2015–2024"],
    ["Weather", "Heat, rain, wind, humidity, soil moisture", "ERA5 reanalysis (Open-Meteo)", "0.25°, daily, 7 days old"],
    ["Vegetation", "How green the plants are (NDVI)", "NOAA CDR NDVI", "0.05°, weekly"],
    ["Land cover", "Share of forest, grassland, shrubland, cropland", "MODIS land cover", "yearly"],
    ["Terrain", "Elevation, slope and aspect", "SRTM", "90 m"],
    ["People", "Population density, distance to settlements", "WorldPop 2010, Natural Earth", "1 km, points"],
    ["Season", "Month of the year", "Calendar", "daily"],
  ], MX, 2.0, CW, [2.0, 4.1, 3.6, 2.43], { leftCols: [1, 2], rowH: 0.5, fontSize: 14 });
  noteBox(s, MX, 6.15, CW, 0.62, "Rule: ",
    "every input is used only if it was available before the forecast day, so the test is like real use.");
  s.addNotes("All data are public. The important rule: the model may only use information that "
    + "was really available before the forecast day. For weather this means data from 7 days "
    + "earlier, because the archive appears with a delay of about 5 days.");

  s = content("Collection, analysis and processing of input data",
    "Raw input: one row for each hot spot seen by the satellite", "Input data");
  text(s, "Raw VIIRS detections (June 2023, first rows)", MX, 1.95, 6.6, 0.35,
    { fontSize: 14, bold: true, color: GREY });
  table(s, ["Time (UTC)", "Latitude", "Longitude", "Confidence", "Satellite"], TABLES.raw,
    MX, 2.35, 6.6, [1.75, 1.05, 1.15, 1.25, 1.4], { fontSize: 13, rowH: 0.4 });
  const bullets = [
    "The VIIRS sensor passes over Kazakhstan about twice a day and marks hot spots of 375 m.",
    "Low-confidence points are removed; nominal and high confidence are kept.",
    "One fire can create hundreds of points over several days, so points must be grouped.",
  ];
  s.addText(bullets.map((b, i) => ({ text: b, options: { bullet: true,
    breakLine: i < bullets.length - 1 } })), { x: MX, y: 5.0, w: 6.6, h: 1.8, isTextBox: true,
    margin: 0, fontSize: 15, color: INK, paraSpaceAfter: 6, valign: "top" });
  const rawEnd = codeCell(s, 7.55, 2.35, W - MX - 7.55,
    1, 'import pandas as pd\n\nraw = pd.read_parquet("detections_2023.parquet")\n'
    + 'n = len(raw)\nprint(f"{n:,} VIIRS fire detections in 2023")',
    CELLS.raw.split("\n")[0]);
  card(s, 7.55, rawEnd + 0.45, W - MX - 7.55, 6.8 - rawEnd - 0.45, SOFT_EMBER, "raw size");
  s.addText([
    { text: "Size of the raw data", options: { bold: true, color: EMBER, breakLine: true } },
    { text: "1,140,564 nominal and high-confidence hot spots in 2015–2024", options: { bullet: true, breakLine: true } },
    { text: "65,413 hot spots in 2023 alone, before cleaning", options: { bullet: true, breakLine: true } },
    { text: "Each row: time, place and confidence of one hot spot", options: { bullet: true } },
  ], { x: 7.8, y: rawEnd + 0.6, w: W - MX - 8.05, h: 6.8 - rawEnd - 0.75, isTextBox: true,
    margin: 0, valign: "middle", fontSize: 16, color: INK, paraSpaceAfter: 6 });
  s.addNotes("This is how the raw data look: one row per hot spot, with time, coordinates and "
    + "confidence. A single fire produces many such points, so the next step groups them.");

  s = content("Collection, analysis and processing of input data",
    "Many hot spots are joined into one fire, and only its first day is the target", "Input data");
  const steps = [
    ["FaFilter", "Clean", "Keep nominal and high confidence; remove industrial heat sources such as gas flares"],
    ["FaLink", "Link", "Points closer than 2 km and 48 hours belong to the same fire event"],
    ["FaFlag", "First day", "The first detection of each event is a “new fire start”"],
    ["FaTableCells", "Grid", "Put starts on the 5 km grid: each square and day gets 1 (start) or 0"],
  ];
  for (let i = 0; i < 4; i++) {
    const w = (CW - 0.9) / 4, x = MX + i * (w + 0.3);
    card(s, x, 2.0, w, 2.15);
    await iconCircle(s, steps[i][0], x + 0.25, 2.2, 0.55, i === 2 ? EMBER : TEAL);
    text(s, `${i + 1}. ${steps[i][1]}`, x + 0.95, 2.22, w - 1.05, 0.5,
      { fontSize: 17, bold: true, valign: "middle" });
    text(s, steps[i][2], x + 0.25, 2.9, w - 0.5, 1.2, { fontSize: 14, color: GREY });
  }
  codeCell(s, MX, 4.5, 7.4, 2,
    "# events were built with link_events(detections, radius_m=2000, window_hours=48)\n"
    + 'events = pd.read_parquet("events_through_2024.parquet")\n'
    + "in_years = events.day.dt.year.between(2015, 2024)\n"
    + 'print(f"{in_years.sum():,} detections (2015-2024)")\n'
    + 'print(f"{(events.is_first & in_years).sum():,} separate fire events")',
    CELLS.events, 10.5);
  card(s, 8.4, 4.5, W - MX - 8.4, 1.95, SOFT_EMBER, "labels");
  text(s, "139,326", 8.6, 4.65, W - MX - 8.8, 0.8, { fontSize: 38, bold: true, color: EMBER,
    fontFace: "Cambria" });
  text(s, "new fire starts used as targets (2015–2024), after removing industrial sites and squares that were already burning",
    8.6, 5.45, W - MX - 8.8, 1.2, { fontSize: 14 });
  s.addNotes("Four steps: clean the points, link points that are close in space and time into "
    + "one fire, keep only the first day of each fire, and place it on the 5 km grid. The code "
    + "shows that 1.14 million detections become about 152 thousand fire events. After cleaning, "
    + "139,326 new fire starts are our targets.");

  s = content("Collection, analysis and processing of input data",
    "After processing: one row per square per day, with 26 predictors", "Input data");
  text(s, "Processed dataset (real rows, June 2023)", MX, 1.95, CW, 0.35,
    { fontSize: 14, bold: true, color: GREY });
  table(s, ["Date", "Land cover", "Max temp. 7 days before (°C)", "Rain in 14 days (mm)", "NDVI",
    "Elevation (m)", "Population density", "New fire?"], TABLES.features.map((r) =>
    [...r.slice(0, 7), r[7] === "1" ? "Yes (1)" : "No (0)"]), MX, 2.35, CW,
    [1.4, 1.4, 1.9, 1.7, 1.0, 1.45, 1.6, 1.68], { fontSize: 13, rowH: 0.42 });
  const groups = [["Daily weather", 6], ["7/14-day weather", 4], ["Vegetation", 3],
    ["Land cover", 5], ["Terrain", 4], ["People", 2], ["Season", 2]];
  text(s, "26 predictors in 7 groups", MX, 5.25, CW, 0.35, { fontSize: 15, bold: true });
  for (let i = 0; i < groups.length; i++) {
    const w = (CW - 6 * 0.2) / 7, x = MX + i * (w + 0.2);
    card(s, x, 5.7, w, 1.0, i < 2 ? SOFT_TEAL : SOFT_EMBER, "group");
    text(s, String(groups[i][1]), x, 5.75, w, 0.5, { fontSize: 24, bold: true,
      color: i < 2 ? TEAL : EMBER, align: "center", fontFace: "Cambria" });
    text(s, groups[i][0], x + 0.05, 6.25, w - 0.1, 0.4, { fontSize: 13, align: "center" });
  }
  s.addNotes("After processing, every row is one 5 km square on one day. The columns are the "
    + "predictors, and the last column says whether a new fire started. There are 26 predictors "
    + "in seven groups.");

  s = content("Collection, analysis and processing of input data",
    "New fires are rare: about 2 in every 10,000 square-days", "Input data");
  const years = ["2015", "2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024"];
  const starts = [15326, 13050, 21819, 14844, 18773, 16679, 12951, 10134, 9563, 6187];
  // thousands, so the axis reads "25k" in any Windows locale
  const part = (from, to) => starts.map((v, i) => (i >= from && i <= to ? v / 1000 : 0));
  s.addChart(pres.charts.BAR, [
    { name: "Training (2015–2021)", labels: years, values: part(0, 6) },
    { name: "Calibration (2022)", labels: years, values: part(7, 7) },
    { name: "Test (2023–2024)", labels: years, values: part(8, 9) },
  ], { x: MX, y: 1.95, w: 6.2, h: 4.85, barDir: "col", barGrouping: "stacked", barGapWidthPct: 45,
    chartColors: [AMBER, TEAL, RED], showLegend: true, legendPos: "b", legendFontSize: 12,
    showTitle: true, title: "New fire starts per year", valAxisLabelFormatCode: '0"k"',
    ...chartText, objectName: "fire starts per year chart" });
  const smpEnd = codeCell(s, 7.05, 2.05, W - MX - 7.05, 3,
    'test = pd.read_parquet("2023_evaluation.parquet")\n'
    + 'print(f"{len(test):,} sampled rows in 2023")\n'
    + 'print(f"{test.label.sum():,} new fire starts (all kept)")\n'
    + 'print(f"{test.weight.sum():,.0f} cell-days represented")', CELLS.sampling, 11);
  noteBox(s, 7.05, smpEnd + 0.4, W - MX - 7.05, 6.8 - smpEnd - 0.4, "How we handle rare fires",
    "We keep every fire and only a sample of the no-fire squares. Each sampled row gets a weight, "
    + "so 189,885 rows stand for all 39.8 million square-days of 2023. Fire numbers also fell over "
    + "time, so the test years are harder.", SOFT_EMBER, EMBER);
  s.addNotes("New fires are very rare: about two in every ten thousand square-days. We keep all "
    + "fires and sample the non-fire rows with weights, so the data stay small but still "
    + "represent the whole country. The chart also shows that fires became less frequent, which "
    + "makes the test years harder.");

  // ===== 10-13. Models and methods =====
  pres.addSection({ title: "Models and methods" });
  s = content("Models and methods for solving the problem",
    "We compared four machine-learning models with two simple references", "Models and methods");
  const models = [
    ["FaChartLine", "Logistic regression", "Adds up the effect of each input in a straight-line way. Simple and easy to read.", TEAL, "ML model"],
    ["FaTree", "Random Forest", "Hundreds of decision trees answer separately, and their answers are averaged.", TEAL, "ML model"],
    ["FaLayerGroup", "XGBoost", "Builds small trees one after another; each new tree fixes the mistakes of the previous ones.", EMBER, "ML model · selected"],
    ["FaCodeBranch", "CatBoost", "Another boosting method that grows trees in a different way.", TEAL, "ML model"],
    ["FaCalendarDays", "Seasonal frequency", "How often fires started in this month and land cover in the past years.", MUTED, "Reference"],
    ["FaCloudSun", "Weather-only model", "Logistic regression that sees only the weather inputs.", MUTED, "Reference"],
  ];
  for (let i = 0; i < 6; i++) {
    const w = (CW - 0.6) / 3, h = 2.1, x = MX + (i % 3) * (w + 0.3), y = 2.05 + Math.floor(i / 3) * (h + 0.35);
    card(s, x, y, w, h, i === 2 ? SOFT_EMBER : LIGHT);
    await iconCircle(s, models[i][0], x + 0.25, y + 0.25, 0.6, models[i][3]);
    text(s, models[i][1], x + 1.0, y + 0.22, w - 1.15, 0.38, { fontSize: 17, bold: true });
    text(s, models[i][4], x + 1.0, y + 0.58, w - 1.15, 0.3, { fontSize: 12, bold: true,
      color: models[i][3] });
    text(s, models[i][2], x + 0.25, y + 1.05, w - 0.5, 0.95, { fontSize: 15, color: GREY });
  }
  s.addNotes("We compared four machine-learning models. Logistic regression is the simplest. "
    + "Random Forest averages many trees. XGBoost and CatBoost are boosting methods: each new tree "
    + "corrects the errors of the previous ones. Two simple references show what we can do "
    + "without machine learning: past fire frequency by month and land cover, and a weather-only "
    + "model.");

  s = content("Models and methods for solving the problem",
    "Strict testing: the model never saw the test years or the test regions", "Models and methods");
  const tl = [[2015, 2021, "Training", AMBER], [2022, 2022, "Calibration", TEAL], [2023, 2024, "Test (untouched)", RED]];
  const yw = CW / 10;
  for (const [a, b, label, col] of tl) {
    const x = MX + (a - 2015) * yw, w = (b - a + 1) * yw - 0.06;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 2.05, w, h: 0.62, fill: { color: col },
      line: { color: col }, rectRadius: 0.06, objectName: label });
    text(s, label, x, 2.05, w, 0.62, { fontSize: 15, bold: true, color: "FFFFFF",
      align: "center", valign: "middle" });
  }
  for (let yy = 2015; yy <= 2024; yy++) {
    text(s, String(yy), MX + (yy - 2015) * yw, 2.72, yw - 0.06, 0.3, { fontSize: 12,
      color: GREY, align: "center" });
  }
  text(s, "Model choice: rolling validation, train on earlier years and check on 2019, 2020 and 2021",
    MX, 3.05, 7.0 * yw, 0.35, { fontSize: 13, italic: true, color: GREY });
  const tests = [
    ["FaClock", "Test in time", "Train on the past and predict 2023–2024, which were never used before the final test."],
    ["FaEarthAsia", "Test in space", "Hide whole 100 km blocks of the country (5 groups), train on the rest and predict the hidden blocks."],
    ["FaScaleBalanced", "Fair inputs", "Weather is taken from 7 days before the forecast, because the weather archive arrives about 5 days late."],
  ];
  for (let i = 0; i < 3; i++) {
    const w = (CW - 0.6) / 3, x = MX + i * (w + 0.3);
    card(s, x, 3.75, w, 2.75);
    await iconCircle(s, tests[i][0], x + 0.3, 4.0, 0.62, i === 1 ? EMBER : TEAL);
    text(s, tests[i][1], x + 1.1, 4.05, w - 1.25, 0.55, { fontSize: 18, bold: true,
      valign: "middle" });
    text(s, tests[i][2], x + 0.3, 4.85, w - 0.6, 1.5, { fontSize: 16, color: GREY });
  }
  s.addNotes("The years 2015 to 2021 were used for training and model choice, 2022 for "
    + "calibrating the probabilities, and 2023 to 2024 only for the final test. We also hid "
    + "whole 100 km blocks to see if the model works in places it has never seen.");

  s = content("Models and methods for solving the problem",
    "How we judge the forecast, in simple words", "Models and methods");
  const measures = [
    ["FaListOl", "Average precision (AP)", "Sort all squares from most to least risky. AP is high when real fires appear near the top of the list.", "Random list: 0.0002, because fires are so rare"],
    ["FaMagnifyingGlass", "Top-5% capture", "Each day, flag the 5% of the country with the highest scores. What share of new fires falls inside?", "Random choice: 5%"],
    ["FaGaugeHigh", "Calibration", "If the model says 1% for 1,000 squares, about 10 of them should really have a fire.", "Checked with reliability diagrams"],
    ["FaDiagramProject", "SHAP explanations", "Shows how much each input pushed a forecast up or down.", "Explains, but does not prove causes"],
  ];
  for (let i = 0; i < 4; i++) {
    const w = (CW - 0.3) / 2, h = 1.95, x = MX + (i % 2) * (w + 0.3), y = 2.0 + Math.floor(i / 2) * (h + 0.25);
    card(s, x, y, w, h);
    await iconCircle(s, measures[i][0], x + 0.3, y + 0.3, 0.62, i === 0 ? EMBER : TEAL);
    text(s, measures[i][1], x + 1.1, y + 0.3, w - 1.3, 0.55, { fontSize: 18, bold: true,
      valign: "middle" });
    text(s, measures[i][2], x + 1.1, y + 0.85, w - 1.3, 0.75, { fontSize: 15, color: INK });
    text(s, measures[i][3], x + 1.1, y + 1.6, w - 1.3, 0.35, { fontSize: 13, italic: true,
      color: i === 0 ? EMBER : TEAL });
  }
  text(s, "We also give 95% confidence intervals from 1,000 bootstrap resamples (blocks of 100 km × 30 days). They show how sure we can be about each number.",
    MX, 6.38, CW, 0.4, { fontSize: 14, color: GREY });
  s.addNotes("Accuracy is useless here: a model that always says 'no fire' is 99.98% accurate. "
    + "So we use average precision, which checks if real fires are at the top of the ranked "
    + "list, and the share of fires inside the daily top 5% of the area. We also check if the "
    + "probabilities are honest, and use SHAP to explain the model.");

  s = content("Models and methods for solving the problem",
    "Training XGBoost and calibrating its probabilities (Python)", "Models and methods");
  const tuneOut = CELLS.tuning.split("\n").filter((l) => !l.startsWith("validation")).join("\n");
  const hw = (CW - 0.4) / 2;
  text(s, "1. Tune and train the model", MX, 1.95, hw, 0.35, { fontSize: 15, bold: true, color: TEAL });
  const trainEnd = codeCell(s, MX, 2.4, hw, 4,
    "from xgboost import XGBClassifier\n\n"
    + "# best of 5 Optuna trials, rolling validation 2019-2021\n"
    + "best = study.best_params\n"
    + 'model = XGBClassifier(**best, objective="binary:logistic",\n'
    + '                      tree_method="hist")\n'
    + "model.fit(X_train, y_train, sample_weight=w_train)\n"
    + "for k, v in best.items():\n    print(k, v)", tuneOut, 11);
  noteBox(s, MX, trainEnd + 0.3, hw, 6.8 - trainEnd - 0.3, "In simple words: ",
    "314 small trees, each at most 5 questions deep; every new tree corrects only a small part "
    + "(0.06) of the remaining error.", SOFT_TEAL, TEAL);
  text(s, "2. Calibrate on 2022 and fix the alert threshold", MX + hw + 0.4, 1.95, hw, 0.35,
    { fontSize: 15, bold: true, color: TEAL });
  const yb = codeCell(s, MX + hw + 0.4, 2.4, hw, 5,
    "from wildfire_kz.calibration import fit_sigmoid\n\n"
    + "# only 2022 is used here, never the test years\n"
    + "calibration, threshold = fit_sigmoid(\n"
    + "    data_2022, model_scores_2022, calibration_year=2022)\n"
    + 'print(f"alert threshold (2022): {threshold:.3f}")', CELLS.calibration.split("\n")[0], 11);
  noteBox(s, MX + hw + 0.4, yb + 0.4, hw, 6.8 - yb - 0.4, "What calibration does",
    "It turns the raw model score into a probability that matches how often fires really "
    + "happened in 2022. The same year also fixes the alert threshold (0.047) and the four map "
    + "warning levels. The test years 2023–2024 are not used in this step.");
  s.addNotes("Here is the main code. We tuned XGBoost on the validation years and trained it with "
    + "the sample weights. Then we used only 2022 to calibrate the probabilities and to fix the "
    + "alert threshold. The test years were not touched in this step.");

  // ===== 14-22. Results =====
  pres.addSection({ title: "Results" });
  s = content("Results", "XGBoost was the best model: about 104 times better than a random ranking",
    "Results");
  table(s, ["Model", "AP", "× random", "ROC-AUC", "Top 5%"], [
    ["XGBoost", "0.0204", "104", "0.924", "55.6%"],
    ["CatBoost", "0.0175", "89", "0.908", "50.2%"],
    ["Random Forest", "0.0070", "36", "0.879", "49.2%"],
    ["Logistic regression", "0.0010", "5", "0.793", "25.6%"],
    ["Weather-only (ref.)", "0.0004", "2", "0.662", "8.4%"],
    ["Seasonal frequency (ref.)", "0.0006", "3", "0.731", "14.3%"],
  ], MX, 2.0, 6.5, [2.45, 0.95, 1.0, 1.05, 1.05], { highlight: 0, rowH: 0.48, fontSize: 14 });
  text(s, "Test years 2023–2024. AP of a random ranking = fire rate = 0.0002.", MX, 5.45, 6.5,
    0.35, { fontSize: 12, italic: true, color: MUTED });
  noteBox(s, MX, 5.9, 6.5, 0.85, "Significant: ",
    "XGBoost beat both references (95% CI). XGBoost vs CatBoost: no clear difference.");
  const capOrder = [["Weather-only", 8.4], ["Seasonal", 14.3], ["Logistic", 25.6],
    ["Random Forest", 49.2], ["CatBoost", 50.2], ["XGBoost", 55.6]];
  // tenths of a percent with a literal point: "55.6%" in any Windows locale
  s.addChart(pres.charts.BAR, [{ name: "Top 5% capture", labels: capOrder.map((c) => c[0]),
    values: capOrder.map((c) => Math.round(c[1] * 10)) }], { x: 7.45, y: 1.95, w: W - MX - 7.45,
    h: 4.85, barDir: "bar", chartColors: ["9CA3AF", "9CA3AF", "9CA3AF", "9CA3AF", "9CA3AF", EMBER],
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: '#0"."0"%"',
    dataLabelColor: INK, valAxisHidden: true, valAxisMaxVal: 700, valAxisMinVal: 0,
    showLegend: false, showTitle: true, title: "New fires inside the daily top 5% of the area",
    barGapWidthPct: 40, ...chartText, valGridLine: { style: "none" },
    objectName: "top 5 percent capture chart" });
  s.addNotes("The table shows the test results. XGBoost has the highest average precision, 104 "
    + "times the random level. The chart is easier: if you check the 5% riskiest area each day, "
    + "XGBoost finds 55.6% of new fires, the seasonal rule only 14.3%, weather alone 8.4%.");

  s = content("Results", "Checking 5% of the area each day finds 55.6% of the new fires", "Results");
  const f1 = figure(s, "fig_performance.png", MX, 2.0, 6.2, 3.2, "Precision-recall and capture curves");
  text(s, "(a) Precision–recall curves; (b) share of new fires captured as more of the daily area is flagged.",
    MX, f1.y + f1.h + 0.08, 6.2, 0.5, { fontSize: 12, italic: true, color: MUTED });
  const capStats = [["55.6%", "of new fires in the top 5% of daily area", EMBER],
    ["68.0%", "in the top 10%", TEAL], ["82.2%", "in the top 20%", TEAL]];
  for (let i = 0; i < 3; i++) {
    const w = (6.2 - 0.4) / 3, x = MX + i * (w + 0.2);
    card(s, x, 5.55, w, 1.25, i === 0 ? SOFT_EMBER : LIGHT);
    text(s, capStats[i][0], x + 0.15, 5.62, w - 0.3, 0.55, { fontSize: 26, bold: true,
      color: capStats[i][2], fontFace: "Cambria" });
    text(s, capStats[i][1], x + 0.15, 6.17, w - 0.3, 0.55, { fontSize: 12, color: GREY });
  }
  const cx = 7.05, cw = W - MX - cx;
  const cy = codeCell(s, cx, 2.0, cw, 6,
    "from sklearn import metrics\n"
    + "rate = (y * w).sum() / w.sum()\n"
    + "ap = metrics.average_precision_score(y, p, sample_weight=w)\n"
    + "auc = metrics.roc_auc_score(y, p, sample_weight=w)\n"
    + 'print(f"Fire rate (no-skill AP): {rate:.2e}")\n'
    + 'print(f"AP      = {ap:.4f}  ({ap / rate:.0f} x no-skill)")\n'
    + 'print(f"ROC-AUC = {auc:.3f}")', CELLS.evaluate, 11);
  codeCell(s, cx, cy + 0.3, cw, 7,
    "from wildfire_kz.evaluation import top_capture\n"
    + "table = top_capture(test, p, [0.05, 0.10, 0.20])\n"
    + "for _, r in table.iterrows():\n"
    + '    print(f"top {r.nominal_fraction:.0%} of area -> "\n'
    + '          f"{r.capture_rate:.1%} of new fires")', CELLS.capture, 11);
  s.addNotes("Panel a shows that the boosting models keep higher precision at every level of "
    + "recall. Panel b is the practical view. The code on the right computes these numbers on "
    + "the real test data: AP 0.0204, ROC-AUC 0.924, and 55.6% of new fires in the top 5% of the "
    + "daily area.");

  s = content("Results", "Our numbers look smaller than in other studies because we test at the real fire rate",
    "Results");
  const big = [
    ["0.020", "AP at the real fire rate", "Our test: only 2 of 10,000 square-days have a fire", RED, "FDE2E4"],
    ["0.925", "AP of the same predictions at a 50/50 balance", "Re-weighted so that half of the cases are fires, as in many studies; nothing is retrained", TEAL, SOFT_TEAL],
  ];
  for (let i = 0; i < 2; i++) {
    const w = (CW - 0.3) / 2, x = MX + i * (w + 0.3);
    card(s, x, 2.0, w, 2.55, big[i][4]);
    text(s, big[i][0], x + 0.35, 2.15, w - 0.7, 1.0, { fontSize: 54, bold: true, color: big[i][3],
      fontFace: "Cambria" });
    text(s, big[i][1], x + 0.35, 3.15, w - 0.7, 0.45, { fontSize: 18, bold: true });
    text(s, big[i][2], x + 0.35, 3.6, w - 0.7, 0.8, { fontSize: 15, color: GREY });
  }
  const cmp = [
    ["FaScaleBalanced", "Studies in Morocco, Türkiye and Algeria report AUC 0.95–0.99, but they test on fire and non-fire points, often in equal numbers."],
    ["FaChartLine", "ROC-AUC does not depend on this balance. Ours is 0.92, close to theirs."],
    ["FaMap", "National hazard maps of Kazakhstan report AUC 0.79–0.80 for a different, static target."],
  ];
  for (let i = 0; i < 3; i++) {
    const y = 4.85 + i * 0.65;
    await iconCircle(s, cmp[i][0], MX, y, 0.48, i === 1 ? EMBER : MUTED);
    text(s, cmp[i][1], MX + 0.65, y, CW - 0.65, 0.48, { fontSize: 15, valign: "middle" });
  }
  s.addNotes("A common question: why is our AP only 0.02 when other papers report 0.95? Most "
    + "studies test on balanced data, half fires and half non-fires. Our test keeps the real "
    + "rate, two fires in ten thousand. If we re-weight our same predictions to a 50/50 balance, "
    + "AP becomes 0.925. So the difference is the test design, not a weak model.");

  s = content("Results", "Terrain, land cover, people and season matter most; week-old weather did not help",
    "Results");
  const fa1 = figure(s, "fig_ablation.png", MX, 1.95, 6.6, 3.55, "Predictor group ablation");
  text(s, "Each bar: how much AP is lost when one group of inputs is removed (95% CI). Red = clear loss.",
    MX, fa1.y + fa1.h + 0.05, 6.6, 0.4, { fontSize: 12, italic: true, color: MUTED });
  const take = [
    ["FaMountain", "Terrain gave the largest loss (0.0153 of 0.0234 AP)", "Land cover, people and season also mattered."],
    ["FaPeopleGroup", "Most steppe fires are started by people", "Field and pasture burning depends on place, land use and the calendar."],
    ["FaCloudSun", "Weather from 7 days before did not help", "It cannot see short hot, dry spells that dry the fuel."],
  ];
  for (let i = 0; i < 3; i++) {
    const y = 2.0 + i * 1.15;
    await iconCircle(s, take[i][0], 7.5, y, 0.6, i === 2 ? MUTED : EMBER);
    s.addText([{ text: take[i][1], options: { bold: true, breakLine: true } },
      { text: take[i][2], options: { color: GREY } }], { x: 8.25, y: y - 0.05, w: W - MX - 8.25,
      h: 1.0, isTextBox: true, margin: 0, valign: "top", fontSize: 15 });
  }
  noteBox(s, MX, 5.85, CW, 0.9, "Research question 1: ",
    "yes, with a caveat. More data beat both references, but the gain came from terrain, land cover, people and season.",
    SOFT_EMBER, EMBER);
  s.addNotes("We removed one group of inputs at a time and measured the loss. Terrain, land "
    + "cover, people and season caused clear losses. Weather and vegetation, as we could use "
    + "them, did not help. This answers our first question: yes, combining data helps, mainly "
    + "through these four groups.");

  s = content("Results", "The model works well in later years, but much weaker in regions it has never seen",
    "Results");
  table(s, ["Test", "AP", "× random", "ROC-AUC"], [
    ["Future year 2023", "0.0192", "80", "0.924"],
    ["Future year 2024", "0.0277", "181", "0.923"],
    ["Unseen regions (mean of 5)", "0.0039", "15", "0.866"],
  ], MX, 2.0, 6.4, [2.9, 1.1, 1.2, 1.2], { highlight: 2, rowH: 0.5, fontSize: 14 });
  text(s, "Unseen regions: whole 100 km blocks hidden during training.", MX, 4.1, 6.4, 0.35,
    { fontSize: 12, italic: true, color: MUTED });
  noteBox(s, MX, 4.6, 6.4, 1.75, "Research question 2",
    "Mixed answer: good for future years in the same area, but in new regions the model keeps "
    + "only part of its ranking skill. The strongest inputs describe places where fires repeat, "
    + "and this knowledge is local.", SOFT_EMBER, EMBER);
  figure(s, "fig_regions.png", 7.35, 1.95, W - MX - 7.35, 4.4, "AP by region");
  text(s, "AP by region, 2023–2024: best in Atyrau and Aktobe, weakest in the northern grain regions.",
    7.35, 6.4, W - MX - 7.35, 0.45, { fontSize: 12, italic: true, color: MUTED });
  s.addNotes("In later years the model was stable. In hidden regions, AP fell from 104 to 15 "
    + "times the random level. The chart shows big differences between regions. In the northern "
    + "grain regions many small cropland fires are hard to predict.");

  s = content("Results", "The probabilities rank squares well, but they are 1.2–1.8 times too high",
    "Results");
  const fr = figure(s, "fig_reliability.png", MX, 1.95, 5.2, 4.45, "Reliability diagram");
  text(s, "Points under the dotted line mean that the model predicted more fires than happened.",
    MX, fr.y + fr.h + 0.05, 5.4, 0.45, { fontSize: 12, italic: true, color: MUTED });
  text(s, "Four warning levels fixed on 2022, checked on 2023–2024", 6.3, 1.95, W - MX - 6.3, 0.35,
    { fontSize: 15, bold: true, color: GREY });
  table(s, ["Warning level", "Share of area", "Share of new fires", "Predicted / observed"], [
    ["1 (lowest)", "49.7%", "2.3%", "1.33"],
    ["2", "31.6%", "10.8%", "1.82"],
    ["3", "13.8%", "21.1%", "1.28"],
    ["4 (highest)", "5.0%", "65.8%", "1.32"],
  ], 6.3, 2.4, W - MX - 6.3, [1.55, 1.45, 1.75, 1.68], { highlight: 3, rowH: 0.46, fontSize: 14 });
  noteBox(s, 6.3, 4.95, W - MX - 6.3, 1.8, "Why too high?",
    "Fires became less frequent: 2.5 in 10,000 in 2022 (calibration year) but 1.5 in 10,000 in "
    + "2024. So the warning levels are useful as an order of risk, not as exact chances.");
  s.addNotes("The highest warning level covers only 5% of the area but contains two thirds of "
    + "the new fires, so the order of risk is right. But the probabilities are 1.2 to 1.8 times "
    + "too high, because there were fewer fires in the test years than in 2022.");

  s = content("Results", "People, season and recent temperature drive the forecasts", "Results");
  const fs1 = figure(s, "fig_shap.png", MX, 1.95, 7.9, 3.45, "SHAP explanations");
  text(s, "(a) Strongest single predictors; (b) strength of each group by land cover (darker = stronger).",
    MX, fs1.y + fs1.h + 0.05, 7.9, 0.4, { fontSize: 12, italic: true, color: MUTED });
  noteBox(s, MX, 5.95, 7.9, 0.85, "Different land, different drivers: ",
    "cropland follows recent weather (stubble burning), grassland follows people and season.");
  codeCell(s, 8.75, 2.0, W - MX - 8.75, 8,
    "import shap\n\n"
    + "explainer = shap.TreeExplainer(\n"
    + '    model, model_output="raw")\n'
    + "values = explainer(X_sample).values\n"
    + "importance = abs(values).mean(axis=0)", CELLS.shap, 11);
  noteBox(s, 8.75, 4.55, W - MX - 8.75, 2.25, "Research question 3",
    "Probabilities are good for ranking but too high in size. The outputs are explained mostly by "
    + "people, season and land surface.", SOFT_EMBER, EMBER);
  s.addNotes("SHAP shows which inputs pushed the forecasts. Population density is the strongest, "
    + "then month and recent temperature. The drivers differ by land cover. Together with the "
    + "calibration result, this answers our third question.");

  s = content("Results", "June 2023: many eastern fires were flagged, but not the Semei start", "Results");
  figure(s, "fig_case_wide.png", MX, 1.9, CW, 3.35, "Forecast maps 7-9 June 2023");
  const caseStats = [
    ["19–31%", "of each day's new fires were inside that day's top 5% of the area", TEAL],
    ["78th", "percentile for the start near Semei on 8 June, so it was not flagged", RED],
    ["4 of 7", "other eastern starts on 8–9 June were at or above the 96th percentile", EMBER],
  ];
  for (let i = 0; i < 3; i++) {
    const w = (CW - 0.6) / 3, x = MX + i * (w + 0.3);
    card(s, x, 5.4, w, 1.4);
    text(s, caseStats[i][0], x + 0.25, 5.5, w - 0.5, 0.6, { fontSize: 28, bold: true,
      color: caseStats[i][2], fontFace: "Cambria" });
    text(s, caseStats[i][1], x + 0.25, 6.1, w - 0.5, 0.65, { fontSize: 13, color: GREY });
  }
  s.addNotes("This is the week of the Semei Ormany fire. The model flagged many eastern fires, "
    + "but the Semei start was only at the 78th percentile. A forecast cannot prevent a fire, "
    + "and fire chance is only one part of risk.");

  s = content("Results", "What limits our results, and what we will do next", "Results");
  const lim = ["One satellite sensor; it shows first detection, not the real ignition time",
    "Farm burning cannot be separated from wildfires", "Weather is 7 days old",
    "Only 5 tuning trials instead of the planned 50", "Forest fires are too rare at 5 km to test separately"];
  const nxt = ["Weather forecasts for the target day", "Detections from several satellites",
    "Separate agricultural burning from wildfires", "Recalibrate by season and region",
    "Finer grid in forests; check against official fire records"];
  const colw = (CW - 0.3) / 2;
  for (const [i, head, items, ic, col, fill] of [[0, "Limitations", lim, "FaTriangleExclamation", RED, "FDE2E4"],
    [1, "Next steps", nxt, "FaForward", TEAL, SOFT_TEAL]]) {
    const x = MX + i * (colw + 0.3);
    card(s, x, 2.0, colw, 4.75, fill);
    await iconCircle(s, ic, x + 0.3, 2.2, 0.6, col);
    text(s, head, x + 1.05, 2.22, colw - 1.3, 0.55, { fontSize: 20, bold: true, color: col,
      valign: "middle" });
    s.addText(items.map((t, k) => ({ text: t, options: { bullet: true, breakLine: k < items.length - 1 } })),
      { x: x + 0.35, y: 3.1, w: colw - 0.7, h: 3.45, isTextBox: true, margin: 0, fontSize: 18,
        color: INK, paraSpaceAfter: 14, valign: "top" });
  }
  s.addNotes("Our main limits are the single satellite, the mixing of farm burning with "
    + "wildfires, and week-old weather. Next, we want to use weather forecasts for the target "
    + "day, more satellites and recalibration by season and region.");

  // ===== 23. Conclusion =====
  pres.addSection({ title: "Conclusion" });
  s = content("Conclusion", "All tasks set at the start of the work were completed", "Conclusion");
  const done = [
    "Built a Kazakhstan dataset that joins satellite fires with weather, vegetation, terrain, land cover and people, using only past data",
    "Compared four machine-learning models with two references and measured the value of seven predictor groups",
    "Tested on future years and unseen regions with rare-event measures and confidence intervals",
    "Calibrated the probabilities and explained the model with SHAP",
    "Produced daily probability maps and documented the data, settings and limits",
  ];
  for (let i = 0; i < done.length; i++) {
    const y = 2.0 + i * 0.88;
    await iconCircle(s, "FaCircleCheck", MX, y + 0.05, 0.5, TEAL);
    text(s, done[i], MX + 0.7, y - 0.1, 6.9, 0.8, { fontSize: 15, valign: "middle" });
  }
  card(s, 8.45, 2.0, W - MX - 8.45, 4.35, SOFT_EMBER, "answers");
  s.addText([
    { text: "Answers to the research questions", options: { bold: true, color: EMBER, fontSize: 17, breakLine: true } },
    { text: "1. ", options: { bold: true } }, { text: "Yes: XGBoost was 104 times better than random; the daily top 5% of the area held 55.6% of new fires.", options: { breakLine: true } },
    { text: "2. ", options: { bold: true } }, { text: "Strong for future years, weak for unseen regions.", options: { breakLine: true } },
    { text: "3. ", options: { bold: true } }, { text: "Good ranking, but probabilities too high; driven by people, season and land surface." },
  ], { x: 8.7, y: 2.2, w: W - MX - 8.95, h: 3.95, isTextBox: true, margin: 0, valign: "top",
    fontSize: 17, color: INK, paraSpaceAfter: 14 });
  text(s, "Thus, all tasks set at the beginning of this work were completed.", MX, 6.45, CW, 0.4,
    { fontSize: 16, italic: true, color: GREY });
  s.addNotes("To conclude: we built the dataset, compared the models, tested them in time and "
    + "space, checked calibration, explained the model and produced daily maps. The framework "
    + "is most useful as a daily ranking tool that shows where to look first.");

  // ===== 24. Thank you =====
  s = pres.addSlide({ masterName: "COVER", sectionTitle: "Conclusion" });
  s.addShape(pres.shapes.RECTANGLE, { x: 7.75, y: 0, w: W - 7.75, h: H, fill: { color: INK },
    line: { color: INK }, objectName: "map panel" });
  figure(s, "hero_map.png", 7.95, 1.8, W - 7.95 - 0.2, 3.9, "Forecast map of Kazakhstan");
  s.addText("Thank you for your attention!", { x: MX, y: 2.0, w: 6.8, h: 2.0, isTextBox: true,
    margin: 0, fontFace: "Cambria", fontSize: 44, color: EMBER, valign: "middle",
    objectName: "title" });
  text(s, "We are happy to answer your questions.", MX, 4.2, 6.8, 0.5, { fontSize: 18, color: GREY });
  s.addText([{ text: "Daily forecast platform: ", options: { bold: true, color: INK } },
    { text: "steppe-wildfire.wildf-kz.workers.dev",
      options: { color: TEAL, hyperlink: { url: "https://steppe-wildfire.wildf-kz.workers.dev/" } } }],
  { x: MX, y: 5.2, w: 6.8, h: 0.45, isTextBox: true, margin: 0, fontSize: 15 });
  text(s, "Samat Zharylkap, Nurbek Bolarbek · Astana IT University", MX, 5.75, 6.8, 0.4,
    { fontSize: 14, color: MUTED });

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("written", OUT);
})().catch((e) => { console.error(e); process.exit(1); });
