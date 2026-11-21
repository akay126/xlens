// Dependency explorer: Row map (find a row) + Trace (dig into one cell).
// window.XlensExplorer.mount(rootEl, data, opts) -> { focus(ids, mode), setData(data) }
//   data = { nodes, links, kpis:[{name,cell,display?,scenarios:[{cell,header,display}]}], findings:[{cell,kind,severity}] }
//   opts = { askLabel?, onAsk?(text) }  (neither set -> no ask button)
// The HTML report auto-mounts from its global `graphData` and the KPI list in #xe-kpis.
// All spreadsheet text goes through esc() before reaching innerHTML.
(function() {
  'use strict';
  var MAP_ROW_LIMIT = 1200;
  var PALETTE = ['#E69F00', '#56B4E9', '#CC79A7', '#D55E00', '#009E73', '#0072B2', '#999933', '#882255', '#44AA99', '#6f7d86'];

  // ---------- helpers ----------
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }
  function colNum(ref) {
    var m = /^\$?([A-Z]+)/.exec(ref || ''), s = m ? m[1] : 'A', n = 0;
    for (var i = 0; i < s.length; i++) n = n * 26 + (s.charCodeAt(i) - 64);
    return n;
  }
  function rowNum(ref) { return parseInt(String(ref || '').replace(/[^0-9]/g, ''), 10) || 0; }
  function num(v) {
    if (typeof v === 'number') return v;
    if (typeof v === 'string' && /^-?\d+(\.\d+)?(e-?\d+)?$/i.test(v.trim())) return parseFloat(v);
    return null;
  }
  function linkId(x) { return x && typeof x === 'object' ? x.id : x; }  
  function trunc(s, n) { return s.length > n ? s.slice(0, n - 1) + '…' : s; }

  function mount(root, data, opts) {
    opts = opts || {};
    var cur = build(root, data || {}, opts);
    return {
      focus: function(ids, mode) { cur.focus(ids, mode); },
      setData: function(d) { root.innerHTML = ''; cur = build(root, d || {}, opts); }
    };
  }

  function build(root, data, opts) {
  function part(id) { return root.querySelector('#' + id); }

  // ---------- model ----------
  var kpiList = (data.kpis || []).filter(function(k) { return k && k.cell; });

  var all = data.nodes || [], byId = Object.create(null), C = [];
  all.forEach(function(n) {
    if (!(n.in_degree > 0 || n.out_degree > 0)) return;
    var c = {
      i: C.length, id: n.id, sheet: n.sheet || '', ref: n.cell_ref || '', label: n.row_label || n.cell_ref || n.id,
      f: n.formula || '', raw: n.value, v: num(n.value), cls: n.classification || '',
      col: colNum(n.cell_ref), row: rowNum(n.cell_ref), pre: [], suc: []
    };
    C.push(c); byId[c.id] = c;
  });
  if (!C.length) { root.innerHTML = '<p class="xe-empty">This model has no formulas linking cells, so there is nothing to explore.</p>'; return { focus: function() {} }; }
  (data.links || []).forEach(function(l) {
    var a = byId[linkId(l.source)], b = byId[linkId(l.target)];
    if (a && b) { b.pre.push(a.i); a.suc.push(b.i); }
  });

  var sheetOrder = Object.create(null), sheets = [];
  all.forEach(function(n) { if (n.sheet && sheetOrder[n.sheet] == null) { sheetOrder[n.sheet] = sheets.length; sheets.push(n.sheet); } });
  function sOrd(s) { return Object.prototype.hasOwnProperty.call(sheetOrder, s) ? sheetOrder[s] : -1; }
  function shColor(s) { return PALETTE[Math.max(0, sOrd(s)) % PALETTE.length]; }

  var kpiOf = Object.create(null);
  kpiList.forEach(function(k) { var c = byId[k.cell]; if (c) kpiOf[c.i] = k; });

  var R = [], rowByKey = Object.create(null);
  C.forEach(function(c) {
    var k = c.row ? c.sheet + '|' + c.row : 'cell|' + c.id, r = rowByKey[k];  // refs with no row number stay separate
    if (!r) { r = rowByKey[k] = { key: k, idx: R.length, sheet: c.sheet, row: c.row, label: c.label, cells: [], pre: {}, suc: {}, rolls: false }; R.push(r); }
    r.cells.push(c.i); c.r = r;
  });
  R.forEach(function(r) { r.cells.sort(function(a, b) { return C[a].col - C[b].col; }); });
  C.forEach(function(c) {
    c.pre.forEach(function(p) {
      var pr = C[p].r;
      if (pr === c.r) c.r.rolls = true; else { c.r.pre[pr.idx] = 1; pr.suc[c.r.idx] = 1; }
    });
  });
  R.forEach(function(r) {
    r.preL = Object.keys(r.pre).map(Number); r.sucL = Object.keys(r.suc).map(Number);
    r.kpi = r.cells.some(function(i) { return kpiOf[i]; });
  });
  var flagsOf = Object.create(null);  // row idx -> findings on that row (cells missing from the map are skipped)
  (data.findings || []).forEach(function(f) {
    var c = f && byId[f.cell];
    if (c) (flagsOf[c.r.idx] = flagsOf[c.r.idx] || []).push(f);
  });
  var aiCells = Object.create(null), aiRows = Object.create(null);  // cells/rows the assistant last pointed at

  function closure(start, nb) {
    var seen = {}, q = [start], out = [], head = 0;
    seen[start] = 1;
    while (head < q.length) {
      var x = q[head++], ns = nb(x);
      for (var j = 0; j < ns.length; j++) if (!seen[ns[j]]) { seen[ns[j]] = 1; out.push(ns[j]); q.push(ns[j]); }
    }
    return out;
  }
  function cellUp(i) { return closure(i, function(x) { return C[x].pre; }); }
  function cellDn(i) { return closure(i, function(x) { return C[x].suc; }); }
  function rowUp(i) { return closure(i, function(x) { return R[x].preL; }); }
  function rowDn(i) { return closure(i, function(x) { return R[x].sucL; }); }

  // ---------- formatting ----------
  function fmt(c) {
    var v = c.v, L = (c.label || '').toLowerCase();
    if (v === null) return c.raw === '' || c.raw == null ? '—' : String(c.raw);
    if (/dscr|multiple/.test(L)) return v.toFixed(2) + 'x';
    if (Math.abs(v) <= 1.5 && v !== Math.round(v) && /%|rate|irr|growth|yield|return|cap rate|\bcap\b|vacancy|ratio|margin|split|fee|cash-on-cash/.test(L)) return (v * 100).toFixed(1) + '%';
    var money = /\$|price|cost|income|noi|revenue|expense|cash|value|balance|payment|equity|debt|profit|rent|reserve|tax|insurance|loan|proceeds|interest|principal|distribution/.test(L) && !/\(months\)|units|sf\b|year/.test(L);
    var a = Math.abs(v), s = a >= 1000 ? Math.round(a).toLocaleString('en-US') : (a === Math.round(a) ? String(a) : a.toFixed(a < 1 ? 4 : 2));
    return (v < 0 ? '−' : '') + (money ? '$' : '') + s;
  }
  function badge(c) {
    if (kpiOf[c.i]) return '<span class="xe-cls xe-kpi">KPI</span>';
    if (c.cls === 'deal_input' || c.cls === 'structural_assumption') return '<span class="xe-cls xe-in">Input</span>';
    if (c.cls === 'hardcoded_in_cashflow') return '<span class="xe-cls xe-hard">Hardcoded</span>';
    if (c.cls === 'external_ref') return '<span class="xe-cls">External</span>';
    return '<span class="xe-cls">' + (c.f ? 'Formula' : 'Value') + '</span>';
  }
  function rangeOf(ids) {
    var cs = ids.map(function(i) { return C[i]; }).sort(function(a, b) { return a.col - b.col; });
    if (cs.length === 1) return cs[0].ref;
    var contiguous = cs.every(function(c, k) { return k === 0 || c.col === cs[k - 1].col + 1; });
    if (contiguous) return cs[0].ref + ':' + cs[cs.length - 1].ref;
    return cs.slice(0, 3).map(function(c) { return c.ref; }).join(', ') + (cs.length > 3 ? ' +' + (cs.length - 3) : '');
  }
  function spark(ids) {
    var vs = ids.map(function(i) { return C[i].v; }).filter(function(v) { return v !== null; });
    if (vs.length < 3) return '';
    var mn = Math.min.apply(null, vs), mx = Math.max.apply(null, vs), span = (mx - mn) || 1;
    var pts = vs.map(function(v, k) { return (2 + k * 60 / (vs.length - 1)).toFixed(1) + ',' + (16 - (v - mn) / span * 14).toFixed(1); }).join(' ');
    return '<svg class="xe-spark" viewBox="0 0 64 18" aria-hidden="true"><polyline points="' + pts + '"/></svg>';
  }
  function lastCell(r) { return C[r.cells[r.cells.length - 1]]; }
  function dot(sheet) { return '<span class="xe-dot" style="background:' + shColor(sheet) + '"></span>'; }
  function flagText(fs) {
    var seen = Object.create(null), kinds = [];
    fs.forEach(function(f) { var k = String(f.kind || 'finding') + (f.severity ? ' (' + f.severity + ')' : ''); if (!seen[k]) { seen[k] = 1; kinds.push(k); } });
    return fs.length + ' finding' + (fs.length === 1 ? '' : 's') + ': ' + kinds.join(', ');
  }
  function kpiStrip() {
    var shown = kpiList.filter(function(k) { return k.display || (k.scenarios && k.scenarios.length); });
    if (!shown.length) return '';  // the report passes names only; its KPIs have their own section
    function btn(cell, inner, cls) {
      var c = byId[cell];
      return c ? '<button type="button" class="' + cls + '" data-cell="' + c.i + '" title="' + esc(c.id) + '">' + inner + '</button>'
               : '<span class="' + cls + '">' + inner + '</span>';
    }
    return '<div class="xe-kpis" role="list" aria-label="Key outputs">' + shown.map(function(k) {
      var sc = (k.scenarios || []).filter(function(x) { return x && x.cell; });
      var vals = sc.length
        ? sc.map(function(x) { return btn(x.cell, '<i>' + esc(x.header) + '</i>' + esc(x.display), 'xe-kv'); }).join('<span class="xe-ksep" aria-hidden="true">/</span>')
        : btn(k.cell, esc(k.display), 'xe-kv');
      return '<div class="xe-kpi-i" role="listitem">' + btn(k.cell, esc(k.name), 'xe-kname') + vals + '</div>';
    }).join('') + '</div>';
  }
  var askOn = !!(opts.onAsk || opts.askLabel);
  function askBtn(what) {
    if (!askOn) return '';
    return '<button type="button" class="xe-ask" data-ask="' + what + '">' + esc(opts.onAsk ? (opts.askLabel || 'Ask about this row') : opts.askLabel) + '</button>';
  }
  // The question goes to a chat model, so workbook text in it is untrusted: quotes and line breaks are
  // stripped, the label is cut to 60 characters and quoted, and the cell reference leads.
  function askClean(s, max) {
    s = String(s == null ? '' : s).replace(/["'\u201c\u201d\u2018\u2019`]/g, '').replace(/[\s\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g, ' ').trim();
    return max && s.length > max ? s.slice(0, max - 1).trim() + '\u2026' : s;
  }
  function askFor(sheet, ref, label) {
    var l = askClean(label, 60);
    return 'Explain ' + askClean(sheet, 40) + '!' + ref + (l ? ' (row "' + l + '")' : '') + ' in this model.';
  }
  function askText(what) {
    if (what === 'row' && sel != null) { var r = R[sel]; return askFor(r.sheet, rangeOf(r.cells), r.label); }
    var c = C[state.cell];
    return askFor(c.sheet, c.ref, c.label);
  }
  function ask(btn) {
    var text = askText(btn.dataset.ask);
    if (opts.onAsk) { opts.onAsk(text); return; }
    function fallback() {  // clipboard blocked: show the text selected so the user can copy it
      var box = btn.nextElementSibling;
      if (!box || !box.classList.contains('xe-askbox')) {
        box = document.createElement('input');
        box.type = 'text'; box.readOnly = true; box.className = 'xe-askbox'; box.setAttribute('aria-label', 'Question to copy');
        btn.parentNode.insertBefore(box, btn.nextSibling);
      }
      box.value = text; box.focus(); box.select();
      btn.textContent = 'Copy the text below';
    }
    try {
      navigator.clipboard.writeText(text).then(function() { btn.textContent = 'Copied'; }, fallback);
    } catch (e) { fallback(); }
  }

  // ---------- shell ----------
  var startCell = kpiList.length && byId[kpiList[0].cell] ? byId[kpiList[0].cell].i
    : C.slice().sort(function(a, b) { return b.pre.length - a.pre.length; })[0].i;
  var state = { cell: startCell, view: 'map', trail: [] };
  var mapOn = R.length <= MAP_ROW_LIMIT;

  root.innerHTML = kpiStrip() +
    '<div class="xe-bar">' +
      '<div class="xe-tabs" role="tablist">' +
        '<button class="xe-tab" role="tab" data-view="map"' + (mapOn ? '' : ' disabled title="Too many rows to draw; use search and Trace"') + '><b>Row map</b><span>Find a row</span></button>' +
        '<button class="xe-tab" role="tab" data-view="trace"><b>Trace</b><span>Dig into one cell</span></button>' +
      '</div>' +
      '<div class="xe-search"><input id="xe-q" type="search" placeholder="Find a cell: label or reference, e.g. NOI, B17, Sheet1!L22" autocomplete="off" aria-label="Find a cell"><ul class="xe-results" id="xe-results" hidden></ul></div>' +
    '</div>' +
    '<div class="xe-view" id="xe-map" hidden>' +
      '<div class="xe-mapwrap">' +
        '<div class="xe-stage" id="xe-stage"><svg aria-label="Row dependency map"><g id="xe-g"></g></svg>' +
          '<div class="xe-tools"><button data-z="in" aria-label="Zoom in">+</button><button data-z="out" aria-label="Zoom out">−</button><button data-z="fit" aria-label="Fit whole map">⤢</button></div>' +
          '<div class="xe-legend" id="xe-legend"></div></div>' +
        '<aside class="xe-side" id="xe-side"></aside>' +
      '</div>' +
    '</div>' +
    '<div class="xe-view" id="xe-trace" hidden>' +
      '<nav class="xe-crumbs" id="xe-crumbs" aria-label="Trail"></nav>' +
      '<div class="xe-trace">' +
        '<div class="xe-col xe-up"><h4>Feeds into this <em id="xe-upn"></em></h4><div class="xe-glist" id="xe-upl"></div></div>' +
        '<div class="xe-focus" id="xe-focus"></div>' +
        '<div class="xe-col xe-down"><h4>Used by <em id="xe-dnn"></em></h4><div class="xe-glist" id="xe-dnl"></div></div>' +
      '</div>' +
    '</div>';

  var views = { map: renderMap, trace: renderTrace };
  function setView(v) {
    if (v === 'map' && !mapOn) v = 'trace';
    state.view = v;
    root.querySelectorAll('.xe-tab').forEach(function(b) { b.setAttribute('aria-selected', b.dataset.view === v ? 'true' : 'false'); });
    part('xe-map').hidden = v !== 'map';
    part('xe-trace').hidden = v !== 'trace';
    views[v]();
  }
  function focusCell(i) {
    state.cell = i;
    var t = state.trail, pos = t.indexOf(i);
    if (pos >= 0) state.trail = t.slice(0, pos + 1); else { t.push(i); if (t.length > 8) t.shift(); }
    views[state.view]();
  }
  function digIn(i) { state.trail = []; state.cell = i; setView('trace'); }
  root.querySelectorAll('.xe-tab').forEach(function(b) { b.addEventListener('click', function() {
    // a trail only makes sense if it ends at the cell being traced
    if (b.dataset.view === 'trace' && state.trail[state.trail.length - 1] !== state.cell) state.trail = [];
    setView(b.dataset.view);
  }); });

  // ---------- search ----------
  var q = part('xe-q'), res = part('xe-results'), hits = [], hi = 0;
  function doSearch() {
    var s = q.value.trim().toLowerCase();
    if (!s) { res.hidden = true; return; }
    var seen = Object.create(null);
    hits = [];
    C.forEach(function(c) {
      var full = c.id.toLowerCase();
      if (c.ref.toLowerCase() === s || full === s || (s.indexOf('!') >= 0 && full.indexOf(s) >= 0)) hits.unshift({ c: c, exact: true });
      else if (c.label.toLowerCase().indexOf(s) >= 0 && !seen[c.r.key]) { seen[c.r.key] = 1; hits.push({ c: lastCell(c.r) }); }
    });
    hits = hits.slice(0, 10); hi = 0;
    res.innerHTML = hits.length ? hits.map(function(h, k) {
      var c = h.c;
      return '<li><button type="button" data-k="' + k + '" class="' + (k === 0 ? 'xe-on' : '') + '">' + dot(c.sheet) + '<span>' + esc(c.label) + '</span><span class="xe-mono">' + esc(c.sheet) + '!' + esc(h.exact ? c.ref : rangeOf(c.r.cells)) + '</span></button></li>';
    }).join('') : '<li class="xe-none">No cell matches “' + esc(q.value) + '”</li>';
    res.hidden = false;
  }
  function pick(k) {
    if (!hits[k]) return;
    res.hidden = true; q.value = ''; q.blur();
    if (state.view === 'map') { state.cell = hits[k].c.i; selectRow(hits[k].c.r.idx, true); }
    else focusCell(hits[k].c.i);
  }
  q.addEventListener('input', doSearch);
  q.addEventListener('keydown', function(e) {
    if (res.hidden || !hits.length) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); hi = (hi + (e.key === 'ArrowDown' ? 1 : -1) + hits.length) % hits.length;
      res.querySelectorAll('button').forEach(function(b, k) { b.classList.toggle('xe-on', k === hi); });
    } else if (e.key === 'Enter') { e.preventDefault(); pick(hi); }
    else if (e.key === 'Escape') { res.hidden = true; }
  });
  res.addEventListener('mousedown', function(e) { var b = e.target.closest('button[data-k]'); if (b) { e.preventDefault(); pick(+b.dataset.k); } });
  q.addEventListener('blur', function() { setTimeout(function() { res.hidden = true; }, 120); });

  // ---------- Row map ----------
  var NW = 188, NH = 36, GX = 74, GY = 10, PAD = 40, layout = null, vw = { x: 0, y: 0, k: 1 }, sel = null, mode = 'both', drawn = false;
  function buildLayout() {
    var n = R.length, indeg = R.map(function(r) { return r.preL.length; }), layer = R.map(function() { return 0; }),
        done = R.map(function() { return false; }), qq = [], cnt = 0;
    R.forEach(function(r, i) { if (!indeg[i]) qq.push(i); });
    while (cnt < n) {
      if (!qq.length) {  // rows can loop (A feeds B in one column, B feeds A in the next): release the least-blocked row
        var best = -1;
        R.forEach(function(r, i) { if (!done[i] && (best < 0 || indeg[i] < indeg[best])) best = i; });
        qq.push(best); indeg[best] = 0;
      }
      var x = qq.shift();
      if (done[x]) continue;
      done[x] = true; cnt++;
      R[x].sucL.forEach(function(y) { if (done[y]) return; layer[y] = Math.max(layer[y], layer[x] + 1); if (--indeg[y] === 0) qq.push(y); });
    }
    var L = Math.max.apply(null, layer) + 1, cols = [], pos = {};
    for (var k = 0; k < L; k++) cols.push([]);
    R.forEach(function(r, i) { cols[layer[i]].push(i); });
    cols.forEach(function(col) { col.sort(function(a, b) { return (sOrd(R[a].sheet) - sOrd(R[b].sheet)) || R[a].row - R[b].row; }); });
    function idxs() { cols.forEach(function(col) { col.forEach(function(i, k2) { pos[i] = k2; }); }); }
    idxs();
    for (var sweep = 0; sweep < 4; sweep++) {  // barycenter passes keep linked rows near each other
      for (var c = 1; c < L; c++) {
        cols[c].forEach(function(i) { var p = R[i].preL; R[i]._b = p.length ? p.reduce(function(s, j) { return s + pos[j]; }, 0) / p.length : pos[i]; });
        cols[c].sort(function(a, b) { return R[a]._b - R[b]._b; });
        idxs();
      }
    }
    var maxRows = Math.max.apply(null, cols.map(function(c2) { return c2.length; }));
    R.forEach(function(r, i) {
      var off = (maxRows - cols[layer[i]].length) * (NH + GY) / 2;
      r.x = PAD + layer[i] * (NW + GX); r.y = PAD + 18 + off + pos[i] * (NH + GY); r.layer = layer[i];
    });
    return { w: PAD * 2 + L * NW + (L - 1) * GX, h: PAD * 2 + 18 + maxRows * (NH + GY), L: L };
  }
  function drawMap() {
    layout = buildLayout();
    var s = '';
    for (var k = 0; k < layout.L; k++) s += '<text class="xe-layer" x="' + (PAD + k * (NW + GX)) + '" y="' + PAD + '">' + (k === 0 ? 'STEP 1 · INPUTS' : 'STEP ' + (k + 1)) + '</text>';
    R.forEach(function(r) {
      r.sucL.forEach(function(j) {
        var t = R[j], x1 = r.x + NW, y1 = r.y + NH / 2, x2 = t.x, y2 = t.y + NH / 2, d;
        if (x2 > x1) { var mx = (x1 + x2) / 2; d = 'M' + x1 + ',' + y1 + ' C' + mx + ',' + y1 + ' ' + mx + ',' + y2 + ' ' + x2 + ',' + y2; }
        else d = 'M' + x1 + ',' + y1 + ' C' + (x1 + 60) + ',' + (y1 - 60) + ' ' + (x2 - 60) + ',' + (y2 - 60) + ' ' + x2 + ',' + y2;
        s += '<path class="xe-edge" data-a="' + r.idx + '" data-b="' + j + '" d="' + d + '"/>';
      });
    });
    R.forEach(function(r) {
      var fl = flagsOf[r.idx];
      s += '<g class="xe-node' + (fl ? ' xe-flag' : '') + '" data-row="' + r.idx + '" transform="translate(' + r.x + ',' + r.y + ')" tabindex="0" role="button" aria-label="' + esc(r.label + ', ' + r.sheet + (fl ? ', ' + flagText(fl) : '')) + '">' +
        '<title>' + esc(r.label + ' — ' + r.sheet + '!' + rangeOf(r.cells) + (fl ? ' · ' + flagText(fl) : '')) + '</title>' +
        '<rect class="xe-box" width="' + NW + '" height="' + NH + '" rx="6"/><rect width="4" height="' + NH + '" rx="2" style="fill:' + shColor(r.sheet) + '"/>' +
        '<text x="12" y="15">' + esc(trunc(r.label, 27)) + (r.kpi ? ' ★' : '') + '</text>' +
        '<text class="xe-sub" x="12" y="28">' + esc(trunc(rangeOf(r.cells), 18)) + (r.rolls ? ' ↻' : '') + '</text>' +
        '<text class="xe-sub" x="' + (NW - 8) + '" y="28" text-anchor="end">' + esc(trunc(fmt(lastCell(r)), 12)) + '</text>' +
        (fl ? '<circle class="xe-flagdot" cx="' + (NW - 6) + '" cy="6" r="4"/>' : '') + '</g>';
    });
    part('xe-g').innerHTML = s;
    part('xe-legend').innerHTML = sheets.map(function(k2) { return '<span>' + dot(k2) + esc(k2) + '</span>'; }).join('') +
      '<span><span class="xe-dot" style="background:var(--xe-up)"></span>Feeds selected</span><span><span class="xe-dot" style="background:var(--xe-down)"></span>Uses selected</span>' + (Object.keys(flagsOf).length ? '<span><span class="xe-dot" style="background:var(--accent-red)"></span>Has a finding</span>' : '') + '<span>★ KPI · ↻ carries forward column to column · drag to pan, Ctrl+scroll or +/− to zoom</span>';
  }
  function applyView() { part('xe-g').setAttribute('transform', 'translate(' + vw.x + ',' + vw.y + ') scale(' + vw.k + ')'); }
  function fit(rowIdx) {
    var st = part('xe-stage'), W = st.clientWidth, H = st.clientHeight;
    if (!W || !H) return;
    var x0 = PAD - 10, y0 = PAD - 20, x1 = layout.w, y1 = layout.h;
    if (rowIdx != null) {
      var set = [rowIdx].concat(mode !== 'down' ? rowUp(rowIdx) : [], mode !== 'up' ? rowDn(rowIdx) : []);
      x0 = y0 = Infinity; x1 = y1 = -Infinity;
      set.forEach(function(i) { var r = R[i]; x0 = Math.min(x0, r.x); y0 = Math.min(y0, r.y); x1 = Math.max(x1, r.x + NW); y1 = Math.max(y1, r.y + NH); });
      x0 -= 30; y0 -= 30; x1 += 30; y1 += 30;
    }
    vw.k = Math.max(0.15, Math.min(1.1, W / (x1 - x0), H / (y1 - y0)));
    vw.x = (W - (x1 - x0) * vw.k) / 2 - x0 * vw.k; vw.y = (H - (y1 - y0) * vw.k) / 2 - y0 * vw.k;
    applyView();
  }
  function highlight() {
    var g = part('xe-g'), up = {}, dn = {};
    if (sel != null) {
      if (mode !== 'down') rowUp(sel).forEach(function(i) { up[i] = 1; });
      if (mode !== 'up') rowDn(sel).forEach(function(i) { dn[i] = 1; });
    }
    g.classList.toggle('xe-dim', sel != null);
    g.querySelectorAll('.xe-node').forEach(function(el) {
      var i = +el.dataset.row;
      el.classList.toggle('xe-sel', i === sel); el.classList.toggle('xe-u', !!up[i]); el.classList.toggle('xe-d', !!dn[i]);
      el.classList.toggle('xe-ai', !!aiRows[i]);
    });
    g.querySelectorAll('.xe-edge').forEach(function(el) {
      var a = +el.dataset.a, b = +el.dataset.b;
      el.classList.toggle('xe-u', (up[a] || a === sel) && (up[b] || b === sel) && !(a === sel && dn[b]));
      el.classList.toggle('xe-d', (dn[a] || a === sel) && (dn[b] || b === sel) && !(b === sel && up[a]));
    });
    renderSide(up, dn);
  }
  function miniList(ids) {
    return '<div class="xe-mini">' + ids.sort(function(a, b) { return R[a].layer - R[b].layer || R[a].row - R[b].row; }).map(function(i) {
      return '<button type="button" data-row="' + i + '">' + dot(R[i].sheet) + '<span>' + esc(R[i].label) + '</span><span class="xe-mono">' + esc(fmt(lastCell(R[i]))) + '</span></button>';
    }).join('') + '</div>';
  }
  function renderSide(up, dn) {
    var side = part('xe-side');
    if (sel == null) {
      side.innerHTML = '<h5>Click any row</h5><p class="xe-muted">Each box is one row of the model, with its columns folded together. Inputs sit on the left and results on the right. Click a row to light up what feeds it and what it feeds, then dig in to trace a single cell.</p>';
      return;
    }
    var r = R[sel], u = Object.keys(up).map(Number), d = Object.keys(dn).map(Number), c = C[state.cell].r === r ? C[state.cell] : lastCell(r);
    side.innerHTML =
      '<div><span class="xe-chip">' + dot(r.sheet) + esc(r.sheet) + ' · <span class="xe-mono">' + esc(rangeOf(r.cells)) + '</span></span>' +
      '<h5>' + esc(r.label) + '</h5><div class="xe-valrow"><span class="xe-mono">' + esc(fmt(c)) + '</span>' + spark(r.cells) + '</div></div>' +
      '<button type="button" class="xe-primary" data-dig="' + c.i + '">Dig in: trace ' + esc(c.ref) + ' →</button>' +
      (flagsOf[sel] ? '<p class="xe-flags">⚑ ' + esc(flagText(flagsOf[sel])) + '</p>' : '') + askBtn('row') +
      (r.cells.length > 1 ? '<div><p class="xe-h">Or pick a column</p><div class="xe-gcells xe-flat">' + r.cells.map(function(i) {
        return '<button type="button" data-dig="' + i + '" title="' + esc(fmt(C[i])) + '"' + (i === c.i ? ' aria-current="true"' : '') + '>' + esc(C[i].ref) + '</button>';
      }).join('') + '</div></div>' : '') +
      '<div class="xe-toggle" role="group" aria-label="Show"><button type="button" data-mode="both" aria-pressed="' + (mode === 'both') + '">Both ways</button><button type="button" data-mode="up" aria-pressed="' + (mode === 'up') + '">What feeds it</button><button type="button" data-mode="down" aria-pressed="' + (mode === 'down') + '">What it feeds</button></div>' +
      (mode !== 'down' ? '<div><p class="xe-h xe-uptxt">Feeds it · ' + u.length + ' rows</p>' + (u.length ? miniList(u) : '<p class="xe-empty">Nothing. This is a starting input.</p>') + '</div>' : '') +
      (mode !== 'up' ? '<div><p class="xe-h xe-dntxt">It feeds · ' + d.length + ' rows</p>' + (d.length ? miniList(d) : '<p class="xe-empty">Nothing. This is an end result.</p>') + '</div>' : '') +
      '<button type="button" class="xe-link" data-clear="1">Clear selection</button>';
  }
  function selectRow(i, zoom) {
    sel = i;
    if (i != null && C[state.cell].r.idx !== i) state.cell = lastCell(R[i]).i;
    highlight();
    if (zoom && i != null) fit(i);
  }
  function renderMap() {
    if (!drawn) { drawMap(); drawn = true; }
    var r = C[state.cell].r.idx;
    if (sel !== r) selectRow(r, true); else { highlight(); fit(sel); }
  }
  if (mapOn) (function wireMap() {
    var st = part('xe-stage'), drag = null, moved = false;
    st.addEventListener('pointerdown', function(e) {
      if (e.target.closest('.xe-tools')) return;
      drag = { x: e.clientX, y: e.clientY, vx: vw.x, vy: vw.y }; moved = false;
      st.setPointerCapture(e.pointerId);
    });
    st.addEventListener('pointermove', function(e) {
      if (!drag) return;
      var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) { moved = true; st.classList.add('xe-drag'); }
      vw.x = drag.vx + dx; vw.y = drag.vy + dy; applyView();
    });
    st.addEventListener('pointerup', function(e) {
      st.classList.remove('xe-drag');
      var wasDrag = moved; drag = null;
      if (wasDrag || e.target.closest('.xe-tools')) return;
      var el = document.elementFromPoint(e.clientX, e.clientY), n = el && el.closest('.xe-node');
      if (n) selectRow(+n.dataset.row, false); else if (el && el.closest('svg')) selectRow(null);
    });
    st.addEventListener('dblclick', function(e) {
      // pointer capture retargets dblclick to the stage, so hit-test like pointerup does
      var el = document.elementFromPoint(e.clientX, e.clientY), n = el && el.closest('.xe-node');
      if (n) digIn(lastCell(R[+n.dataset.row]).i);
    });
    st.addEventListener('wheel', function(e) {
      if (!(e.ctrlKey || e.metaKey)) return;  // plain scrolling keeps scrolling the report
      e.preventDefault();
      var rect = st.getBoundingClientRect(), mx = e.clientX - rect.left, my = e.clientY - rect.top;
      var k2 = Math.min(2.5, Math.max(0.15, vw.k * Math.exp(-e.deltaY * 0.0015)));
      vw.x = mx - (mx - vw.x) * k2 / vw.k; vw.y = my - (my - vw.y) * k2 / vw.k; vw.k = k2; applyView();
    }, { passive: false });
    st.querySelector('.xe-tools').addEventListener('click', function(e) {
      var b = e.target.closest('button'); if (!b) return;
      if (b.dataset.z === 'fit') { fit(); return; }
      var f = b.dataset.z === 'in' ? 1.25 : 0.8, W = st.clientWidth / 2, H = st.clientHeight / 2, k2 = Math.min(2.5, Math.max(0.15, vw.k * f));
      vw.x = W - (W - vw.x) * k2 / vw.k; vw.y = H - (H - vw.y) * k2 / vw.k; vw.k = k2; applyView();
    });
    part('xe-g').addEventListener('keydown', function(e) {
      var n = e.target.closest('.xe-node');
      if (!n) return;
      if (e.key === 'Enter') { e.preventDefault(); digIn(lastCell(R[+n.dataset.row]).i); }
      else if (e.key === ' ') { e.preventDefault(); selectRow(+n.dataset.row, false); }
    });
    part('xe-side').addEventListener('click', function(e) {
      var b = e.target.closest('button'); if (!b) return;
      if (b.dataset.dig) digIn(+b.dataset.dig);
      else if (b.dataset.row) selectRow(+b.dataset.row, true);
      else if (b.dataset.mode) { mode = b.dataset.mode; highlight(); fit(sel); }
      else if (b.dataset.clear) selectRow(null);
      else if (b.dataset.ask) ask(b);
    });
  })();

  // ---------- Trace ----------
  function groupByRow(list, focus) {
    var g = Object.create(null), order = [];
    list.forEach(function(i) { var r = C[i].r; if (!g[r.key]) { g[r.key] = { r: r, cells: [] }; order.push(g[r.key]); } g[r.key].cells.push(i); });
    order.forEach(function(x) { x.cells.sort(function(a, b) { return C[a].col - C[b].col; }); });
    order.sort(function(a, b) {
      if (a.r.sheet === b.r.sheet) return a.r.row - b.r.row;
      if (a.r.sheet === focus.sheet) return -1;
      if (b.r.sheet === focus.sheet) return 1;
      return sOrd(a.r.sheet) - sOrd(b.r.sheet);
    });
    return order;
  }
  function bestCell(group, focus) {
    for (var k = 0; k < group.cells.length; k++) if (C[group.cells[k]].col === focus.col) return group.cells[k];
    return group.cells[group.cells.length - 1];
  }
  function groupHtml(gr, focus) {
    var c = C[bestCell(gr, focus)], multi = gr.cells.length > 1;
    var ai = gr.cells.some(function(i) { return aiCells[i]; });
    var h = '<div class="xe-group' + (ai ? ' xe-ai' : '') + '"><button type="button" class="xe-gmain" data-cell="' + c.i + '">' + dot(c.sheet) +
      '<span class="xe-lbl" title="' + esc(c.label) + '">' + esc(c.label) + '</span>' +
      '<span class="xe-val">' + esc(multi ? '' : fmt(c)) + '</span>' +
      '<span class="xe-gsub"><span class="xe-mono">' + esc(c.sheet === focus.sheet ? '' : c.sheet + '!') + esc(rangeOf(gr.cells)) + '</span>' + (multi ? spark(gr.cells) : '') + badge(c) + '</span></button>';
    if (multi) h += '<div class="xe-gcells">' + gr.cells.map(function(i) { return '<button type="button" data-cell="' + i + '" title="' + esc(fmt(C[i])) + '">' + esc(C[i].ref) + '</button>'; }).join('') + '</div>';
    return h + '</div>';
  }
  function formulaHtml(c) {
    if (!c.f) return '<div class="xe-formula">' + esc(fmt(c)) + '  <span class="xe-muted">(typed-in value, no formula)</span></div>';
    // group 1 is the character before the ref (no lookbehind: older Safari can't parse it)
    var re = /(^|[^A-Za-z0-9_.$'])((?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?(?![A-Za-z0-9_(])/g, out = '', last = 0, m;
    while ((m = re.exec(c.f))) {
      out += esc(c.f.slice(last, m.index) + m[1]); last = re.lastIndex;
      var txt = m[0].slice(m[1].length), sheet = c.sheet, ref = txt, bang = txt.lastIndexOf('!');
      if (bang >= 0) { sheet = txt.slice(0, bang).replace(/^'|'$/g, '').replace(/''/g, "'"); ref = txt.slice(bang + 1); }
      ref = ref.replace(/\$/g, '');
      var t = byId[sheet + '!' + ref];
      out += (ref.indexOf(':') < 0 && t) ? '<a role="button" tabindex="0" data-cell="' + t.i + '">' + esc(txt) + '</a>' : '<span class="xe-rng">' + esc(txt) + '</span>';
    }
    return '<div class="xe-formula">' + out + esc(c.f.slice(last)) + '</div>';
  }
  function renderTrace() {
    var c = C[state.cell];
    if (state.trail.indexOf(c.i) < 0) { state.trail.push(c.i); if (state.trail.length > 8) state.trail.shift(); }
    part('xe-crumbs').innerHTML =
      (mapOn ? '<button type="button" class="xe-back" data-back="1">← Row map</button>' : '') + '<span>Trail</span>' +
      state.trail.map(function(i) { return '<button type="button" data-cell="' + i + '">' + esc(C[i].label) + ' <span class="xe-mono">' + esc(C[i].ref) + '</span></button>'; }).join('<span aria-hidden="true">›</span>');
    var ups = groupByRow(c.pre, c), dns = groupByRow(c.suc, c);
    part('xe-upn').textContent = c.pre.length + ' cell' + (c.pre.length === 1 ? '' : 's');
    part('xe-dnn').textContent = c.suc.length + ' cell' + (c.suc.length === 1 ? '' : 's');
    part('xe-upl').innerHTML = ups.length ? ups.map(function(g) { return groupHtml(g, c); }).join('') : '<div class="xe-empty">Nothing feeds this cell. It is a starting input.</div>';
    part('xe-dnl').innerHTML = dns.length ? dns.map(function(g) { return groupHtml(g, c); }).join('') : '<div class="xe-empty">Nothing uses this cell. It is an end result.</div>';

    var anc = cellUp(c.i), desc = cellDn(c.i);
    var inputs = anc.filter(function(i) { return !C[i].f && C[i].pre.length === 0; });
    var inRows = groupByRow(inputs, c), kp = desc.filter(function(i) { return kpiOf[i]; });
    var h = '<div class="xe-ftop"><span class="xe-chip">' + dot(c.sheet) + esc(c.sheet) + ' · <span class="xe-mono">' + esc(c.ref) + '</span></span>' + badge(c) + '</div>' +
      '<div><h5 class="xe-ftitle">' + esc(c.label) + '</h5><div class="xe-big">' + esc(fmt(c)) + '</div></div>' +
      (function() { var fs = (flagsOf[c.r.idx] || []).filter(function(f) { return f.cell === c.id; }); return fs.length ? '<p class="xe-flags">⚑ ' + esc(flagText(fs)) + '</p>' : ''; })() +
      askBtn('cell') +
      (c.r.cells.length > 1 ? '<div><p class="xe-h">Same row, other columns</p><div class="xe-gcells xe-flat">' + c.r.cells.map(function(i) {
        return '<button type="button" data-cell="' + i + '" title="' + esc(fmt(C[i])) + '"' + (i === c.i ? ' aria-current="true"' : '') + '>' + esc(C[i].ref) + '</button>';
      }).join('') + '</div></div>' : '') + formulaHtml(c) +
      '<div class="xe-facts"><div><b>' + anc.length + '</b><span>cells upstream, from ' + inputs.length + ' typed-in values</span></div>' +
      '<div><b>' + desc.length + '</b><span>cells downstream, reaching ' + kp.length + ' KPI' + (kp.length === 1 ? '' : 's') + '</span></div></div>';
    if (inRows.length) h += '<div><p class="xe-h">Driven by these inputs</p><div class="xe-pills">' + inRows.slice(0, 14).map(function(g) {
      var x = C[bestCell(g, c)];
      return '<button type="button" class="xe-pill" data-cell="' + x.i + '">' + dot(x.sheet) + esc(x.label) + (g.cells.length > 1 ? ' <span class="xe-mono">×' + g.cells.length + '</span>' : '') + '</button>';
    }).join('') + (inRows.length > 14 ? '<span class="xe-chip">+' + (inRows.length - 14) + ' more</span>' : '') + '</div></div>';
    if (kp.length) h += '<div><p class="xe-h">Flows into these KPIs</p><div class="xe-pills">' + kp.map(function(i) {
      return '<button type="button" class="xe-pill" data-cell="' + i + '">' + esc(kpiOf[i].name) + ' <span class="xe-mono">' + esc(fmt(C[i])) + '</span></button>';
    }).join('') + '</div></div>';
    var kAll = kpiList.filter(function(k) { return byId[k.cell]; });
    if (kAll.length) h += '<div><p class="xe-h">Jump to a KPI</p><div class="xe-pills">' + kAll.map(function(k) {
      return '<button type="button" class="xe-pill" data-cell="' + byId[k.cell].i + '">' + esc(k.name) + '</button>';
    }).join('') + '</div></div>';
    part('xe-focus').innerHTML = h;
  }
  var traceEl = part('xe-trace');
  function traceAct(e) {
    var b = e.target.closest('[data-cell],[data-back],[data-ask]');
    if (!b) return;
    if (b.dataset.back) { setView('map'); return; }
    if (b.dataset.ask) { ask(b); return; }
    focusCell(+b.dataset.cell);
  }
  traceEl.addEventListener('click', traceAct);
  traceEl.addEventListener('keydown', function(e) { if (e.key === 'Enter' && e.target.matches('a[data-cell]')) traceAct(e); });

  var det = root.closest('details');
  if (det) det.addEventListener('toggle', function() { if (det.open && state.view === 'map' && drawn) fit(sel); });

  var strip = root.querySelector('.xe-kpis');
  if (strip) strip.addEventListener('click', function(e) { var b = e.target.closest('button[data-cell]'); if (b) digIn(+b.dataset.cell); });

  // ---------- API ----------
  // Highlight cells the assistant points at; trace/drivers open Trace, anything else selects the row on the map.
  function focusIds(ids, how) {
    aiCells = Object.create(null); aiRows = Object.create(null);
    var first = null;
    (Array.isArray(ids) ? ids : []).forEach(function(id) {
      var c = byId[id];
      if (!c) return;
      aiCells[c.i] = 1; aiRows[c.r.idx] = 1;
      if (first === null) first = c.i;
    });
    if (first === null) { if (state.view === 'trace') renderTrace(); else if (drawn) highlight(); return; }
    if (how === 'trace' || how === 'drivers' || !mapOn) digIn(first);
    else { state.cell = first; setView('map'); }
  }

  setView(mapOn ? 'map' : 'trace');
  return { focus: focusIds };
  }

  window.XlensExplorer = { mount: mount };

  // The HTML report: mount once from its embedded graph and KPI list.
  var reportRoot = document.getElementById('xe-root');
  if (reportRoot && typeof graphData !== 'undefined' && !window.__xlensMounted) {
    window.__xlensMounted = true;
    var reportKpis = [];
    try { reportKpis = JSON.parse(document.getElementById('xe-kpis').textContent) || []; } catch (e) { reportKpis = []; }
    mount(reportRoot, {
      nodes: graphData.nodes || [], links: graphData.links || [],
      kpis: reportKpis.map(function(k) { return { name: k.name, cell: k.cell, scenarios: [] }; }),
      findings: []
    }, {});
  }
})();
