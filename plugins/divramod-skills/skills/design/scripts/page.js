// The design page (hal2 plan 0364, D3-D5): draws the fixed layout from the JSON design.py render embedded.
// Libraries are pinned and loaded only when a design needs them; offline, a design shows its source instead.
const DATA = JSON.parse(document.getElementById("design-data").textContent);
const LIBS = {
  mermaid: "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.esm.min.mjs",
  marked: "https://cdn.jsdelivr.net/npm/marked@15.0.12/lib/marked.esm.js",
  excalidraw: "https://cdn.jsdelivr.net/npm/@excalidraw/excalidraw@0.18.1/+esm",
};
const loaded = {};
const at = { view: "feats", feat: 0, kind: 0, version: null, compare: false, left: null, right: null };
let counter = 0;

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return node;
}

function lib(name) {
  loaded[name] = loaded[name] || import(LIBS[name]);
  return loaded[name];
}

const feat = () => DATA.feats[at.feat];
const kind = () => feat().kinds[at.kind];
const versions = () => kind().versions;
const latest = () => versions().length - 1;

function current() {
  const list = versions();
  return list[at.version === null ? latest() : Math.min(at.version, latest())];
}

function readHash() {
  let hash = location.hash.slice(1);
  try { hash = decodeURIComponent(hash); } catch (err) { return; } // a malformed #%E0%A4%A: keep the default view
  if (hash === "designs") { at.view = "designs"; return; }
  const [f, k, v] = hash.split("/");
  const fi = DATA.feats.findIndex((x) => x.id === f);
  if (fi < 0) return;
  at.view = "feats"; at.feat = fi;
  const ki = DATA.feats[fi].kinds.findIndex((x) => x.id === k);
  at.kind = ki < 0 ? 0 : ki;
  const vi = versions().findIndex((x) => "v" + x.v === v);
  at.version = vi < 0 ? null : vi;
}

function writeHash() {
  if (!DATA.feats.length) return;
  const hash = at.view === "designs" ? "designs" : current().id;
  history.replaceState(null, "", "#" + encodeURIComponent(hash).replace(/%2F/g, "/"));
}

function go(change) {
  Object.assign(at, change);
  writeHash();
  draw();
}

function tabs(target, items, active, pick, accepted = () => false) {
  target.replaceChildren(...items.map((label, i) => el("button", {
    type: "button", class: "tab" + (i === active ? " on" : "") + (accepted(i) ? " accepted" : ""),
    onclick: () => pick(i),
  }, label)));
}

function step(by) {
  const flat = DATA.feats.flatMap((f, fi) => f.kinds.map((_, ki) => [fi, ki]));
  const here = flat.findIndex(([fi, ki]) => fi === at.feat && ki === at.kind);
  const [fi, ki] = flat[(here + by + flat.length) % flat.length];
  go({ view: "feats", feat: fi, kind: ki, version: null, left: null, right: null });
}

function fallback(box, file, why) {
  box.replaceChildren(el("div", { class: "fail" }, why), el("pre", { class: "raw" }, file.text || ""));
}

async function drawMermaid(box, file) {
  const { default: mermaid } = await lib("mermaid");
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
  const { svg } = await mermaid.render("mmd-" + ++counter, file.text);
  box.innerHTML = svg;
}

// Markdown may hold raw HTML: it is drawn in an iframe with an empty sandbox (no script, no same origin) under a CSP
// that allows no script or network, never into the page itself.
const MD_FRAME = "<!doctype html><meta charset=utf-8><meta http-equiv=Content-Security-Policy "
  + "content=\"default-src 'none'; img-src data:; style-src 'unsafe-inline'\"><style>"
  + "body{font:14px/1.5 system-ui,sans-serif;margin:8px}table{border-collapse:collapse}"
  + "th,td{border:1px solid #888;padding:3px 8px;text-align:left}pre,code{white-space:pre-wrap}</style>";

async function drawMarkdown(box, file) {
  const { marked } = await lib("marked");
  const frame = el("iframe", { sandbox: "", title: file.name });
  frame.srcdoc = MD_FRAME + marked.parse(file.text);
  box.replaceChildren(frame);
}

async function drawExcalidraw(box, file) {
  const { exportToSvg } = await lib("excalidraw");
  const scene = JSON.parse(file.text);
  const svg = await exportToSvg({
    elements: scene.elements || [], files: scene.files || {},
    appState: { ...(scene.appState || {}), exportBackground: true },
  });
  box.replaceChildren(svg);
}

function drawFrame(box, file) {
  const frame = el("iframe", { sandbox: "allow-scripts", title: file.name });
  frame.srcdoc = file.text;
  box.replaceChildren(frame);
}

const RENDERERS = {
  ".html": drawFrame, ".htm": drawFrame, ".mmd": drawMermaid, ".mermaid": drawMermaid, ".md": drawMarkdown,
  ".excalidraw": drawExcalidraw,
  ".dbml": (box, file) => { box.innerHTML = file.html; },
  ".svg": (box, file) => box.replaceChildren(el("img", {
    alt: file.name, src: "data:image/svg+xml;charset=utf-8," + encodeURIComponent(file.text) })),
};

function fileBox(file) {
  const box = el("div", { class: "box" });
  const draw = file.data ? (b) => b.replaceChildren(el("img", { alt: file.name, src: file.data }))
    : RENDERERS[file.ext] || ((b) => fallback(b, file, ""));
  Promise.resolve().then(() => draw(box, file))
    .catch((err) => fallback(box, file, `could not draw ${file.name} (${err && err.message || err}); its source:`));
  return el("figure", {}, el("figcaption", {}, file.name), box);
}

function filesArea(files) {
  const out = [];
  const used = new Set();
  for (const file of files) {
    if (used.has(file)) continue;
    const partner = file.role === "current" && files.find((f) => f.role === "new" && f.ext === file.ext);
    if (partner) {
      used.add(partner);
      out.push(el("div", { class: "pair" }, fileBox(file), fileBox(partner)));
    } else out.push(fileBox(file));
  }
  return out.length ? out : [el("div", { class: "empty" }, "no files in this version yet")];
}

function versionPanel(version) {
  const bits = [version.created, version.from && `from ${version.from}`, version.base && `base: ${version.base}`];
  return el("div", { class: "version", "data-design-id": version.id },
    el("div", { class: "meta" }, el("b", {}, `${version.title} `), `${version.id} `, bits.filter(Boolean).join(" · ")),
    reviewBox(version), filesArea(version.files));
}

function compareBar() {
  const bar = document.getElementById("compare-bar");
  const list = versions();
  const button = el("button", { type: "button", class: "cmp-btn" + (at.compare ? " on" : ""),
    onclick: () => go({ compare: !at.compare }) }, "compare");
  if (!at.compare || list.length < 2) { bar.replaceChildren(list.length < 2 ? "" : button); return; }
  const pick = (side, value) => el("select", { onchange: (e) => go({ [side]: Number(e.target.value) }) },
    list.map((v, i) => { const o = el("option", { value: i }, "v" + v.v); o.selected = i === value; return o; }));
  bar.replaceChildren(button, pick("left", leftIndex()), "vs", pick("right", rightIndex()));
}

const leftIndex = () => at.left === null ? Math.max(0, latest() - 1) : at.left;
const rightIndex = () => at.right === null ? latest() : at.right;

function drawVersionTabs() {
  const list = versions();
  tabs(document.getElementById("version-tabs"), list.map((v) => "v" + v.v), list.indexOf(current()),
    (i) => go({ version: i, compare: false }), (i) => list[i].review.accepted);
}

function drawFeats() {
  const list = versions();
  tabs(document.getElementById("feat-tabs"), DATA.feats.map((f) => f.id), at.feat,
    (i) => go({ feat: i, kind: 0, version: null, left: null, right: null }));
  tabs(document.getElementById("kind-tabs"), feat().kinds.map((k) => k.id), at.kind,
    (i) => go({ kind: i, version: null, left: null, right: null }));
  drawVersionTabs();
  compareBar();
  const content = at.compare && list.length > 1
    ? el("div", { class: "compare" }, versionPanel(list[leftIndex()]), versionPanel(list[rightIndex()]))
    : versionPanel(current());
  document.getElementById("content").replaceChildren(content);
}

function drawIndex() {
  for (const id of ["feat-tabs", "kind-tabs", "version-tabs", "compare-bar"]) {
    document.getElementById(id).replaceChildren();
  }
  const rows = DATA.feats.flatMap((f, fi) => f.kinds.flatMap((k, ki) => k.versions.map((v, vi) => el("tr", {
    class: "go", onclick: () => go({ view: "feats", feat: fi, kind: ki, version: vi, compare: false }) },
  el("td", {}, f.id), el("td", {}, k.id), el("td", {}, "v" + v.v), el("td", {}, v.title),
  el("td", {}, v.created), el("td", {}, v.review.accepted ? "accepted" : "open"),
  el("td", {}, String(v.review.comments.length))))));
  const head = el("tr", {}, ["feat", "kind", "version", "title", "created", "review", "comments"]
    .map((h) => el("th", {}, h)));
  document.getElementById("content").replaceChildren(el("table", { class: "index" }, head, rows));
}

function draw() {
  for (const b of document.querySelectorAll(".side-btn")) b.classList.toggle("on", b.dataset.view === at.view);
  document.getElementById("feat-row").querySelector(".arrows").hidden = at.view !== "feats";
  if (!DATA.feats.length) {
    document.getElementById("content").replaceChildren(el("div", { class: "empty" },
      "no designs yet: design.py new <feat> <kind>, then design.py render"));
    return;
  }
  if (at.view === "designs") drawIndex();
  else drawFeats();
}

for (const b of document.querySelectorAll(".side-btn")) b.addEventListener("click", () => go({ view: b.dataset.view }));
document.getElementById("prev").addEventListener("click", () => step(-1));
document.getElementById("next").addEventListener("click", () => step(1));
document.addEventListener("keydown", (e) => {
  if (e.target.closest("input, select, textarea") || at.view !== "feats" || !DATA.feats.length) return;
  if (e.key === "ArrowLeft") step(-1);
  if (e.key === "ArrowRight") step(1);
});
window.addEventListener("hashchange", () => { readHash(); draw(); });
readHash();
draw();
