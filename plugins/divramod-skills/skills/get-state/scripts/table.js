// get-state's table component (hal2 plan 0369, D2-D6, D9, D10): every `grid` section of the page (grid.py) becomes an
// interactive table: header click sorts (asc, desc, none), headers drag onto another to reorder, a gear opens the
// column menu (show/hide, up/down, sort, Fit widths, Reset), filter buttons, a refresh per table and for the page
// when served over http. Settings persist per table id in localStorage and, over http, in the server's /settings.
// The pure functions below are exported for node (test_table_js.py); the browser part runs only with a document.
(function () {
  "use strict";
  const PREFIX = "hal2-get-state:";
  const EMPTY = "Nothing here.";
  const ENT = { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\x22": "&quot;", "\x27": "&#x27;" };

  const esc = (v) => (v === null || v === undefined ? "" : String(v)).replace(/[&<>\x22\x27]/g, (c) => ENT[c]);
  const isEmpty = (v) => v === null || v === undefined || v === "";
  const text = (v) => (v === null || v === undefined ? "" : String(v));
  const columnsOf = (section) => (section.columns || []).filter((c) => c && c.key);
  const filtersOf = (section) => (section.filters || []).filter((f) => f && f.key);

  // Numbers numeric (a value without a leading number after every number), text in natural order, case folded.
  function compare(a, b, type) {
    if (type === "num") {
      const x = parseFloat(a), y = parseFloat(b);
      if (!isNaN(x) && !isNaN(y)) return x - y;
      if (!isNaN(x) || !isNaN(y)) return isNaN(x) ? 1 : -1;
    }
    return String(a).localeCompare(String(b), "en", { numeric: true, sensitivity: "base" });
  }

  // Stable; empty values last in both directions; no sort keeps the data order.
  function sortRows(rows, sort, columns) {
    if (!sort || !sort.key) return rows.slice();
    const col = (columns || []).find((c) => c.key === sort.key);
    const type = col ? col.type : "text";
    const sign = sort.dir === "desc" ? -1 : 1;
    return rows.map((r, i) => [r, i]).sort(([a, i], [b, j]) => {
      const ea = isEmpty(a[sort.key]), eb = isEmpty(b[sort.key]);
      if (ea || eb) return ea === eb ? i - j : ea ? 1 : -1;
      return sign * compare(a[sort.key], b[sort.key], type) || i - j;
    }).map(([r]) => r);
  }

  // Every matched column's value is one of the filter's values (as text); a filter without match is All.
  function matches(row, filter) {
    const match = (filter && filter.match) || {};
    return Object.keys(match).every((k) => (match[k] || []).map(text).includes(text(row[k])));
  }

  function filterRows(rows, filters, key) {
    const f = (filters || []).find((x) => x && x.key === key);
    return f ? rows.filter((r) => matches(r, f)) : rows.slice();
  }

  function counts(rows, filters) {
    const out = {};
    (filters || []).forEach((f) => { out[f.key] = rows.filter((r) => matches(r, f)).length; });
    return out;
  }

  function defaultFilter(section) {
    const filters = filtersOf(section);
    if (filters.some((f) => f.key === section.filter)) return section.filter;
    const all = filters.find((f) => !f.match);
    return all ? all.key : null;
  }

  function normSort(sort, keys) {
    return sort && keys.includes(sort.key) ? { key: sort.key, dir: sort.dir === "desc" ? "desc" : "asc" } : null;
  }

  function defaults(section) {
    const cols = columnsOf(section), keys = cols.map((c) => c.key);
    return { order: keys, hidden: cols.filter((c) => c.hidden).map((c) => c.key),
      sort: normSort(section.sort, keys), filter: defaultFilter(section), widths: {} };
  }

  // The saved settings over the section's defaults: columns that went drop out, a new column takes its default
  // place (after its nearest known predecessor) and its default visibility; a gone sort or filter falls back.
  function merge(section, saved) {
    const d = defaults(section);
    if (!saved || typeof saved !== "object") return d;
    const keys = d.order;
    const savedOrder = Array.isArray(saved.order) ? saved.order : [];
    const savedHidden = Array.isArray(saved.hidden) ? saved.hidden : [];
    const known = new Set(savedOrder.concat(savedHidden));
    const order = savedOrder.filter((k, i) => keys.includes(k) && savedOrder.indexOf(k) === i);
    keys.forEach((k, i) => {
      if (order.includes(k)) return;
      const prev = keys.slice(0, i).reverse().find((p) => order.includes(p));
      order.splice(prev === undefined ? 0 : order.indexOf(prev) + 1, 0, k);
    });
    const hidden = keys.filter((k) => (known.has(k) ? savedHidden.includes(k) : d.hidden.includes(k)));
    const sort = !("sort" in saved) ? d.sort : saved.sort === null ? null : normSort(saved.sort, keys) || d.sort;
    const fkeys = filtersOf(section).map((f) => f.key);
    const filter = fkeys.includes(saved.filter) ? saved.filter : d.filter;
    const widths = {};
    Object.entries(saved.widths || {}).forEach(([k, w]) => { if (keys.includes(k) && w > 0) widths[k] = Math.round(w); });
    return { order, hidden, sort, filter, widths };
  }

  const cycleSort = (sort, key) =>
    !sort || sort.key !== key ? { key, dir: "asc" } : sort.dir === "asc" ? { key, dir: "desc" } : null;

  function moveKey(order, key, delta) {
    const o = order.slice(), i = o.indexOf(key), j = i + delta;
    if (i < 0 || j < 0 || j >= o.length) return o;
    o.splice(i, 1);
    o.splice(j, 0, key);
    return o;
  }

  // Dragging right lands after the target, dragging left before it.
  function dropKey(order, from, to) {
    const o = order.slice(), i = o.indexOf(from), j = o.indexOf(to);
    if (i < 0 || j < 0 || i === j) return o;
    o.splice(i, 1);
    o.splice(j, 0, from);
    return o;
  }

  function visibleColumns(section, state) {
    const cols = columnsOf(section);
    return state.order.filter((k) => !state.hidden.includes(k)).map((k) => cols.find((c) => c.key === k));
  }

  function viewRows(section, state) {
    return sortRows(filterRows(section.rows || [], filtersOf(section), state.filter), state.sort, columnsOf(section));
  }

  function tableHtml(section, state) {
    const rows = viewRows(section, state);
    if (!rows.length) return `<p class="empty">${esc(section.empty || EMPTY)}</p>`;
    const sort = state.sort || {};
    const head = visibleColumns(section, state).map((c) => {
      const on = c.key === sort.key;
      const aria = on ? (sort.dir === "desc" ? "descending" : "ascending") : "none";
      const arrow = on ? (sort.dir === "desc" ? "↓" : "↑") : "";
      const width = state.widths[c.key] ? ` style="width:${state.widths[c.key]}px"` : "";
      return `<th data-key="${esc(c.key)}" draggable="true" aria-sort="${aria}"${width}>` +
        `${esc(c.label === undefined ? c.key : c.label)}<span class="arrow">${arrow}</span><span class="grip"></span></th>`;
    }).join("");
    const keys = visibleColumns(section, state).map((c) => c.key);
    const body = rows.map((r) => `<tr${r._marked ? ' class="marked"' : ""}>` +
      keys.map((k) => `<td>${esc(r[k])}</td>`).join("") + "</tr>").join("");
    return `<table class="grid-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  }

  function filtersHtml(section, state) {
    const filters = filtersOf(section);
    if (!filters.length) return "";
    const n = counts(section.rows || [], filters);
    return filters.map((f) => `<button type="button" class="grid-filter${f.key === state.filter ? " on" : ""}" ` +
      `data-filter="${esc(f.key)}">${esc(f.label || f.key)} <span class="count">${n[f.key]}</span></button>`).join("");
  }

  const item = (act, key, check, label, extra, cls) =>
    `<div class="menu-item${cls || ""}" role="menuitem" data-act="${act}" data-key="${esc(key)}"><span class="check">` +
    `${check ? "✓" : ""}</span><span class="label">${label}</span>${extra || ""}</div>`;

  // The column menu of 66.png: Columns (check, up, down), Sort (Unsorted, each column, Ascending), Fit widths, Reset.
  function menuHtml(section, state) {
    const cols = columnsOf(section), last = state.order.length - 1, sort = state.sort;
    const parts = ['<div class="menu-title">Columns</div>'];
    state.order.forEach((k, i) => {
      const c = cols.find((x) => x.key === k);
      const arrows = `<button type="button" class="mv" data-act="up" data-key="${esc(k)}"${i === 0 ? " disabled" : ""}` +
        ` title="Move up">↑</button><button type="button" class="mv" data-act="down" data-key="${esc(k)}"` +
        `${i === last ? " disabled" : ""} title="Move down">↓</button>`;
      parts.push(item("toggle", k, !state.hidden.includes(k), esc(c.label === undefined ? k : c.label), arrows));
    });
    parts.push('<div class="menu-title">Sort</div>', item("sort", "", !sort, "Unsorted"));
    state.order.forEach((k) => {
      const c = cols.find((x) => x.key === k);
      parts.push(item("sort", k, sort && sort.key === k, esc(c.label === undefined ? k : c.label)));
    });
    parts.push(item("asc", "", !sort || sort.dir === "asc", "Ascending", "", sort ? "" : " off"));
    parts.push('<div class="menu-sep"></div>', item("fit", "", false, "Fit widths"), item("reset", "", false, "Reset"));
    return `<div class="grid-menu" role="menu">${parts.join("")}</div>`;
  }

  // Applies one menu action to a state; returns the new state (Reset is the caller's).
  function act(state, action, key) {
    const s = { ...state, hidden: state.hidden.slice(), order: state.order.slice(), widths: { ...state.widths } };
    if (action === "toggle") s.hidden = s.hidden.includes(key) ? s.hidden.filter((k) => k !== key) : s.hidden.concat(key);
    else if (action === "up" || action === "down") s.order = moveKey(s.order, key, action === "up" ? -1 : 1);
    else if (action === "sort") s.sort = key ? { key, dir: state.sort && state.sort.key === key ? state.sort.dir : "asc" } : null;
    else if (action === "asc" && s.sort) s.sort = { key: s.sort.key, dir: s.sort.dir === "asc" ? "desc" : "asc" };
    else if (action === "fit") s.widths = {};
    return s;
  }

  // A grid's JSON island: plain JSON, or (a big one, grid.py's PACK_OVER) gzip in base64, unpacked by the platform.
  function readIsland(node) {
    if (node.type !== "application/gzip+base64") return Promise.resolve(JSON.parse(node.textContent));
    const bytes = Uint8Array.from(atob(node.textContent.trim()), (c) => c.charCodeAt(0));
    return new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).text().then(JSON.parse);
  }

  const api = { esc, compare, sortRows, matches, filterRows, counts, defaultFilter, defaults, merge, cycleSort,
    moveKey, dropKey, visibleColumns, viewRows, tableHtml, filtersHtml, menuHtml, act, readIsland, PREFIX };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document === "undefined") return;

  const served = /^https?:$/.test(location.protocol);
  const grids = [];

  function loadLocal(id) {
    try { return JSON.parse(localStorage.getItem(PREFIX + id) || "null"); } catch (e) { return null; }
  }

  function persist(g, drop) {
    try {
      if (drop) localStorage.removeItem(PREFIX + g.id);
      else localStorage.setItem(PREFIX + g.id, JSON.stringify(g.state));
    } catch (e) { /* storage off: the server copy is enough */ }
    if (served) {
      fetch("/settings", { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [g.id]: drop ? null : g.state }) }).catch(() => {});
    }
  }

  function render(g) {
    g.el.querySelector(".grid-body").innerHTML = tableHtml(g.section, g.state);
    g.el.querySelector(".grid-filters").innerHTML = filtersHtml(g.section, g.state);
    const note = g.el.querySelector(".grid-note");
    if (note) note.textContent = g.section.note || "";
    const tools = g.el.querySelector(".grid-tools");
    tools.innerHTML = (served ? '<button type="button" class="grid-refresh" title="Refresh this table">↻</button>' : "") +
      '<button type="button" class="grid-gear" title="Columns and sort" aria-haspopup="menu">⚙</button>' +
      (g.menu ? menuHtml(g.section, g.state) : "");
  }

  function change(g, state) {
    g.state = state;
    persist(g);
    render(g);
  }

  function refresh(g, btn) {
    btn.classList.add("busy");
    fetch("/table/" + encodeURIComponent(g.id) + location.search, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((section) => { g.section = section; g.state = merge(section, g.state); render(g); })
      .catch(() => { btn.classList.remove("busy"); btn.classList.add("failed"); btn.title = "Refresh failed"; });
  }

  function onClick(g, e) {
    const t = e.target;
    if (t.closest(".grid-tools")) e.gridTools = g;
    const btn = t.closest("button, .menu-item, th, .grid-filter");
    if (!btn || btn.disabled || btn.classList.contains("off")) return;
    if (btn.classList.contains("grid-gear")) { g.menu = !g.menu; render(g); return; }
    if (btn.classList.contains("grid-refresh")) { refresh(g, btn); return; }
    if (btn.classList.contains("grid-filter")) { change(g, { ...g.state, filter: btn.dataset.filter }); return; }
    if (btn.tagName === "TH") {
      if (g.resized || t.classList.contains("grip")) { g.resized = false; return; }
      change(g, { ...g.state, sort: cycleSort(g.state.sort, btn.dataset.key) });
      return;
    }
    const action = btn.dataset.act;
    if (action === "reset") { g.state = defaults(g.section); persist(g, true); render(g); return; }
    if (action) change(g, act(g.state, action, btn.dataset.key || ""));
  }

  function onResize(g, e) {
    const grip = e.target.closest(".grip");
    if (!grip) return;
    e.preventDefault();
    e.stopPropagation();
    const th = grip.parentElement, x0 = e.clientX, w0 = th.offsetWidth;
    th.draggable = false;
    const move = (m) => { th.style.width = Math.max(40, w0 + m.clientX - x0) + "px"; };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      g.resized = true;
      setTimeout(() => { g.resized = false; }, 0);
      change(g, { ...g.state, widths: { ...g.state.widths, [th.dataset.key]: th.offsetWidth } });
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  }

  function wire(g) {
    g.el.addEventListener("click", (e) => onClick(g, e));
    g.el.addEventListener("pointerdown", (e) => onResize(g, e));
    g.el.addEventListener("dragstart", (e) => {
      const th = e.target.closest && e.target.closest("th");
      if (!th) return;
      g.drag = th.dataset.key;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", g.drag);
    });
    const over = (on) => (e) => {
      const th = g.drag && e.target.closest && e.target.closest("th");
      if (!th) return;
      if (on) e.preventDefault();
      th.classList.toggle("over", on);
    };
    g.el.addEventListener("dragover", over(true));
    g.el.addEventListener("dragleave", over(false));
    g.el.addEventListener("drop", (e) => {
      const th = e.target.closest("th");
      if (!g.drag || !th) return;
      e.preventDefault();
      const from = g.drag;
      g.drag = null;
      change(g, { ...g.state, order: dropKey(g.state.order, from, th.dataset.key) });
    });
    g.el.addEventListener("dragend", () => { g.drag = null; g.el.querySelectorAll("th.over").forEach((th) => th.classList.remove("over")); });
  }

  const els = [...document.querySelectorAll("section.grid[data-grid]")].filter((el) => el.querySelector("script.grid-data"));
  const mounted = Promise.all(els.map((el) => readIsland(el.querySelector("script.grid-data")).catch(() => null)))
    .then((sections) => els.forEach((el, i) => {
      if (!sections[i]) return;
      const g = { el, id: el.dataset.grid, section: sections[i], menu: false };
      g.state = merge(g.section, loadLocal(g.id));
      grids.push(g);
      wire(g);
      render(g);
    }));

  document.addEventListener("click", (e) => {
    grids.forEach((g) => { if (g.menu && e.gridTools !== g) { g.menu = false; render(g); } });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") grids.forEach((g) => { if (g.menu) { g.menu = false; render(g); } });
  });

  if (served) {
    document.body.insertAdjacentHTML("afterbegin",
      '<button type="button" class="page-refresh" title="Refresh the page">↻</button>');
    document.querySelector(".page-refresh").addEventListener("click", () => location.reload());
    Promise.all([fetch("/settings", { cache: "no-store" }).then((r) => (r.ok ? r.json() : {})), mounted]).then(([all]) => {
      grids.forEach((g) => {
        if (!all || !all[g.id]) return;
        g.state = merge(g.section, all[g.id]);
        try { localStorage.setItem(PREFIX + g.id, JSON.stringify(g.state)); } catch (e) { /* storage off */ }
        render(g);
      });
    }).catch(() => {});
  }
})();
