/* Commander Screen: live operational map, ops log, reference data, urgent alerts, thin commands. */
const App = { meta: null, view: 'map', tickets: new Map(), selTicket: null, mapKit: null, es: null };
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const NUM = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const fmtN = (n) => (n === null || n === undefined || n === '' ? '—' : NUM.format(n));
function fmtDate(s, withTime = true) {
  if (!s) return '—';
  const d = new Date(String(s).replace(' ', 'T'));
  if (isNaN(d)) return s;
  const p = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}/${p(d.getMonth() + 1)}/${p(d.getDate())}` + (withTime ? ` ${p(d.getHours())}:${p(d.getMinutes())}` : '');
}
function fmtLen(m) { if (!m && m !== 0) return '—'; return m >= 1000 ? `${NUM.format(m / 1000)} كم` : `${NUM.format(Math.round(m))} م`; }
function fmtHours(h) { if (h === null || h === undefined) return '—'; if (h < 1) return `${Math.round(h * 60)} دقيقة`; return `${NUM.format(h)} ساعة`; }
function ago(s) {
  if (!s) return '';
  const h = (Date.now() - new Date(String(s).replace(' ', 'T'))) / 36e5;
  if (h < 1) return `منذ ${Math.max(1, Math.round(h * 60))} دقيقة`;
  if (h < 48) return `منذ ${Math.round(h)} ساعة`;
  return `منذ ${Math.round(h / 24)} يوم`;
}
const pill = (cls, text) => `<span class="pill ${cls}">${esc(text)}</span>`;
const prioPill = (p, label) => pill('p-' + p, label || (App.meta?.priorities || {})[p] || p);
const statusPill = (s, label) => pill('s-' + s, label || (App.meta?.statuses || {})[s] || s);
const typePill = (f, label) => pill('t-' + f, label || (App.meta?.fax_types || {})[f] || f);
const availPill = (a) => (a ? pill('a-' + a, (App.meta?.availability || {})[a] || a) : '<span class="muted">—</span>');

async function api(path, opts = {}) {
  const o = { method: opts.method || 'GET', headers: {} };
  if (opts.body !== undefined) { o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(opts.body); }
  let res;
  try { res = await fetch(path, o); } catch (e) { toast('تعذر الاتصال بشاشة القائد', 'err'); throw e; }
  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('json') ? await res.json() : await res.text();
  if (res.status === 401 && !path.startsWith('/api/auth/')) {
    location.href = '/login?next=' + encodeURIComponent(location.pathname + location.hash);
    const err = new Error('unauthorized'); err.status = 401; throw err;
  }
  if (!res.ok) {
    const msg = data && data.detail ? data.detail : 'حدث خطأ';
    if (!opts.silent) toast(msg, 'err');
    const err = new Error(msg); err.status = res.status; err.data = data; throw err;
  }
  return data;
}

function toast(msg, kind = '', ms = 3800) {
  const el = document.createElement('div');
  el.className = 'toast ' + kind; el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), ms);
}

function modal({ title, body, footer = '', wide = false, urgent = false, onClose }) {
  const bg = document.createElement('div');
  bg.className = 'modal-bg';
  bg.innerHTML = `<div class="modal ${wide ? 'wide' : ''}"><div class="modal-h ${urgent ? 'urgent' : ''}"><span>${title}</span><button class="x" data-close>×</button></div>
    <div class="modal-b">${body}</div>${footer ? `<div class="modal-f">${footer}</div>` : ''}</div>`;
  const close = () => { bg.remove(); document.removeEventListener('keydown', onKey); onClose && onClose(); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  bg.addEventListener('click', (e) => { if (e.target === bg || e.target.closest('[data-close]')) close(); });
  document.addEventListener('keydown', onKey);
  $('#modalRoot').appendChild(bg);
  return { el: bg, close };
}

function beep() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    [0, 0.22, 0.44, 0.66].forEach((t) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = 'square'; o.frequency.value = t % 0.44 === 0 ? 988 : 784;
      g.gain.setValueAtTime(0.09, ctx.currentTime + t);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + 0.18);
      o.connect(g).connect(ctx.destination);
      o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.2);
    });
    setTimeout(() => ctx.close(), 1400);
  } catch (e) { /* audio unavailable */ }
}

/* ================= urgent alerts ================= */
async function checkAlerts() {
  try {
    const items = await api('/api/alerts?unseen_only=true', { silent: true });
    items.forEach(showAlert);
  } catch (e) { }
}

function refreshAlertBadge(n) {
  const b = $('#alertsBadge');
  if (!b) return;
  b.hidden = !n;
  b.textContent = n > 9 ? '9+' : n;
}

async function openAlerts() {
  try {
    const items = await api('/api/alerts?unseen_only=true', { silent: true });
    const body = items.length ? items.map((a) => {
      const p = a.payload || {};
      const related = (p.related || []).slice(0, 3).map((r) =>
        `<div class="muted">↳ ${esc(r.fax_no || '')} · ${esc(r.date || '')} — ${esc(r.cause || '')}</div>`).join('');
      return `<div class="alert-row">
        <div style="flex:1">
          <div style="font-weight:700">${esc(p.title || a.title || 'تنبيه عاجل')}</div>
          <div class="muted" style="margin-top:3px">${esc((p.message || '').slice(0, 200))}${(p.message || '').length > 200 ? '…' : ''}</div>
          ${related}
          <div class="muted" style="margin-top:4px">${fmtDate(a.created_at)} · ${esc(a.kind === 'repeat_fault' ? 'عطل متكرر' : 'بلاغ حرج')}</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:6px;align-items:flex-start">
          ${p.ticket_id ? `<button class="btn small" data-open="${p.ticket_id}">فتح</button>` : ''}
          <button class="btn small primary" data-ack="${a.id}">تم الاطلاع</button>
        </div></div>`;
    }).join('') : '<div class="empty">لا توجد تنبيهات غير مقروءة — كل شيء تحت السيطرة</div>';
    const m = modal({ title: '🔔 التنبيهات', wide: true, body });
    $$('[data-ack]', m.el).forEach((b) => b.onclick = async () => {
      try {
        await api(`/api/alerts/${b.dataset.ack}/ack`, { method: 'POST', body: { ticket_id: null } });
        b.closest('.alert-row').remove();
        refreshKpis();
        if (!$('.alert-row', m.el)) { m.close(); }
      } catch (e) { }
    });
    $$('[data-open]', m.el).forEach((b) => b.onclick = () => { m.close(); openTicket(+b.dataset.open); });
  } catch (e) { toast('تعذر تحميل التنبيهات', 'err'); }
}

function showAlert(a) {
  if (!a || !a.id) return;
  beep();
  const p = a.payload || {};
  const related = (p.related || []).map((r) => `<tr><td>${esc(r.fax_no || '')}</td><td>${esc(r.date || '')}</td>
    <td>${esc(r.cause || '—')}</td><td>${esc(r.resolution || '—')}</td></tr>`).join('');
  const body = `<div class="urgent-box">
    <div style="font-size:16px;font-weight:800;margin-bottom:6px">🚨 ${esc(p.title || a.title || 'تنبيه عاجل')}</div>
    <div style="font-size:13px;line-height:1.8">${esc(p.message || '')}</div>
    ${related ? `<table class="tbl" style="margin-top:10px"><tr><th>الفاكس</th><th>تاريخ آخر إصلاح</th><th>السبب</th><th>الإجراءات المتخذة</th></tr>${related}</table>` : ''}
    ${p.ticket ? `<div class="muted" style="margin-top:8px">${esc(p.ticket.fax_no || '')} — ${esc(p.ticket.title || '')}</div>` : ''}
  </div>`;
  const m = modal({ title: '🚨 تنبيه عاجل', urgent: true, wide: true, body,
    footer: `<button class="btn primary" id="ackAlert">تم الاطلاع</button>
             ${p.ticket_id ? `<button class="btn" id="openAlertTicket">فتح العملية</button>` : ''}` });
  $('#ackAlert', m.el).onclick = async () => {
    try { await api(`/api/alerts/${a.id}/ack`, { method: 'POST', body: { ticket_id: p.ticket_id || null } }); } catch (e) { }
    m.close(); refreshKpis();
  };
  const ob = $('#openAlertTicket', m.el);
  if (ob) ob.onclick = () => { m.close(); openTicket(p.ticket_id); };
}

/* ================= header / status ================= */
async function refreshKpis() {
  try {
    const [d, st] = await Promise.all([api('/api/dashboard', { silent: true }), api('/api/status', { silent: true })]);
    $('#topKpis').innerHTML = `
      <div class="k red" data-gov="ops" data-f="fault"><b>${d.active_faults}</b><span>أعطال نشطة</span></div>
      <div class="k green" data-gov="ops" data-f="project"><b>${d.active_projects}</b><span>مشروعات جارية</span></div>
      <div class="k amber" data-gov="ops" data-f="coord"><b>${d.overdue_coordination}</b><span>تنسيق متأخر</span></div>
      <div class="k red" data-gov="ops" data-f="critical"><b>${d.critical_open}</b><span>بلاغات حرجة</span></div>
      <div class="k blue"><b>${d.teams_on_mission}</b><span>مفارز في مأمورية</span></div>`;
    $$('#topKpis [data-gov]').forEach((el) => el.onclick = () => goOps(el.dataset.f));
    refreshAlertBadge(d.unseen_alerts);
    updateConn(st);
  } catch (e) { updateConn({ connected: false }); }
}

function updateConn(st) {
  const box = $('#connBox');
  const ok = !!st.connected;
  box.className = 'conn ' + (ok ? 'ok' : 'bad');
  $('#connText').textContent = ok ? `متصل — ${st.station_device || 'المحطة'}` : 'غير متصل بالمحطة';
  $('#connText').title = st.station_url || '';
  $('#lastUpdate').textContent = st.last_ok ? ` · آخر تحديث ${fmtDate(st.last_ok)}` : '';
}

function tickClock() {
  const d = new Date();
  const days = ['الأحد', 'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت'];
  const p = (x) => String(x).padStart(2, '0');
  $('#clock').textContent = `${days[d.getDay()]} ${d.getFullYear()}/${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/* ================= router ================= */
function go(view, arg) {
  App.view = view;
  $$('#viewnav a').forEach((a) => a.classList.toggle('active', a.dataset.view === view));
  const main = $('#app');
  if (App.mapKit && view !== 'map') { try { App.mapKit.destroy(); } catch (e) { } App.mapKit = null; }
  if (view === 'map') renderMapView(main);
  else if (view === 'ops') renderOps(main, arg || {});
  else if (view === 'ref') renderRef(main);
}

function hashRoute() {
  const h = location.hash || '#/map';
  const [, v, arg] = h.split('/');
  if (v === 'ticket') { openTicket(+arg); return; }
  go(v === 'ops' || v === 'ref' ? v : 'map');
}
window.addEventListener('hashchange', hashRoute);

/* ================= map view ================= */
const CABLE_COLOR = (c) => (!c ? '#818cf8' : c.startsWith('copper') ? '#a1887f' : c.endsWith('96') ? '#ce93d8' : c.endsWith('48') ? '#64b5f6' : '#4db6ac');
const TYPE_COLOR = { fault: '#ef4444', project: '#22c55e', coordination: '#f59e0b' };

function renderMapView(main) {
  main.innerHTML = `<div class="split">
    <div class="map-col"><div id="mapBox"></div>
      <div class="panel" style="max-height:180px;overflow:auto" id="mapList"><h3>العمليات الممررة للقيادة</h3><div id="mapListBody" class="empty">جاري التحميل…</div></div>
    </div>
    <div class="side-col">
      <div id="detailHost" style="flex:1;min-height:0;display:flex;flex-direction:column">
        <div class="panel" style="flex:1"><h3>التفاصيل</h3><div class="empty">اختر عملية من الخريطة أو القائمة لعرض تفاصيلها وأوامر القيادة</div></div>
      </div>
      <div class="panel act-panel"><h3>آخر المستجدات</h3><div id="activityFeed" class="empty">جاري التحميل…</div></div>
    </div>
  </div>`;
  initMap();
  loadMapList();
  loadActivity();
  setTimeout(() => App.mapKit && App.mapKit.map.invalidateSize(), 60);
}

async function loadActivity() {
  const el = $('#activityFeed');
  if (!el) return;
  try {
    const items = await api('/api/activity', { silent: true });
    el.innerHTML = items.length ? items.map((a) => `<div class="act-item" data-tid="${a.ticket_id || ''}" style="cursor:pointer">
        <div class="a1"><span class="mono">${esc(a.fax_no || '')}</span><span class="a-label">${esc(a.label || '')}</span></div>
        <div class="a2 muted">${esc(a.title || '')}</div>
        <div class="a3 muted">${esc(a.actor || '')} · ${ago(a.at)}</div></div>`).join('')
      : '<div class="empty">لا يوجد تتبع بعد</div>';
    $$('.act-item', el).forEach((it) => it.onclick = () => { if (it.dataset.tid) openTicket(+it.dataset.tid); });
  } catch (e) {
    el.innerHTML = '<div class="empty">تعذر تحميل المستجدات</div>';
  }
}

async function initMap() {
  const el = $('#mapBox');
  if (!el || App.mapKit) return;
  const meta = App.meta?.labels?.settings || {};
  const map = L.map(el, { zoomControl: true, preferCanvas: true, attributionControl: false })
    .setView([meta.map_center_lat ?? 30.05, meta.map_center_lon ?? 31.24], meta.map_zoom ?? 11);
  el.setAttribute('dir', 'ltr');
  const renderer = L.canvas({ padding: 0.3 });
  const basemap = L.layerGroup();
  const style = (f) => {
    const c = f.properties.c;
    const s = { motorway: '#f87171', trunk: '#fb923c', primary: '#facc15', secondary: '#d4d4d8', tertiary: '#e5e7eb', rail: '#9ca3af', river: '#60a5fa' }[c] || '#e5e7eb';
    const w = { motorway: 3.2, trunk: 2.8, primary: 2.2, secondary: 1.6, tertiary: 1, rail: 1, river: 6 }[c] || 1;
    return { color: s, weight: w, opacity: c === 'river' ? 0.8 : 0.9, dashArray: c === 'rail' ? '4 4' : null, interactive: false };
  };
  const eg = L.geoJSON(null, { style, renderer });
  const ca = L.geoJSON(null, { style, renderer });
  basemap.addLayer(eg); basemap.addLayer(ca);
  Promise.all([
    fetch('/static/map/egypt_roads.geojson').then((r) => r.json()),
    fetch('/static/map/cairo_roads.geojson').then((r) => r.json()),
  ]).then(([e, c]) => { eg.addData(e); ca.addData(c); });
  basemap.addTo(map);
  const network = L.layerGroup().addTo(map);
  const tickets = L.layerGroup().addTo(map);
  L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);
  App.mapKit = { map, network, tickets, destroy: () => map.remove() };
  refreshMapLayers();
}

async function refreshMapLayers() {
  if (!App.mapKit) return;
  try {
    const data = await api('/api/map/layers', { silent: true });
    const { network, tickets, map } = App.mapKit;
    network.clearLayers(); tickets.clearLayers();
    for (const f of data.network.features) {
      const p = f.properties;
      if (p.kind === 'route') {
        L.geoJSON(f, { style: { color: CABLE_COLOR(p.cable_type), weight: 4, opacity: 0.85 } })
          .bindPopup(`<b>${esc(p.code)}</b> — ${esc(p.name)}<br>الكابل: ${esc(p.cable_type || '—')}<br>الطول: ${fmtLen(p.length_m)}<br>الجهات: ${esc(p.parties || '—')}`)
          .bindTooltip(p.code, { sticky: true }).addTo(network);
      } else {
        const ll = [f.geometry.coordinates[1], f.geometry.coordinates[0]];
        L.circleMarker(ll, { radius: p.kind === 'exchange' ? 7 : 4, color: p.kind === 'exchange' ? '#fbbf24' : '#cbd5e1', fillColor: '#334155', fillOpacity: 1, weight: 2 })
          .bindPopup(`<b>${esc(p.code)}</b><br>${esc(p.name)}<br><span class="muted">${esc(p.kind_label || '')}</span>`).bindTooltip(p.code).addTo(network);
      }
    }
    for (const f of data.tickets.features) {
      const p = f.properties;
      const color = p.status === 'closed' ? '#64748b' : (TYPE_COLOR[p.fax_type] || '#94a3b8');
      const popup = `<b>${esc(p.fax_no)}</b> ${pill('t-' + p.fax_type, p.type_label)}<br>${esc(p.title)}<br>
        ${pill('s-' + p.status, p.status_label)} ${prioPill(p.priority, p.priority_label)}
        ${p.overdue ? ' ' + pill('overdue', 'متأخر') : ''}<br><span class="muted">${fmtDate(p.received_at)}</span>
        <br><a href="#/ticket/${p.id}">فتح التفاصيل ←</a>`;
      if (f.geometry.type === 'Point') {
        const ll = [f.geometry.coordinates[1], f.geometry.coordinates[0]];
        L.circleMarker(ll, { radius: p.status === 'closed' ? 5 : p.priority === 'critical' ? 10 : 8, color: '#0f172a', weight: 2, fillColor: color, fillOpacity: 0.95 })
          .bindPopup(popup).on('click', () => openTicket(p.id)).addTo(tickets);
      } else {
        L.geoJSON(f, { style: { color, weight: 6, opacity: 0.85, dashArray: p.fax_type === 'project' ? '8 6' : null } })
          .bindPopup(popup).on('click', () => openTicket(p.id)).addTo(tickets);
      }
    }
    // fit to tickets if any
    if (tickets.getLayers().length) {
      const b = tickets.getBounds();
      if (b.isValid()) map.fitBounds(b.pad(0.15), { maxZoom: 13 });
    }
  } catch (e) { }
}

async function loadMapList() {
  const body = $('#mapListBody');
  if (!body) return;
  try {
    const items = await api('/api/tickets?scope=active', { silent: true });
    App.tickets = new Map(items.map((t) => [t.id, t]));
    body.innerHTML = items.length ? items.map(ticketRow).join('') : '<div class="empty">لا توجد عمليات ممررة بعد</div>';
    $$('.ticket-row', body).forEach((el) => el.onclick = () => openTicket(+el.dataset.id));
  } catch (e) {
    body.innerHTML = '<div class="empty">تعذر تحميل القائمة — المحطة غير متصلة</div>';
  }
}

function ticketRow(t) {
  return `<button class="ticket-row" data-id="${t.id}">
    <div class="t1"><span class="fax mono">${esc(t.fax_no)}</span><span>${typePill(t.fax_type, t.type_label)} ${prioPill(t.priority, t.priority_label)}</span></div>
    <div class="ti">${esc(t.title)}</div>
    <div class="m">${statusPill(t.status, t.status_label)} ${t.wait?.overdue ? pill('overdue', 'تنسيق متأخر') : ''}
      <span>${esc(t.location_text || '')}</span><span class="muted">${ago(t.received_at)}</span>${t.command_seen_at ? '<span class="muted">✓ مقروء</span>' : ''}</div>
  </button>`;
}

function renderTicketList(container, items) {
  container.innerHTML = items.length ? items.map(ticketRow).join('') : '<div class="empty">لا توجد عمليات</div>';
  $$('.ticket-row', container).forEach((el) => el.onclick = () => openTicket(+el.dataset.id));
}

/* ================= ticket detail ================= */
async function openTicket(tid) {
  if (!tid) return;
  try {
    const t = await api(`/api/tickets/${tid}`, { silent: true });
    App.selTicket = t;
    renderDetail(t);
    if (!App._seenDone) App._seenDone = new Set();
    if (!App._seenDone.has(tid)) {
      App._seenDone.add(tid);
      api('/api/commands/seen', { method: 'POST', body: { ticket_id: tid }, silent: true }).catch(() => { });
    }
  } catch (e) {
    toast('العملية غير متاحة محليًا بعد', 'warn');
  }
}

function detailEditing() {
  const ae = document.activeElement;
  if (!ae || ae === document.body) return false;
  return !!(ae.closest && ae.closest('#detailHost, .modal-b'));
}

function estimateHtml(e) {
  if (!e) return '';
  const rows = [
    ['الطول المقاس', fmtLen(e.measured_length_m) + (e.length_source ? ` (${e.length_source === 'map' ? 'خريطة' : 'يدوي'})` : '')],
    ['نوع الكابل', esc(e.cable_type || '—')], ['الألياف', fmtN(e.fiber_count)],
    ['طول الكابل الكلي (+احتياطي)', fmtLen(e.total_cable_m)],
    ['علب الدمج', fmtN(e.splice_closures)], ['لحامات Fusion', fmtN(e.fusion_splices)],
    ['نقاط الربط', fmtN(e.connection_points)], ['Media Converters', fmtN(e.media_converters)],
    ['ساعات تنقل', fmtN(e.travel_hours)], ['ساعات مد', fmtN(e.laying_hours)],
    ['ساعات لحام', fmtN(e.splicing_hours)], ['ساعات اختبار', fmtN(e.testing_hours)],
    ['معامل الصعوبة', fmtN(e.difficulty_factor)],
    ['الزمن التقديري', `<b>${fmtN(e.estimated_hours)} ساعة ≈ ${fmtN(e.estimated_days)} يوم عمل</b>`],
  ];
  const equip = (e.equipment || []).map((x) => `<tr><td>${esc(x.name)}</td><td>${fmtN(x.quantity)} ${esc(x.unit || '')}</td><td>${availPill(x.availability)}</td><td class="muted">${esc(x.reason || '')}</td></tr>`).join('');
  return `<h3 style="margin-top:14px">التقدير الفني</h3>
    <table class="tbl"><tr>${rows.map(([k, v]) => `<th>${k}</th><td>${v}</td>`).join('</tr><tr>')}</table>
    ${equip ? `<table class="tbl"><tr><th>المعدة / الخامة</th><th>الكمية</th><th>الإتاحة</th><th>ملاحظة</th></tr>${equip}</table>` : ''}`;
}

function needsHtml(t) {
  const needs = t.needs || [];
  if (!needs.length) return '<div class="muted">لا توجد بنود احتياجات</div>';
  const rows = needs.map((n) => `<tr>
    <td>${esc(n.item_name)}<div class="muted">${esc(n.category || '')}</div></td>
    <td>${fmtN(n.quantity)} ${esc(n.unit || '')}</td>
    <td>${availPill(n.availability)}</td>
    <td><div class="need-actions">
      ${['available', 'needs_approval', 'shortage'].map((a) => `<button class="btn small ${n.availability === a ? 'active-avail' : ''}" data-cmd="avail" data-need="${n.id}" data-val="${a}" ${n.availability === a ? 'disabled' : ''}>${(App.meta?.availability || {})[a] || a}</button>`).join('')}
    </div></td></tr>`).join('');
  return `<table class="tbl"><tr><th>البند</th><th>الكمية</th><th>الحالة الحالية</th><th>تصديق القيادة</th></tr>${rows}</table>
    <div class="muted">أوامر التصديق تُنفذ على محطة المشروعات وتظهر للمشغل فورًا.</div>`;
}

function timelineHtml(t) {
  const ups = t.updates || [];
  if (!ups.length) return '<div class="muted">لا يوجد تتبع</div>';
  return `<div class="timeline">${ups.slice().reverse().map((u) => `<div class="tl-item">
    <div><b>${esc(u.new_label || u.new_status || '')}</b>${u.old_label ? ` ← ${esc(u.old_label)}` : ''}</div>
    ${u.notes ? `<div>${esc(u.notes)}</div>` : ''}
    <div class="at">${fmtDate(u.at)} · ${esc(u.actor || '')}</div></div>`).join('')}</div>`;
}

function faxFileHtml(t) {
  if (!t.local_has_file && !t.has_file) return '';
  const url = `/api/tickets/${t.id}/file`;
  const ext = (t.file_name || '').split('.').pop().toLowerCase();
  if (ext === 'pdf') return `<h3 style="margin-top:14px">الفاكس الأصلي</h3><iframe class="fax-view" src="${url}"></iframe>`;
  if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'].includes(ext))
    return `<h3 style="margin-top:14px">الفاكس الأصلي</h3><a href="${url}" target="_blank"><img class="fax-img" src="${url}"></a>`;
  return `<h3 style="margin-top:14px">الفاكس الأصلي</h3><a class="btn" href="${url}" target="_blank">فتح الملف الأصلي</a>`;
}

function captureInputs(root) {
  const dir = $('#dirText', root), pr = $('#prioSel', root);
  const ae = document.activeElement;
  const editing = ae && root.contains(ae) && (ae.id === 'dirText' || ae.id === 'prioSel') ? ae.id : null;
  const sel = editing && ae.selectionStart !== undefined ? [ae.selectionStart, ae.selectionEnd] : null;
  return { dir: dir ? dir.value : undefined, prio: pr ? pr.value : undefined, editing, sel };
}
function restoreInputs(root, st) {
  if (!st) return;
  const dir = $('#dirText', root), pr = $('#prioSel', root);
  if (dir && st.dir !== undefined) dir.value = st.dir;
  if (pr && st.prio !== undefined) pr.value = st.prio;
  if (st.editing) {
    const el = root.querySelector('#' + st.editing);
    if (el) {
      el.focus();
      if (st.sel && el.setSelectionRange) { try { el.setSelectionRange(st.sel[0], st.sel[1]); } catch (e) { } }
    }
  }
}

function renderDetail(t) {
  const host = App.view === 'map' ? $('#detailHost') : null;
  const content = detailHtml(t);
  if (host) {
    const st = captureInputs(host);
    host.innerHTML = `<div class="panel" style="flex:1">${content}</div>`;
    bindDetail(host, t.id);
    restoreInputs(host, st);
    return;
  }
  if (App._detailModal) {
    const mb = $('.modal-b', App._detailModal.el);
    const st = captureInputs(mb);
    mb.innerHTML = content;
    bindDetail(mb, t.id);
    restoreInputs(mb, st);
    return;
  }
  App._detailModal = modal({ title: `${esc(t.fax_no)} — ${esc(t.title)}`, wide: true, body: content,
    footer: '<button class="btn" data-close>إغلاق</button>',
    onClose: () => { App._detailModal = null; } });
  bindDetail(App._detailModal.el, t.id);
}

function detailHtml(t) {
  const st = App.meta?.statuses || {};
  return `<div class="det-head">
      <div>
        <div class="det-title mono">${esc(t.fax_no)}</div>
        <div style="margin-top:4px">${typePill(t.fax_type, t.type_label)} ${statusPill(t.status, t.status_label)} ${prioPill(t.priority, t.priority_label)}
          ${t.wait?.overdue ? pill('overdue', 'تنسيق متأخر') : ''}</div>
      </div>
      <div class="muted">استلم ${fmtDate(t.received_at)} · آخر تحديث ${fmtDate(t.updated_at)}<br>
        ${t.command_seen_at ? `✓ اطّلعت القيادة ${fmtDate(t.command_seen_at)}` : ''} ${t.forwarded_at ? `· سُلّم ${fmtDate(t.forwarded_at)}` : ''}</div>
    </div>
    <div class="kv">
      <div><span class="k">العنوان</span><span class="v">${esc(t.title)}</span></div>
      <div><span class="k">الموقع</span><span class="v">${esc(t.location_text || '—')}</span></div>
      <div><span class="k">الجهة الطالبة</span><span class="v">${esc(t.requesting_party || '—')}</span></div>
      <div><span class="k">الجهة المسؤولة</span><span class="v">${esc(t.responsible_party || '—')}</span></div>
      <div><span class="k">المسار</span><span class="v">${esc(t.route_name || t.route_code || '—')}</span></div>
      <div><span class="k">المفرزة المكلفة</span><span class="v">${esc(t.assigned_team || '—')}</span></div>
      ${t.cause ? `<div><span class="k">سبب العطل</span><span class="v">${esc(t.cause)}</span></div>` : ''}
      ${t.resolution ? `<div><span class="k">الإجراءات / الحل</span><span class="v">${esc(t.resolution)}</span></div>` : ''}
    </div>
    <h3>الملخص التنفيذي</h3>
    <div class="summary-box">${esc(t.summary || '—')}</div>
    ${t.required_action ? `<h3>الإجراء المطلوب</h3><div class="summary-box">${esc(t.required_action)}</div>` : ''}
    ${estimateHtml(t.estimate)}
    <h3>الاحتياجات — تصديق القيادة</h3>
    ${needsHtml(t)}
    <h3>تغيير درجة الأهمية</h3>
    <div style="display:flex;gap:8px;align-items:center">
      <select class="inp fld" id="prioSel">
        ${Object.entries(App.meta?.priorities || {}).map(([k, v]) => `<option value="${k}" ${t.priority === k ? 'selected' : ''}>${esc(v)}</option>`).join('')}
      </select>
      <button class="btn primary" id="prioBtn">تطبيق</button>
    </div>
    <h3>توجيه مكتوب للمحطة</h3>
    <div style="display:flex;gap:8px">
      <input class="inp fld" id="dirText" placeholder="اكتب التوجيه الذي يظهر فورًا لدى مشغل المحطة…" style="flex:1">
      <button class="btn danger" id="dirBtn">إرسال توجيه</button>
    </div>
    <h3>التتبع الزمني</h3>
    ${timelineHtml(t)}
    ${faxFileHtml(t)}
    <div class="muted" style="margin-top:10px">المصدر: محطة المشروعات · ${esc(t.synced_at ? 'مزامنة ' + fmtDate(t.synced_at) : '')}</div>`;
}

function bindDetail(root, tid) {
  $$('[data-cmd="avail"]', root).forEach((b) => b.onclick = async () => {
    b.disabled = true;
    try {
      const r = await api('/api/commands/availability', { method: 'POST', body: { ticket_id: tid, need_id: +b.dataset.need, availability: b.dataset.val } });
      if (r.ticket) { App.selTicket = r.ticket; refreshDetail(); toast('تم تسجيل التصديق على المحطة', 'ok'); }
    } catch (e) { b.disabled = false; }
  });
  const pb = $('#prioBtn', root);
  if (pb) pb.onclick = async () => {
    const pr = $('#prioSel', root).value;
    try {
      const r = await api('/api/commands/priority', { method: 'POST', body: { ticket_id: tid, priority: pr } });
      if (r.ticket) { App.selTicket = r.ticket; refreshDetail(); toast('تم تغيير درجة الأهمية', 'ok'); }
    } catch (e) { }
  };
  const db = $('#dirBtn', root);
  if (db) db.onclick = async () => {
    const msg = $('#dirText', root).value.trim();
    if (msg.length < 3) { toast('نص التوجيه قصير جدًا', 'warn'); return; }
    db.disabled = true;
    try {
      await api('/api/commands/directive', { method: 'POST', body: { ticket_id: tid, message: msg } });
      toast('تم إرسال التوجيه — سيظهر فورًا لدى مشغل المحطة', 'ok');
      $('#dirText', root).value = '';
      refreshKpis();
    } catch (e) { }
    db.disabled = false;
  };
}

function refreshDetail() {
  if (!App.selTicket) return;
  renderDetail(App.selTicket);
  loadMapList();
}

/* ================= ops log ================= */
function goOps(key) {
  const map = { fault: { fax_type: 'fault' }, project: { fax_type: 'project' }, coord: { status: 'awaiting_coordination' }, critical: { priority: 'critical' } };
  App._opsFilter = map[key] || {};
  if ((location.hash || '#/map') === '#/ops') renderOps($('#app'));
  else location.hash = '#/ops';
}

function renderOps(main, arg) {
  const f = App._opsFilter || {};
  App._opsFilter = {};
  main.innerHTML = `<div class="filters">
      <select id="fScope"><option value="active">العمليات النشطة</option><option value="all">الكل</option><option value="closed">المغلقة</option></select>
      <select id="fType"><option value="">كل الأنواع</option>${Object.entries(App.meta?.fax_types || {}).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select>
      <select id="fPrio"><option value="">كل الأولويات</option>${Object.entries(App.meta?.priorities || {}).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select>
      <select id="fStatus"><option value="">كل الحالات</option>${Object.entries(App.meta?.statuses || {}).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select>
      <input id="fQ" placeholder="بحث برقم الفاكس أو العنوان أو الموقع…">
      <button class="btn" id="fGo">تطبيق</button>
    </div>
    <div class="panel" style="padding:0;overflow:auto"><table class="tbl" id="opsTbl">
      <tr><th>رقم الفاكس</th><th>النوع</th><th>العنوان</th><th>الحالة</th><th>الأولوية</th><th>الموقع</th><th>الاستلام</th><th>آخر تحديث</th><th>المفرزة</th><th>مقروء</th></tr>
      <tbody id="opsBody"><tr><td colspan="10" class="empty">جاري التحميل…</td></tr></tbody></table></div>`;
  const load = async () => {
    const p = new URLSearchParams({ scope: $('#fScope').value });
    if ($('#fType').value) p.set('fax_type', $('#fType').value);
    if ($('#fPrio').value) p.set('priority', $('#fPrio').value);
    if ($('#fStatus').value) p.set('status', $('#fStatus').value);
    if ($('#fQ').value.trim()) p.set('q', $('#fQ').value.trim());
    try {
      const items = await api('/api/tickets?' + p, { silent: true });
      App.tickets = new Map(items.map((t) => [t.id, t]));
      $('#opsBody').innerHTML = items.length ? items.map((t) => `<tr data-id="${t.id}" style="cursor:pointer">
        <td class="mono">${esc(t.fax_no)}</td><td>${typePill(t.fax_type, t.type_label)}</td><td>${esc(t.title)}${t.wait?.overdue ? ' ' + pill('overdue', 'متأخر') : ''}</td>
        <td>${statusPill(t.status, t.status_label)}</td><td>${prioPill(t.priority, t.priority_label)}</td>
        <td>${esc(t.location_text || '—')}</td><td>${fmtDate(t.received_at)}</td><td>${fmtDate(t.updated_at)}</td>
        <td>${esc(t.assigned_team || '—')}</td><td>${t.command_seen_at ? '✓' : '<span class="muted">—</span>'}</td></tr>`).join('')
        : '<tr><td colspan="10" class="empty">لا توجد نتائج</td></tr>';
      $$('#opsBody tr[data-id]').forEach((tr) => tr.onclick = () => openTicket(+tr.dataset.id));
    } catch (e) {
      $('#opsBody').innerHTML = '<tr><td colspan="10" class="empty">تعذر التحميل — المحطة غير متصلة</td></tr>';
    }
  };
  App._opsLoad = load;
  $('#fGo').onclick = load;
  $('#fQ').addEventListener('keydown', (e) => { if (e.key === 'Enter') load(); });
  // preselect from KPI click
  if (f.fax_type) $('#fType').value = f.fax_type;
  if (f.priority) $('#fPrio').value = f.priority;
  if (f.status) $('#fStatus').value = f.status;
  if (f.q) $('#fQ').value = f.q;
  if (f.scope) $('#fScope').value = f.scope;
  if (f.coord) { $('#fStatus').value = 'awaiting_coordination'; }
  load();
}

/* ================= reference data ================= */
async function renderRef(main) {
  main.innerHTML = `<div class="stat-row" id="refStats"></div>
  <div class="ref-grid">
    <div class="panel"><h3>المسارات والكابلات القائمة</h3><div id="refRoutes" class="empty">جاري التحميل…</div></div>
    <div class="panel"><h3>الأطقم والمفارز</h3><div id="refTeams" class="empty">جاري التحميل…</div></div>
    <div class="panel"><h3>الوصلات والنقاط (غير المسارات)</h3><div id="refSites" class="empty">جاري التحميل…</div></div>
    <div class="panel"><h3>ملاحظة</h3><div class="muted" style="line-height:1.9">البيانات المرجعية للعرض فقط — تُدار وتُحدَّث من محطة المشروعات وتصل هنا تلقائيًا عبر المزامنة. لتعديلها ارجع لمحطة المشروعات.</div></div>
  </div>`;
  try {
    const r = await api('/api/reference', { silent: true });
    const routes = (r.routes || []).filter((x) => x.kind === 'route');
    const sites = (r.routes || []).filter((x) => x.kind !== 'route');
    const teams = r.teams || [];
    const totalKm = routes.reduce((s, x) => s + (x.length_m || 0), 0) / 1000;
    const onMission = teams.filter((p) => p.status === 'on_mission').length;
    $('#refStats').innerHTML = `
      <div class="stat-card"><b>${routes.length}</b><span>مسار كابل رئيسي</span></div>
      <div class="stat-card"><b>${fmtN(Math.round(totalKm))} كم</b><span>إجمالي أطوال الكابلات</span></div>
      <div class="stat-card"><b>${sites.length}</b><span>وصلة / غرفة / نقطة ربط</span></div>
      <div class="stat-card"><b>${teams.length}</b><span>فرد في الأطقم (${onMission} في مأمورية)</span></div>`;
    $('#refRoutes').innerHTML = routes.length ? `<table class="tbl"><tr><th>الكود</th><th>الاسم</th><th>الكابل</th><th>الطول</th><th>الجهات المشتركة</th></tr>
      ${routes.map((x) => `<tr><td class="mono">${esc(x.code)}</td><td>${esc(x.name)}</td><td>${esc(x.cable_type || '—')}</td><td>${fmtLen(x.length_m)}</td><td>${esc(x.parties || '—')}</td></tr>`).join('')}</table>` : '<div class="empty">لا توجد بيانات</div>';
    $('#refSites').innerHTML = sites.length ? `<table class="tbl"><tr><th>الكود</th><th>الاسم</th><th>النوع</th><th>المسار الأب</th></tr>
      ${sites.map((x) => `<tr><td class="mono">${esc(x.code)}</td><td>${esc(x.name)}</td><td>${esc(x.kind_label || x.kind)}</td><td class="mono">${esc(x.parent_code || '—')}</td></tr>`).join('')}</table>` : '<div class="empty">لا توجد بيانات</div>';
    $('#refTeams').innerHTML = teams.length ? `<table class="tbl"><tr><th>الاسم</th><th>الرتبة</th><th>التخصص</th><th>المفرزة</th><th>الحالة</th><th>الحالية</th></tr>
      ${teams.map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.rank || '—')}</td><td>${esc(p.specialty || '—')}</td><td>${esc(p.team_name || '—')}</td>
        <td>${pill(p.status === 'on_mission' ? 's-in_progress' : p.status === 'available' ? 's-preparing' : 's-closed', p.status_label || p.status)}</td>
        <td class="mono">${esc(p.current_fax || '—')}</td></tr>`).join('')}</table>` : '<div class="empty">لا توجد بيانات</div>';
  } catch (e) {
    ['#refRoutes', '#refSites', '#refTeams'].forEach((s) => { const el = $(s); if (el) el.innerHTML = '<div class="empty">تعذر التحميل — المحطة غير متصلة</div>'; });
  }
}

/* ================= settings ================= */
function openSettings() {
  api('/api/settings', { silent: true }).then((s) => {
    const m = modal({ title: 'الإعدادات', body: `
      <div class="field" style="margin-bottom:12px"><label>عنوان محطة المشروعات</label>
        <input class="inp fld" id="stUrl" value="${esc(s.station_url)}" style="width:100%;margin-top:6px">
        <div class="muted" style="margin-top:6px">عند نقل الشاشة لجهاز آخر غيّر هذا العنوان إلى IP جهاز المحطة (مثل http://192.168.1.10:8765) — بدون أي تعديل في الكود.</div></div>
      <div class="field" style="margin-bottom:12px"><label>مستخدم حساب المزامنة على المحطة</label>
        <input class="inp fld" id="stUser" value="${esc(s.station_user || 'sync')}" dir="ltr" style="width:100%;margin-top:6px"></div>
      <div class="field" style="margin-bottom:12px"><label>كلمة مرور حساب المزامنة (اتركها فارغة لعدم التغيير)</label>
        <input class="inp fld" id="stPass" type="password" dir="ltr" style="width:100%;margin-top:6px" placeholder="••••••••"></div>
      <div class="muted">الجهاز: <span class="mono">${esc(App.meta?.device || '')}</span> · الوضع: مزامنة كل ثانيتين من المحطة.</div>`,
      footer: '<button class="btn primary" id="stSave">حفظ</button><button class="btn" data-close>إغلاق</button>' });
    $('#stSave', m.el).onclick = async () => {
      const v = $('#stUrl', m.el).value.trim();
      const body = { station_url: v, station_user: $('#stUser', m.el).value.trim() };
      const pw = $('#stPass', m.el).value;
      if (pw) body.station_pass = pw;
      try { await api('/api/settings', { method: 'PUT', body }); toast('تم حفظ الإعدادات — جاري إعادة الاتصال', 'ok'); m.close(); setTimeout(refreshKpis, 2500); }
      catch (e) { }
    };
  });
}

/* ================= SSE ================= */
function startSSE() {
  if (App.es) App.es.close();
  App.es = new EventSource('/api/events');
  App.es.onmessage = (e) => {
    let ev; try { ev = JSON.parse(e.data); } catch (err) { return; }
    if (ev.type === 'hello') return;
    if (ev.type === 'connection') refreshKpis();
    else if (ev.type === 'alert') { showAlert(ev.alert); refreshKpis(); }
    else if (ev.type === 'ticket') { onTicketEvent(ev.id); }
    else if (ev.type === 'reference') { if (App.view === 'ref') renderRef($('#app')); refreshKpis(); }
    else if (ev.type === 'directive') toast('توجيه من القيادة سُجل على المحطة', 'ok');
  };
  App.es.onerror = () => { /* EventSource auto-reconnects */ };
}

async function onTicketEvent(id) {
  refreshKpis();
  loadActivity();
  if (App.view === 'map') { loadMapList(); refreshMapLayers(); }
  else if (App.view === 'ops' && App._opsLoad) App._opsLoad();
  if (App.selTicket?.id === id && !detailEditing()) openTicket(id);
}

/* ================= theme & auto refresh ================= */
function applyTheme(t) {
  const light = t === 'light';
  document.body.classList.toggle('light', light);
  const b = $('#themeBtn');
  if (b) { b.textContent = light ? '☀️' : '🌙'; b.title = light ? 'الوضع الفاتح — اضغط للوضع الداكن' : 'الوضع الداكن — اضغط للوضع الفاتح'; }
}

function setRefresh(mins) {
  if (App._rt) { clearInterval(App._rt); App._rt = null; }
  if (mins > 0) App._rt = setInterval(softRefresh, mins * 60000);
}

async function softRefresh() {
  refreshKpis();
  loadActivity();
  if (App.view === 'map') { loadMapList(); refreshMapLayers(); if (App.selTicket && !detailEditing()) renderDetail(App.selTicket); }
  else if (App.view === 'ops' && App._opsLoad) App._opsLoad();
  else if (App.view === 'ref') renderRef($('#app'));
}

function applyRefreshPref() {
  const sel = $('#refreshSel');
  const v = localStorage.getItem('cmdRefreshMin') || '0';
  sel.value = v;
  setRefresh(+v);
  sel.onchange = () => {
    localStorage.setItem('cmdRefreshMin', sel.value);
    setRefresh(+sel.value);
    toast(sel.value === '0' ? 'التحديث التلقائي معطل' : `سيتم تحديث البيانات كل ${sel.value} دقائق`, 'ok', 2500);
  };
}

function accountMenu() {
  const u = App.user || {};
  const canAdmin = (u.permissions || []).includes('admin.users');
  const m = modal({ title: 'الحساب', body: `<div style="text-align:center;padding:10px 0">
      <div style="font-size:36px">🎖️</div>
      <div style="font-weight:700;font-size:16px;margin-top:6px">${esc(u.display_name || '')}</div>
      <div class="muted" dir="ltr" style="font-size:12px">${esc(u.username || '')}</div>
      <div class="muted" style="margin-top:8px;font-size:12px">الدور: ${esc(u.role_label || u.role || '')} · الصلاحيات: ${(u.permissions || []).length}</div>
    </div>`,
    footer: `${canAdmin ? '<a class="btn" href="/admin" style="text-decoration:none;display:inline-block">🛡️ إدارة الحسابات</a>' : ''}<button class="btn primary" id="acctLogout">تسجيل الخروج</button><button class="btn" data-close>إغلاق</button>` });
  $('#acctLogout', m.el).onclick = async () => { try { await fetch('/api/auth/logout', { method: 'POST' }); } finally { location.href = '/login'; } };
}

/* ================= boot ================= */
async function boot() {
  try { const me = await api('/api/auth/me'); App.user = me.user; } catch (e) { App.user = null; }
  if (App.user) { const n = $('#userName'); if (n) n.textContent = ' ' + (App.user.display_name || App.user.username); }
  $('#accountBtn').onclick = accountMenu;
  try { App.meta = await api('/api/meta'); } catch (e) { App.meta = null; }
  applyTheme(localStorage.getItem('cmdTheme') || 'light');
  $('#themeBtn').onclick = () => {
    const next = document.body.classList.contains('light') ? 'dark' : 'light';
    localStorage.setItem('cmdTheme', next);
    applyTheme(next);
  };
  applyRefreshPref();
  $('#alertsBtn').onclick = openAlerts;
  tickClock(); setInterval(tickClock, 1000);
  refreshKpis(); setInterval(refreshKpis, 8000);
  checkAlerts(); setInterval(checkAlerts, 20000);
  $('#settingsBtn').onclick = openSettings;
  hashRoute();
  startSSE();
  setInterval(() => { if (App.view === 'map' && App.mapKit) refreshMapLayers(); }, 15000);
}
document.addEventListener('DOMContentLoaded', boot);
