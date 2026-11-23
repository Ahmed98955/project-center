/* Core helpers: API, formatting, toasts, modals, router, header. */
const App = { meta: null, pages: {}, current: null, cleanup: [], seenAlerts: new Set(JSON.parse(sessionStorage.getItem('seenAlerts') || '[]')) };
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const NUM = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const fmtN = (n) => (n === null || n === undefined || n === '' ? '—' : NUM.format(n));
function fmtDate(s, withTime = true) {
  if (!s) return '—';
  const d = new Date(s.replace(' ', 'T'));
  if (isNaN(d)) return s;
  const pad = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())}` + (withTime ? ` ${pad(d.getHours())}:${pad(d.getMinutes())}` : '');
}
function fmtLen(m) { if (!m && m !== 0) return '—'; return m >= 1000 ? `${NUM.format(m / 1000)} كم` : `${NUM.format(Math.round(m))} م`; }
function fmtHours(h) { if (h === null || h === undefined) return '—'; if (h < 1) return `${Math.round(h * 60)} دقيقة`; return `${NUM.format(h)} ساعة`; }
function ago(s) {
  if (!s) return '';
  const h = (Date.now() - new Date(s.replace(' ', 'T'))) / 36e5;
  if (h < 1) return `منذ ${Math.max(1, Math.round(h * 60))} دقيقة`;
  if (h < 48) return `منذ ${Math.round(h)} ساعة`;
  return `منذ ${Math.round(h / 24)} يوم`;
}
const pill = (cls, text) => `<span class="pill ${cls}">${esc(text)}</span>`;
const prioPill = (t) => pill('p-' + t.priority, t.priority_label);
const statusPill = (t) => pill('s-' + t.status, t.status_label) + (t.wait && t.wait.overdue ? ' ' + pill('overdue', 'متأخر') : '');
const typePill = (t) => pill('t-' + t.fax_type, t.type_label);
const availPill = (a) => (a ? pill('a-' + a, App.meta.availability[a]) : '<span class="muted">—</span>');
const sevIcon = { urgent: '🚨', warning: '⚠️', info: 'ℹ️' };

function operator() { return localStorage.getItem('operator') || 'مشغل المشروعات'; }

async function api(path, opts = {}) {
  const o = { method: opts.method || 'GET', headers: { 'X-Operator': encodeURIComponent(operator()) } };
  if (opts.body instanceof FormData) o.body = opts.body;
  else if (opts.body !== undefined) { o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(opts.body); }
  let res;
  try { res = await fetch(path, o); } catch (e) { toast('تعذر الاتصال بالخادم المحلي — تأكد أن البرنامج يعمل', 'err'); throw e; }
  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('json') ? await res.json() : await res.text();
  if (res.status === 401 && !path.startsWith('/api/auth/')) {
    location.href = '/login?next=' + encodeURIComponent(location.pathname + location.hash);
    const err = new Error('unauthorized'); err.status = 401; throw err;
  }
  if (!res.ok) {
    let msg = data && data.detail ? data.detail : 'حدث خطأ';
    if (Array.isArray(msg)) msg = 'بيانات غير مكتملة أو غير صالحة: ' + msg.map((d) => (d.loc || []).slice(-1)[0]).join('، ');
    if (!opts.silent) toast(msg, 'err');
    const err = new Error(msg); err.status = res.status; throw err;
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

function confirmBox(message, okText = 'تأكيد', danger = false) {
  return new Promise((resolve) => {
    const m = modal({ title: 'تأكيد', body: `<p>${message}</p>`,
      footer: `<button class="btn ${danger ? 'danger' : 'primary'}" data-ok>${okText}</button><button class="btn" data-close>إلغاء</button>`,
      onClose: () => resolve(false) });
    $('[data-ok]', m.el).onclick = () => { resolve(true); m.el.remove(); };
  });
}

function opts(map, selected, empty) {
  const entries = Array.isArray(map) ? map : Object.entries(map);
  return (empty !== undefined ? `<option value="">${esc(empty)}</option>` : '') +
    entries.map(([k, v]) => `<option value="${esc(k)}" ${String(k) === String(selected ?? '') ? 'selected' : ''}>${esc(v)}</option>`).join('');
}

function formData(form) {
  const d = {};
  new FormData(form).forEach((v, k) => { d[k] = typeof v === 'string' ? v.trim() : v; });
  return d;
}

function alertHtml(a, clickable = true) {
  return `<div class="alert-item ${a.severity}" ${clickable && a.ticket_id ? `data-ticket="${a.ticket_id}"` : ''}>
    <div class="ic">${sevIcon[a.severity]}</div><div><div class="t">${esc(a.title)}</div><div class="m">${esc(a.message)}</div>
    ${a.related && a.type === 'repeat_fault' ? `<table class="tbl small" style="margin-top:6px"><tr><th>الفاكس</th><th>التاريخ</th><th>السبب</th><th>الإجراء</th><th>المسافة</th></tr>
      ${a.related.map((r) => `<tr><td>${esc(r.fax_no)}</td><td>${esc(r.date)}</td><td>${esc(r.cause || '—')}</td><td>${esc(r.resolution || '—')}</td><td>${fmtLen(r.distance_m)}</td></tr>`).join('')}</table>` : ''}
    </div></div>`;
}
function bindAlertClicks(root) {
  $$('[data-ticket]', root).forEach((el) => el.addEventListener('click', () => { $$('.modal-bg').forEach((m) => m.remove()); location.hash = '#/ticket/' + el.dataset.ticket; }));
}

/* ---------- router ---------- */
function route() {
  const hash = location.hash || '#/dashboard';
  const [, page, arg] = hash.split('/');
  App.cleanup.forEach((f) => { try { f(); } catch (e) { console.error(e); } });
  App.cleanup = [];
  const main = $('#app');
  main.className = '';
  main.innerHTML = '<div class="empty">جاري التحميل…</div>';
  $$('#sidenav a').forEach((a) => a.classList.toggle('active', a.dataset.page === page || (page === 'ticket' && a.dataset.page === 'faxes')));
  const fn = App.pages[page] || App.pages.dashboard;
  App.current = page;
  Promise.resolve(fn(main, arg)).catch((e) => { console.error(e); main.innerHTML = `<div class="empty">تعذر تحميل الصفحة: ${esc(e.message)}</div>`; });
}

/* ---------- header ---------- */
function tickClock() {
  const d = new Date();
  const days = ['الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت'];
  $('#clock').textContent = `${days[d.getDay()]} · ${fmtDate(localIso(d))}:${String(d.getSeconds()).padStart(2, '0')}`;
}
function localIso(d) { const p = (x) => String(x).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; }

async function refreshHeader() {
  try {
    const d = await api('/api/dashboard', { silent: true });
    $('#topKpis').innerHTML = `
      <div class="k" data-go="#/faxes?status=new"><b>${d.by_status.new}</b>وارد جديد</div>
      <div class="k amber" data-go="#/faxes?status=awaiting_coordination"><b>${d.by_status.awaiting_coordination}</b>انتظار تنسيق</div>
      <div class="k" data-go="#/faxes?status=in_progress"><b>${d.by_status.in_progress}</b>تنفيذ ميداني</div>
      <div class="k red" data-go="#/faxes?priority=critical"><b>${d.critical_open}</b>حرج مفتوح</div>`;
    $$('#topKpis [data-go]').forEach((el) => (el.onclick = () => (location.hash = el.dataset.go)));
    const n = d.alerts.length;
    $('#bellCount').hidden = !n; $('#bellCount').textContent = n;
    App.lastAlerts = d.alerts;
    const fresh = d.alerts.filter((a) => a.severity === 'urgent' && !App.seenAlerts.has(a.type + ':' + a.ticket_id));
    if (fresh.length && App.current !== 'ticket') {
      fresh.forEach((a) => App.seenAlerts.add(a.type + ':' + a.ticket_id));
      sessionStorage.setItem('seenAlerts', JSON.stringify([...App.seenAlerts]));
      const m = modal({ title: '🚨 تنبيه عاجل', urgent: true, body: fresh.map((a) => alertHtml(a)).join(''), footer: '<button class="btn" data-close>إغلاق</button>' });
      bindAlertClicks(m.el);
    }
  } catch (e) { /* server offline */ }
}

function showAlerts() {
  const list = App.lastAlerts || [];
  const m = modal({ title: 'التنبيهات النشطة', wide: true, body: list.length ? list.map((a) => alertHtml(a)).join('') : '<div class="empty">لا توجد تنبيهات</div>', footer: '<button class="btn" data-close>إغلاق</button>' });
  bindAlertClicks(m.el);
}

function accountMenu() {
  const u = App.user || {};
  const canAdmin = (u.permissions || []).includes('admin.users');
  const m = modal({ title: 'الحساب', body: `<div style="text-align:center;padding:10px 0">
      <div style="font-size:36px">👤</div>
      <div style="font-weight:700;font-size:16px;margin-top:6px">${esc(u.display_name || '')}</div>
      <div class="muted" dir="ltr" style="font-size:12px">${esc(u.username || '')}</div>
      <div class="muted" style="margin-top:8px;font-size:12px">الدور: ${esc(u.role_label || u.role || '')} · الصلاحيات: ${(u.permissions || []).length}</div>
    </div>`,
    footer: `${canAdmin ? '<a class="btn" href="/admin" style="text-decoration:none;display:inline-block">🛡️ إدارة الحسابات</a>' : ''}<button class="btn primary" id="acctLogout">تسجيل الخروج</button><button class="btn" data-close>إغلاق</button>` });
  $('#acctLogout', m.el).onclick = async () => { try { await fetch('/api/auth/logout', { method: 'POST' }); } finally { location.href = '/login'; } };
}

function hashParams() { const q = (location.hash.split('?')[1] || ''); return Object.fromEntries(new URLSearchParams(q)); }

async function boot() {
  const me = await api('/api/auth/me');
  App.user = me.user;
  App.meta = await api('/api/meta');
  const s = App.meta.settings;
  $('#unitName').textContent = s.operator_unit; $('#stationName').textContent = s.station_name;
  $('#operatorName').textContent = App.user.display_name || App.user.username;
  $('#navFoot').innerHTML = `الجهاز: <span class="mono">${esc(App.meta.device)}</span><br>قاعدة البيانات: SQLite محلية<br>وضع التشغيل: بدون إنترنت`;
  $('#bellBtn').onclick = showAlerts; $('#accountChip').onclick = accountMenu;
  setInterval(tickClock, 1000); tickClock();
  refreshHeader(); setInterval(refreshHeader, 30000);
  window.addEventListener('hashchange', route);
  route();
}
document.addEventListener('DOMContentLoaded', boot);
