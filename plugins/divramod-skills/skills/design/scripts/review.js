// The review box (hal2 plan 0364, D7): the accept toggle and the comments of one design version. Served by
// `design.py serve` (http origin) they are live and saved in design/state.json; from file:// they stay read-only.
// Inlined before page.js: this file only declares, page.js draws.
const LIVE = location.protocol === "http:" || location.protocol === "https:";

async function post(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function versionById(id) {
  for (const f of DATA.feats) for (const k of f.kinds) for (const v of k.versions) if (v.id === id) return v;
  return null;
}

// The server answers with every design's new state (accepting one clears its siblings): take it over and redraw
// only the review boxes, the version tabs and the index, so open iframes and typed text stay.
function takeState(designs) {
  for (const f of DATA.feats) for (const k of f.kinds) for (const v of k.versions) {
    const e = designs[v.id] || {};
    v.review = { accepted: !!e.accepted, comments: Array.isArray(e.comments) ? e.comments : [] };
  }
  const typed = {};
  for (const box of document.querySelectorAll(".review textarea")) typed[box.closest(".review").dataset.designId] = box.value;
  for (const node of document.querySelectorAll(".review")) {
    const fresh = reviewBox(versionById(node.dataset.designId));
    const area = fresh.querySelector("textarea");
    if (area && typed[node.dataset.designId]) area.value = typed[node.dataset.designId];
    node.replaceWith(fresh);
  }
  if (at.view === "feats") drawVersionTabs();
  else drawIndex();
}

async function save(box, path, body) {
  const msg = box.querySelector(".msg");
  try {
    msg.textContent = "saving...";
    takeState((await post(path, body)).designs);
  } catch (err) {
    msg.textContent = `not saved: ${err.message}`;
  }
}

function commentLine(c) {
  return `${c.at || ""} ${c.by || ""}${c.anchor ? ` [${c.anchor}]` : ""}: ${c.text || ""}`;
}

function liveBox(version) {
  const id = version.id;
  const box = el("div", { class: "review live", "data-design-id": id });
  const toggle = el("input", { type: "checkbox" });
  toggle.checked = version.review.accepted;
  toggle.addEventListener("change", () => save(box, "accept", { id, accepted: toggle.checked }));
  const list = version.review.comments.map((c, index) => el("li", {}, commentLine(c), " ",
    el("button", { type: "button", class: "del", title: "delete this comment",
      onclick: () => save(box, "comment/delete", { id, index, at: c.at }) }, "delete")));
  const text = el("textarea", { rows: "2", placeholder: "comment on this design", "aria-label": "comment" });
  const anchor = el("select", { "aria-label": "about" }, el("option", { value: "" }, "whole design"),
    version.files.map((f) => el("option", { value: f.name }, f.name)));
  const add = el("button", { type: "button", onclick: () => {
    if (text.value.trim()) save(box, "comment", { id, text: text.value, anchor: anchor.value });
  } }, "add comment");
  box.append(el("label", {}, toggle, " accepted"), list.length ? el("ul", { class: "comments" }, list) : "",
    el("div", { class: "add" }, text, anchor, add), el("div", { class: "msg hint" }));
  return box;
}

function reviewBox(version) {
  if (LIVE) return liveBox(version);
  const toggle = el("input", { type: "checkbox", disabled: "" });
  toggle.checked = version.review.accepted;
  const comments = version.review.comments.map((c) => el("li", {}, commentLine(c)));
  return el("div", { class: "review", "data-design-id": version.id },
    el("label", {}, toggle, " accepted"),
    comments.length ? el("ul", { class: "comments" }, comments) : "",
    el("div", { class: "hint" }, `read-only: run \`${DATA.serve}\` to accept and comment`));
}
