/* Pages: dashboard, faxes, general map, history, teams, routes, equipment, settings, audit. */

/* ---------------- dashboard ---------------- */
App.pages.dashboard = async (main) => {
  const d = await api('/api/dashboard');
  const st = d.by_status;
  main.innerHTML = `
  <div class="page-head"><div><h1>لوحة المتابعة</h1><div class="sub">الموقف الحالي لقسم المشروعات — ${fmtDate(localIso(new Date()))}</div></div>
    <div class="btn-row"><button class="btn" id="simBtn">📠 محاكاة ورود فاكس</button><a class="btn primary" href="#/faxes?new=1">＋ تسجيل فاكس جديد</a></div></div>
  <div class="grid g6">
    <div class="card kpi blue" data-go="#/faxes?status=new"><span class="v">${st.new}</span><span class="l">وارد جديد</span></div>
    <div class="card kpi amber" data-go="#/faxes?status=awaiting_coordination"><span class="v">${st.awaiting_coordination}</span><span class="l">انتظار تنسيق / تصديق ${d.overdue ? `<b style="color:var(--red)">(${d.overdue} متأخر)</b>` : ''}</span></div>
    <div class="card kpi" data-go="#/faxes?status=preparing"><span class="v">${st.preparing}</span><span class="l">قيد التجهيز</span></div>
    <div class="card kpi green" data-go="#/faxes?status=in_progress"><span class="v">${st.in_progress}</span><span class="l">جاري التنفيذ الميداني</span></div>
    <div class="card kpi red" data-go="#/faxes?priority=critical"><span class="v">${d.critical_open}</span><span class="l">بلاغات حرجة مفتوحة</span></div>
    <div class="card kpi" data-go="#/faxes"><span class="v">${d.not_forwarded}</span><span class="l">لم تُمرر إلى القيادة بعد</span></div>
  </div>
  <div class="grid" style="grid-template-columns:1.25fr 1fr;margin-top:14px">
    <div class="card"><h2>🚨 التنبيهات النشطة (${d.alerts.length})</h2><div id="dashAlerts">${d.alerts.length ? d.alerts.map((a) => alertHtml(a)).join('') : '<div class="empty">لا توجد تنبيهات — الموقف مستقر</div>'}</div></div>
    <div class="card" style="padding:0;overflow:hidden;min-height:380px;position:relative"><div id="dashMap" style="position:absolute;inset:0"></div></div>
  </div>
  <div class="grid g3" style="margin-top:14px">
    <div class="card"><h2>العمليات المفتوحة حسب النوع</h2>
      <div class="kv"><dt>أعطال</dt><dd>${d.by_type.fault}</dd><dt>مشروعات إنشاء</dt><dd>${d.by_type.project}</dd><dt>طلبات تنسيق</dt><dd>${d.by_type.coordination}</dd>
      <dt>مغلق هذا الشهر</dt><dd>${d.closed_this_month}</dd><dt>إجمالي المغلق (السجل)</dt><dd>${st.closed}</dd><dt>المسارات المسجلة</dt><dd>${d.routes} مسار · ${fmtN(d.routes_km)} كم</dd></div></div>
    <div class="card"><h2>الأطقم والمفارز</h2>${d.teams.map((t) => `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #f0f2f5">
      <span>${esc(t.team_name)} <span class="muted small">(${t.members} فرد)</span></span>${pill(t.status === 'on_mission' ? 's-in_progress' : t.status === 'available' ? 'a-available' : 's-closed', App.meta.team_status[t.status])}</div>`).join('')}
      <a href="#/teams" class="small">إدارة الأطقم ←</a></div>
    <div class="card"><h2>آخر التحديثات</h2><ul class="timeline">${d.recent_updates.map((u) => `<li class="${u.old_status === u.new_status ? 'note' : ''}">
      <div><a href="#/ticket/${u.ticket_id}">${esc(u.fax_no)}</a> — ${u.old_status === u.new_status ? esc(u.notes || '') : esc(App.meta.statuses.find((s) => s[0] === u.new_status)[1])}</div>
      <div class="when">${fmtDate(u.at)} · ${esc(u.actor || '')}</div></li>`).join('')}</ul></div>
  </div>`;
  $$('[data-go]', main).forEach((el) => (el.onclick = () => (location.hash = el.dataset.go)));
  bindAlertClicks(main);
  $('#simBtn').onclick = simulateFax;
  const kit = MapKit.create($('#dashMap'));
  App.cleanup.push(kit.destroy);
  await kit.loadLayers();
  kit.addLegend($('#dashMap'));
  if (kit.tickets.getLayers().length) kit.map.fitBounds(kit.tickets.getBounds(), { padding: [30, 30], maxZoom: 13 });
};

async function simulateFax() {
  const t = await api('/api/simulate/fax', { method: 'POST' });
  toast(`تم استلام فاكس جديد (محاكاة): ${t.fax_no}`, 'ok');
  refreshHeader();
  location.hash = '#/ticket/' + t.id;
}

/* ---------------- faxes list ---------------- */
App.pages.faxes = async (main) => {
  const p = hashParams();
  const m = App.meta;
  main.innerHTML = `
  <div class="page-head"><div><h1>الفاكسات الواردة</h1><div class="sub">كل الفاكسات والعمليات المفتوحة — اضغط على أي سطر لفتح شاشة العمل</div></div>
    <div class="btn-row"><button class="btn" id="simBtn">📠 محاكاة ورود فاكس</button><button class="btn primary" id="newBtn">＋ تسجيل فاكس جديد</button></div></div>
  <div class="filters">
    <input class="inp" id="fq" placeholder="بحث: رقم، عنوان، موقع، جهة…" style="min-width:240px" value="${esc(p.q || '')}">
    <select class="inp" id="fscope">${opts({ active: 'المفتوحة فقط', all: 'الكل', closed: 'المغلقة' }, p.scope || 'active')}</select>
    <select class="inp" id="fstatus">${opts(m.statuses, p.status, 'كل الحالات')}</select>
    <select class="inp" id="ftype">${opts(m.fax_types, p.fax_type, 'كل الأنواع')}</select>
    <select class="inp" id="fprio">${opts(m.priorities, p.priority, 'كل درجات الأهمية')}</select>
    <span class="muted small" id="fcount"></span>
  </div>
  <div class="tbl-wrap"><table class="tbl"><thead><tr><th>رقم الفاكس</th><th>النوع</th><th>العنوان / الملخص</th><th>الموقع</th><th>الجهة</th><th>الأهمية</th><th>الحالة</th><th>المسار</th><th>الاحتياجات</th><th>القيادة</th><th>الورود</th></tr></thead><tbody id="fbody"></tbody></table></div>`;
  const load = async () => {
    const qs = new URLSearchParams({ scope: $('#fscope').value });
    [['status', '#fstatus'], ['fax_type', '#ftype'], ['priority', '#fprio'], ['q', '#fq']].forEach(([k, s]) => { const v = $(s).value.trim(); if (v) qs.set(k, v); });
    if (qs.get('status') === 'closed') qs.set('scope', 'all');
    const items = await api('/api/tickets?' + qs);
    $('#fcount').textContent = `${items.length} فاكس`;
    $('#fbody').innerHTML = items.length ? items.map((t) => `<tr class="click" data-id="${t.id}">
      <td><b>${esc(t.fax_no)}</b>${t.has_file ? ' 📎' : ''}</td><td>${typePill(t)}</td>
      <td><div style="font-weight:600">${esc(t.title)}</div><div class="muted small">${esc(t.required_action || t.summary)}</div></td>
      <td>${t.geometry ? '📍 ' : '<span title="لم يُحدد على الخريطة">⚪ </span>'}${esc(t.location_text || '—')}</td><td class="small">${esc(t.requesting_party || '—')}</td>
      <td>${prioPill(t)}</td><td>${statusPill(t)}${t.status === 'awaiting_coordination' ? `<div class="small muted">${fmtN(t.wait.hours_in_status)} ساعة</div>` : ''}</td>
      <td>${esc(t.route_code || '—')}</td><td>${availPill(t.needs_status)}</td><td>${t.forwarded_to_command ? '✅' : '—'}</td><td class="small">${fmtDate(t.received_at)}<div class="muted">${ago(t.received_at)}</div></td></tr>`).join('')
      : '<tr><td colspan="11" class="empty">لا توجد فاكسات مطابقة</td></tr>';
    $$('#fbody tr[data-id]').forEach((tr) => (tr.onclick = () => (location.hash = '#/ticket/' + tr.dataset.id)));
  };
  let timer;
  $('#fq').oninput = () => { clearTimeout(timer); timer = setTimeout(load, 250); };
  ['#fscope', '#fstatus', '#ftype', '#fprio'].forEach((s) => ($(s).onchange = load));
  $('#newBtn').onclick = () => newFaxModal();
  $('#simBtn').onclick = simulateFax;
  await load();
  if (p.new) newFaxModal();
};

function newFaxModal() {
  const m = App.meta;
  const now = localIso(new Date()).replace(' ', 'T');
  const md = modal({ title: '📠 تسجيل فاكس وارد — بطاقة الملخص التنفيذي', wide: true, body: `
    <form id="faxForm">
      <div class="row3">
        <div class="field"><label>رقم الفاكس *</label><input name="fax_no" required placeholder="مثال: ف/2026/0420"></div>
        <div class="field"><label>نوع الفاكس *</label><select name="fax_type">${opts(m.fax_types, 'fault')}</select></div>
        <div class="field"><label>درجة الأهمية *</label><select name="priority">${opts(m.priorities, 'normal')}</select></div>
      </div>
      <div class="field"><label>العنوان المختصر *</label><input name="title" required minlength="3" placeholder="مثال: قطع كابل ألياف — طريق الأوتوستراد"></div>
      <div class="field"><label>الملخص التنفيذي (المضمون الجوهري) *</label><textarea name="summary" required minlength="3"></textarea></div>
      <div class="field"><label>المطلوب في سطر واحد</label><input name="required_action" placeholder="مثال: إصلاح فوري وإعادة الخدمة خلال 6 ساعات"></div>
      <div class="row3">
        <div class="field"><label>الموقع (وصف نصي)</label><input name="location_text" placeholder="يُحدد بدقة على الخريطة بعد الحفظ"></div>
        <div class="field"><label>الجهة الطالبة / المتسببة</label><input name="requesting_party" list="partiesList"></div>
        <div class="field"><label>تاريخ ووقت الورود</label><input type="datetime-local" name="received_at" value="${now}"></div>
      </div>
      <datalist id="partiesList"><option>غرفة عمليات الاتصالات</option><option>شركة مياه الشرب بالقاهرة</option><option>شركة الغاز الطبيعي</option><option>هيئة الطرق والكباري</option><option>قيادة المنطقة المركزية</option><option>حي</option></datalist>
      <div class="field"><label>ملف الفاكس الأصلي (PDF أو صورة) — اختياري</label>
        <div class="drop" id="drop"><span id="dropLbl">اسحب الملف هنا أو اضغط للاختيار</span>
          <input type="file" id="faxFile" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.gif,.webp" style="display:block;margin:8px auto 0;max-width:100%;font-size:12px"></div>
        <div id="faxAnalysis" style="margin-top:8px"></div></div>
    </form>`,
    footer: '<button class="btn primary" id="saveFax">💾 حفظ وفتح شاشة العمل</button><button class="btn" data-close>إلغاء</button>' });
  const fileIn = $('#faxFile', md.el), drop = $('#drop', md.el), dropLbl = $('#dropLbl', md.el), anaBox = $('#faxAnalysis', md.el);
  let file = null;
  const setFile = (f) => {
    file = f;
    dropLbl.textContent = f ? `📎 ${f.name} (${fmtN(f.size / 1024)} ك.ب)` : 'اسحب الملف هنا أو اضغط للاختيار';
    anaBox.innerHTML = '';
    if (f) analyzeFaxFile(f);
  };
  async function analyzeFaxFile(f) {
    anaBox.innerHTML = '<div class="small muted">⏳ جاري تحليل محتوى الملف…</div>';
    const fd = new FormData(); fd.append('file', f);
    try {
      const r = await api('/api/files/extract-text', { method: 'POST', body: fd, silent: true });
      if (r.ok && r.text && r.text.trim()) {
        anaBox.innerHTML = `<div class="section" style="margin-top:4px"><h3>🧠 النص المستخرج من الملف <span class="muted small">(${r.chars} حرف — ${r.pages} صفحة)</span></h3>
          <textarea class="inp" readonly style="width:100%;height:130px">${esc(r.text)}</textarea>
          <div class="btn-row" style="margin-top:6px"><button class="btn sm" id="cpTxt" type="button">📋 نسخ النص</button>
          <span class="small muted">انسخ ما يلزم إلى حقول العنوان والملخص أعلاه</span></div></div>`;
        $('#cpTxt', anaBox).onclick = () => navigator.clipboard && navigator.clipboard.writeText(r.text).then(() => toast('تم نسخ النص', 'ok'));
      } else {
        anaBox.innerHTML = `<div class="alert-item info"><div class="ic">ℹ️</div><div class="m">${esc(r.message || 'لا يوجد نص قابل للاستخراج من هذا الملف')}</div></div>`;
      }
    } catch (e) {
      anaBox.innerHTML = '<div class="small muted">تعذر تحليل الملف — يمكنك إرفاقه وإكمال الإدخال يدويًا</div>';
    }
  }
  drop.onclick = (e) => { if (e.target !== fileIn) fileIn.click(); };
  fileIn.onchange = () => setFile(fileIn.files[0]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove('over'); setFile(e.dataTransfer.files[0]); };
  $('#saveFax', md.el).onclick = async () => {
    const form = $('#faxForm', md.el);
    if (!form.reportValidity()) return;
    const d = formData(form);
    Object.keys(d).forEach((k) => d[k] === '' && delete d[k]);
    const t = await api('/api/tickets', { method: 'POST', body: d });
    if (file) { const fd = new FormData(); fd.append('file', file); await api(`/api/tickets/${t.id}/file`, { method: 'POST', body: fd }).catch(() => {}); }
    md.close(); toast('تم تسجيل الفاكس — حدد الموقع على الخريطة', 'ok'); refreshHeader();
    location.hash = '#/ticket/' + t.id;
  };
}

/* ---------------- general map ---------------- */
App.pages.map = async (main) => {
  main.className = 'full';
  main.innerHTML = '<div class="pagemap" style="position:relative"><div id="gmap" style="position:absolute;inset:0"></div></div>';
  const kit = MapKit.create($('#gmap'));
  App.cleanup.push(kit.destroy);
  kit.addSearch($('#gmap')); kit.addLegend($('#gmap'));
  kit.history.addTo(kit.map);
  await kit.loadLayers();
  kit.map.on('contextmenu', (e) => pointHistory(e.latlng.lat, e.latlng.lng));
  const info = document.createElement('div'); info.className = 'map-info';
  info.innerHTML = 'كليك يمين على أي نقطة لعرض <b>سجلها التاريخي</b> (الأعطال والعمليات في نطاقها)';
  $('#gmap').appendChild(info);
};

async function pointHistory(lat, lon) {
  const r = App.meta.settings.repeat_radius_m;
  const items = await api(`/api/history/near?lat=${lat}&lon=${lon}&radius=${r}`);
  const m = modal({ title: `سجل النقطة — نطاق ${fmtLen(r)}`, wide: true, body: items.length ? `<table class="tbl"><tr><th>الفاكس</th><th>النوع</th><th>العنوان</th><th>الحالة</th><th>السبب</th><th>الإجراء</th><th>التاريخ</th><th>المسافة</th></tr>
    ${items.map((t) => `<tr class="click" data-ticket="${t.id}"><td>${esc(t.fax_no)}</td><td>${typePill(t)}</td><td>${esc(t.title)}</td><td>${statusPill(t)}</td><td>${esc(t.cause || '—')}</td><td class="small">${esc(t.resolution || '—')}</td><td>${fmtDate(t.closed_at || t.received_at, false)}</td><td>${fmtLen(t.distance_m)}</td></tr>`).join('')}</table>`
    : '<div class="empty">لا يوجد سجل لهذه النقطة</div>', footer: '<button class="btn" data-close>إغلاق</button>' });
  bindAlertClicks(m.el);
}

/* ---------------- history ---------------- */
App.pages.history = async (main) => {
  const m = App.meta;
  const routes = await api('/api/routes?kind=route');
  main.className = 'full';
  main.innerHTML = `<div class="split" style="grid-template-columns:1fr 1fr"><div class="side" style="border:0">
    <div class="page-head"><div><h1>السجل التاريخي</h1><div class="sub">ذاكرة القسم: كل الأعطال والمشروعات وأسبابها والإجراءات المتخذة</div></div></div>
    <div class="filters">
      <input class="inp" id="hq" placeholder="بحث في السبب، الإجراء، العنوان…" style="min-width:220px">
      <select class="inp" id="hscope">${opts({ closed: 'المغلقة (السجل)', all: 'الكل' }, 'closed')}</select>
      <select class="inp" id="htype">${opts(m.fax_types, '', 'كل الأنواع')}</select>
      <select class="inp" id="hroute">${opts(routes.map((r) => [r.id, r.code + ' — ' + r.axis_name]), '', 'كل المسارات')}</select>
      <label class="small">من <input type="date" class="inp" id="hfrom"></label><label class="small">إلى <input type="date" class="inp" id="hto"></label>
    </div>
    <div id="hstats" class="chips" style="margin-bottom:10px"></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>الفاكس</th><th>النوع</th><th>العنوان</th><th>المسار</th><th>السبب</th><th>الإجراءات المتخذة</th><th>التاريخ</th></tr></thead><tbody id="hbody"></tbody></table></div>
  </div><div style="position:relative"><div id="hmap" style="position:absolute;inset:0"></div></div></div>`;
  const kit = MapKit.create($('#hmap'));
  App.cleanup.push(kit.destroy);
  kit.addSearch($('#hmap'));
  await kit.loadLayers();
  kit.map.removeLayer(kit.tickets);
  const hl = L.featureGroup().addTo(kit.map);
  const load = async () => {
    const qs = new URLSearchParams({ scope: $('#hscope').value });
    [['q', '#hq'], ['fax_type', '#htype'], ['route_id', '#hroute'], ['date_from', '#hfrom'], ['date_to', '#hto']].forEach(([k, s]) => $(s).value && qs.set(k, $(s).value));
    const items = await api('/api/tickets?' + qs);
    const causes = {};
    items.forEach((t) => t.cause && (causes[t.cause.split(' (')[0]] = (causes[t.cause.split(' (')[0]] || 0) + 1));
    $('#hstats').innerHTML = `<span class="pill s-closed">${items.length} سجل</span>` + Object.entries(causes).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([c, n]) => `<span class="pill t-fault">${esc(c)}: ${n}</span>`).join('');
    $('#hbody').innerHTML = items.length ? items.map((t) => `<tr class="click" data-id="${t.id}"><td><b>${esc(t.fax_no)}</b></td><td>${typePill(t)}</td><td>${esc(t.title)}</td><td>${esc(t.route_code || '—')}</td>
      <td class="small">${esc(t.cause || '—')}</td><td class="small">${esc(t.resolution || '—')}</td><td class="small">${fmtDate(t.closed_at || t.received_at, false)}</td></tr>`).join('') : '<tr><td colspan="7" class="empty">لا توجد سجلات</td></tr>';
    hl.clearLayers();
    items.forEach((t) => {
      if (!t.geometry) return;
      const color = { fault: '#d32f2f', project: '#2e7d32', coordination: '#f9a825' }[t.fax_type];
      const layer = t.geometry.type === 'Point' ? L.circleMarker([t.geometry.coordinates[1], t.geometry.coordinates[0]], { radius: 7, color: '#fff', weight: 2, fillColor: color, fillOpacity: 0.9 })
        : L.geoJSON(t.geometry, { style: { color, weight: 5 } });
      layer.bindPopup(`<b>${esc(t.fax_no)}</b><br>${esc(t.title)}<br>السبب: ${esc(t.cause || '—')}<br><a href="#/ticket/${t.id}">فتح ←</a>`).addTo(hl);
      layer._tid = t.id;
    });
    $$('#hbody tr[data-id]').forEach((tr) => {
      tr.onclick = () => (location.hash = '#/ticket/' + tr.dataset.id);
      tr.onmouseenter = () => hl.eachLayer((l) => { if (l._tid === +tr.dataset.id) { l.openPopup && l.openPopup(); } });
    });
    if (hl.getLayers().length) kit.map.fitBounds(hl.getBounds(), { padding: [30, 30], maxZoom: 14 });
  };
  let timer;
  $('#hq').oninput = () => { clearTimeout(timer); timer = setTimeout(load, 250); };
  ['#hscope', '#htype', '#hroute', '#hfrom', '#hto'].forEach((s) => ($(s).onchange = load));
  await load();
};

/* ---------------- teams ---------------- */
App.pages.teams = async (main) => {
  const render = (items) => {
    const groups = {};
    items.forEach((p) => (groups[p.team_name || 'بدون مفرزة'] ||= []).push(p));
    main.innerHTML = `<div class="page-head"><div><h1>الأطقم والمفارز</h1><div class="sub">قادة المفارز والأطقم الفنية وحالة تواجدهم الميداني</div></div>
      <button class="btn primary" id="addM">＋ إضافة فرد</button></div>
      <div class="grid g2">${Object.entries(groups).map(([g, ps]) => `<div class="card"><h2>${esc(g)} <span class="muted small">(${ps.length})</span></h2>
        <table class="tbl"><tr><th>الاسم</th><th>التخصص الفني</th><th>الحالة</th><th>المهمة الحالية</th><th></th></tr>
        ${ps.map((p) => `<tr><td>${p.is_leader ? '⭐ ' : ''}<b>${esc(p.name)}</b><div class="muted small">${esc(p.rank || '')}</div></td><td class="small">${esc(p.specialty || '—')}</td>
          <td><select class="inp" data-status="${p.id}" style="width:auto">${opts(App.meta.team_status, p.status)}</select></td>
          <td>${p.current_fax ? `<a href="#/ticket/${p.current_ticket_id}">${esc(p.current_fax)}</a>` : '—'}</td>
          <td><button class="btn sm" data-edit="${p.id}">تعديل</button></td></tr>`).join('')}</table></div>`).join('')}</div>`;
    $$('[data-status]', main).forEach((s) => (s.onchange = async () => { render(await api('/api/teams/' + s.dataset.status, { method: 'PUT', body: { status: s.value } })); toast('تم تحديث الحالة', 'ok'); }));
    $$('[data-edit]', main).forEach((b) => (b.onclick = () => memberModal(items.find((p) => p.id === +b.dataset.edit), render)));
    $('#addM').onclick = () => memberModal(null, render);
  };
  render(await api('/api/teams'));
};

function memberModal(p, render) {
  p = p || {};
  const md = modal({ title: p.id ? 'تعديل بيانات فرد' : 'إضافة فرد', body: `<form id="mf">
    <div class="row"><div class="field"><label>الاسم *</label><input name="name" required value="${esc(p.name || '')}"></div><div class="field"><label>الرتبة / الدرجة</label><input name="rank" value="${esc(p.rank || '')}"></div></div>
    <div class="row"><div class="field"><label>المفرزة / الطاقم</label><input name="team_name" value="${esc(p.team_name || '')}" list="teamsList"></div><div class="field"><label>التخصص الفني</label><input name="specialty" value="${esc(p.specialty || '')}"></div></div>
    <div class="row"><div class="field"><label>الحالة</label><select name="status">${opts(App.meta.team_status, p.status || 'available')}</select></div><div class="field"><label>رقم التواصل</label><input name="phone" value="${esc(p.phone || '')}"></div></div>
    <label><input type="checkbox" name="is_leader" ${p.is_leader ? 'checked' : ''}> قائد المفرزة</label>
    <datalist id="teamsList"><option>المفرزة الأولى</option><option>المفرزة الثانية</option><option>المفرزة الثالثة</option><option>طاقم القياس</option></datalist></form>`,
    footer: `<button class="btn primary" id="ms">حفظ</button>${p.id ? '<button class="btn danger" id="md">حذف</button>' : ''}<button class="btn" data-close>إلغاء</button>` });
  $('#ms', md.el).onclick = async () => {
    const f = $('#mf', md.el); if (!f.reportValidity()) return;
    const d = formData(f); d.is_leader = d.is_leader ? 1 : 0;
    render(await api(p.id ? '/api/teams/' + p.id : '/api/teams', { method: p.id ? 'PUT' : 'POST', body: d })); md.close(); toast('تم الحفظ', 'ok');
  };
  if (p.id) $('#md', md.el).onclick = async () => { if (await confirmBox('حذف هذا الفرد؟', 'حذف', true)) { render(await api('/api/teams/' + p.id, { method: 'DELETE' })); md.close(); } };
}

/* ---------------- routes & sites (reference data) ---------------- */
App.pages.routes = async (main) => {
  main.className = 'full';
  main.innerHTML = `<div class="split" style="grid-template-columns:1fr 460px"><div style="position:relative"><div id="rmap" style="position:absolute;inset:0"></div></div>
    <div class="side"><div class="page-head"><div><h1>المسارات والوصلات</h1><div class="sub">المرجع الثابت لمسارات الكوابل والوصلات ونقاط الربط</div></div></div>
    <div class="btn-row" style="margin-bottom:10px"><button class="btn primary" id="addR">＋ إضافة مسار / نقطة (ارسم على الخريطة)</button></div>
    <input class="inp" id="rq" placeholder="بحث بالكود أو الاسم" style="margin-bottom:8px"><div id="rlist"></div></div></div>`;
  const kit = MapKit.create($('#rmap'));
  App.cleanup.push(kit.destroy);
  kit.addSearch($('#rmap')); kit.addLegend($('#rmap'));
  let pending = null;
  kit.enableDraw({ onChange: (d) => { pending = d; if (d) siteModal(null, d); } });
  let items = [];
  const load = async () => {
    items = await api('/api/routes');
    await kit.loadLayers();
    renderList();
  };
  const renderList = () => {
    const q = normalizeAr($('#rq').value);
    const list = items.filter((r) => !q || normalizeAr(r.code + ' ' + r.name).includes(q));
    $('#rlist').innerHTML = list.map((r) => `<div class="alert-item ${r.kind === 'route' ? 'info' : ''}" data-id="${r.id}" style="align-items:center">
      <div class="ic">${r.kind === 'route' ? '🧵' : r.kind === 'exchange' ? '🏢' : r.kind === 'checkpoint' ? '🕳️' : '🔗'}</div>
      <div style="flex:1"><div class="t">${esc(r.code)} <span class="muted small">${esc(r.kind_label)}</span></div><div class="m">${esc(r.name)}</div>
      ${r.kind === 'route' ? `<div class="small muted">${esc(MapKit.cableName(r.cable_type))} · ${fmtLen(r.length_m)} · أعطال مسجلة: ${r.faults} · ${esc(r.parties || '')}</div>` : r.parent_code ? `<div class="small muted">على المسار ${esc(r.parent_code)}</div>` : ''}</div>
      <button class="btn sm" data-edit="${r.id}">تعديل</button></div>`).join('');
    $$('#rlist [data-id]').forEach((el) => (el.onclick = (e) => {
      const r = items.find((x) => x.id === +el.dataset.id);
      if (e.target.closest('[data-edit]')) return siteModal(r, null);
      if (r.geometry.type === 'Point') kit.map.setView([r.geometry.coordinates[1], r.geometry.coordinates[0]], 16);
      else kit.map.fitBounds(L.geoJSON(r.geometry).getBounds(), { padding: [30, 30] });
    }));
  };
  $('#rq').oninput = renderList;
  $('#addR').onclick = () => toast('استخدم أدوات الرسم أعلى يسار الخريطة: الخط للمسار، العلامة للنقطة', '', 5000);
  function siteModal(r, drawn) {
    const isNew = !r; r = r || {};
    const geomType = drawn ? drawn.geometry.type : r.geometry?.type;
    const kinds = Object.entries(App.meta.kinds).filter(([k]) => (geomType === 'Point' ? k !== 'route' : k === 'route'));
    const routesOpts = items.filter((x) => x.kind === 'route').map((x) => [x.id, x.code + ' — ' + x.axis_name]);
    const md = modal({ title: isNew ? 'إضافة عنصر مرجعي' : 'تعديل ' + r.code, body: `<form id="sf">
      <div class="row"><div class="field"><label>الكود *</label><input name="code" required value="${esc(r.code || '')}"></div>
      <div class="field"><label>النوع *</label><select name="kind">${opts(kinds, r.kind)}</select></div></div>
      <div class="field"><label>الاسم *</label><input name="name" required value="${esc(r.name || '')}"></div>
      ${geomType === 'Point' ? `<div class="field"><label>المسار التابع له</label><select name="parent_route_id">${opts(routesOpts, r.parent_route_id, '—')}</select></div>`
        : `<div class="row"><div class="field"><label>اسم المحور</label><input name="axis_name" value="${esc(r.axis_name || '')}"></div>
        <div class="field"><label>نوع الكابل القائم</label><select name="cable_type">${opts(App.meta.cable_types.map((c) => [c.code, c.name]), r.cable_type)}</select></div></div>
        <div class="row"><div class="field"><label>الجهات المشتركة</label><input name="parties" value="${esc(r.parties || '')}"></div><div class="field"><label>سنة الإنشاء</label><input type="number" name="install_year" value="${esc(r.install_year || '')}"></div></div>`}
      <div class="field"><label>ملاحظات</label><textarea name="notes">${esc(r.notes || '')}</textarea></div>
      ${drawn && drawn.length ? `<div class="muted">الطول المرسوم: <b>${fmtLen(drawn.length)}</b></div>` : ''}</form>`,
      footer: `<button class="btn primary" id="ss">حفظ</button>${!isNew ? '<button class="btn danger" id="sd">حذف</button>' : ''}<button class="btn" data-close>إلغاء</button>`,
      onClose: () => kit.drawn && kit.drawn.clearLayers() });
    $('#ss', md.el).onclick = async () => {
      const f = $('#sf', md.el); if (!f.reportValidity()) return;
      const d = formData(f);
      ['parent_route_id', 'install_year'].forEach((k) => { if (k in d) d[k] = d[k] ? +d[k] : null; });
      if (drawn) d.geometry = drawn.geometry;
      await api(isNew ? '/api/routes' : '/api/routes/' + r.id, { method: isNew ? 'POST' : 'PUT', body: d });
      md.close(); toast('تم الحفظ', 'ok'); load();
    };
    if (!isNew) $('#sd', md.el).onclick = async () => { if (await confirmBox(`حذف ${esc(r.code)}؟`, 'حذف', true)) { await api('/api/routes/' + r.id, { method: 'DELETE' }); md.close(); load(); } };
  }
  await load();
};

function normalizeAr(t) { return (t || '').replace(/[\u064B-\u065F\u0640]/g, '').replace(/[أإآ]/g, 'ا').replace(/ة/g, 'ه').replace(/ى/g, 'ي').toLowerCase(); }

/* ---------------- equipment ---------------- */
App.pages.equipment = async (main) => {
  const cats = { cable: 'الكوابل', material: 'الخامات', device: 'الأجهزة', tool: 'المعدات والأدوات' };
  const render = (items) => {
    main.innerHTML = `<div class="page-head"><div><h1>المعدات وإرشادات الاستخدام الفنية</h1><div class="sub">قائمة الخامات والمعدات المتداولة — تُستخدم في التقدير والاحتياجات</div></div>
      <button class="btn primary" id="addE">＋ إضافة بند</button></div>
      ${Object.entries(cats).map(([c, label]) => `<div class="section"><h3>${label}</h3>${items.filter((e) => e.category === c).map((e) => `
        <details class="eq"><summary><span><b>${esc(e.name)}</b> <span class="muted small mono">${esc(e.code)}</span></span><span>${availPill(e.default_availability)} <button class="btn sm" data-edit="${e.id}">تعديل</button></span></summary>
        <div>${e.guide ? `<div class="guide">📘 ${esc(e.guide)}</div>` : ''}${e.safety ? `<div class="guide safety">⚠️ ${esc(e.safety)}</div>` : ''}<div class="small muted" style="margin-top:6px">وحدة القياس: ${esc(e.unit || '—')}</div></div></details>`).join('')}</div>`).join('')}`;
    $$('[data-edit]', main).forEach((b) => (b.onclick = (ev) => { ev.preventDefault(); equipModal(items.find((e) => e.id === +b.dataset.edit)); }));
    $('#addE').onclick = () => equipModal(null);
  };
  const equipModal = (e) => {
    const isNew = !e; e = e || {};
    const md = modal({ title: isNew ? 'إضافة بند' : 'تعديل ' + e.name, wide: true, body: `<form id="ef">
      <div class="row3"><div class="field"><label>الكود *</label><input name="code" required value="${esc(e.code || '')}" ${isNew ? '' : 'disabled'}></div>
      <div class="field"><label>الفئة *</label><select name="category">${opts(cats, e.category)}</select></div><div class="field"><label>الوحدة</label><input name="unit" value="${esc(e.unit || 'عدد')}"></div></div>
      <div class="row"><div class="field"><label>الاسم *</label><input name="name" required value="${esc(e.name || '')}"></div>
      <div class="field"><label>حالة الإتاحة الافتراضية</label><select name="default_availability">${opts(App.meta.availability, e.default_availability || 'available')}</select></div></div>
      <div class="field"><label>إرشادات الاستخدام الفنية</label><textarea name="guide" rows="5">${esc(e.guide || '')}</textarea></div>
      <div class="field"><label>تعليمات السلامة</label><textarea name="safety">${esc(e.safety || '')}</textarea></div></form>`,
      footer: '<button class="btn primary" id="es">حفظ</button><button class="btn" data-close>إلغاء</button>' });
    $('#es', md.el).onclick = async () => {
      const f = $('#ef', md.el); if (!f.reportValidity()) return;
      render(await api(isNew ? '/api/equipment' : '/api/equipment/' + e.id, { method: isNew ? 'POST' : 'PUT', body: formData(f) })); md.close(); toast('تم الحفظ', 'ok');
    };
  };
  render(await api('/api/equipment'));
};

/* ---------------- settings ---------------- */
App.pages.settings = async (main) => {
  const items = await api('/api/settings');
  const groups = {};
  items.forEach((s) => (groups[s.grp] ||= []).push(s));
  main.innerHTML = `<div class="page-head"><div><h1>الإعدادات</h1><div class="sub">قواعد الحساب والتنبيهات قابلة للتعديل حسب تعليمات القسم — كل تعديل يُسجل في سجل التدقيق</div></div>
    <div class="btn-row"><button class="btn primary" id="saveS">💾 حفظ الإعدادات</button></div></div>
    <form id="sform" class="grid g2">${Object.entries(groups).map(([g, ss]) => `<div class="card"><h2>${esc(g)}</h2>${ss.map((s) => `
      <div class="field"><label>${esc(s.label)} ${s.unit ? `<span class="muted">(${esc(s.unit)})</span>` : ''}</label>
      ${s.key === 'default_cable_type' ? `<select name="${s.key}">${opts(App.meta.cable_types.map((c) => [c.code, c.name]), s.value)}</select>`
        : `<input name="${s.key}" value="${esc(s.value)}" ${typeof s.value === 'number' ? 'type="number" step="any" min="0"' : ''}>`}</div>`).join('')}</div>`).join('')}
    <div class="card"><h2>بيانات المحاكاة</h2><p class="muted">إعادة قاعدة البيانات إلى البيانات التجريبية الأصلية (يحذف كل ما تم إدخاله).</p>
      <button type="button" class="btn danger" id="resetBtn">♻️ إعادة تهيئة البيانات التجريبية</button></div></form>`;
  $('#saveS').onclick = async () => {
    const d = formData($('#sform'));
    await api('/api/settings', { method: 'PUT', body: d });
    App.meta = await api('/api/meta');
    $('#unitName').textContent = App.meta.settings.operator_unit; $('#stationName').textContent = App.meta.settings.station_name;
    toast('تم حفظ الإعدادات', 'ok');
  };
  $('#resetBtn').onclick = async () => {
    if (!(await confirmBox('سيتم حذف كل البيانات المدخلة وإعادة البيانات التجريبية. هل أنت متأكد؟', 'إعادة التهيئة', true))) return;
    await api('/api/admin/reset-demo', { method: 'POST', body: { confirm: 'RESET' } });
    sessionStorage.removeItem('seenAlerts'); App.seenAlerts = new Set();
    toast('تمت إعادة التهيئة', 'ok'); location.hash = '#/dashboard'; refreshHeader();
  };
};

/* ---------------- audit ---------------- */
App.pages.audit = async (main) => {
  const tables = { faxes_tickets: 'الفاكسات والعمليات', estimates_project: 'التقديرات', ticket_needs: 'الاحتياجات', routes_sites: 'المسارات والوصلات', teams_personnel: 'الأطقم', equipment_catalog: 'المعدات', settings: 'الإعدادات' };
  const actions = { INSERT: 'إضافة', UPDATE: 'تعديل', DELETE: 'حذف' };
  main.innerHTML = `<div class="page-head"><div><h1>سجل التدقيق الأمني والرقابي</h1><div class="sub">كل عمليات الإدخال والتعديل والحذف — القيمة القديمة والجديدة والجهاز المنفذ والتوقيت</div></div></div>
    <div class="filters"><select class="inp" id="at">${opts(tables, '', 'كل الجداول')}</select><select class="inp" id="aa">${opts(actions, '', 'كل الإجراءات')}</select>
    <input class="inp" id="aq" placeholder="بحث في القيم أو اسم المشغل"><span class="muted small" id="acount"></span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>#</th><th>التوقيت</th><th>الإجراء</th><th>الجدول</th><th>السجل</th><th>التغييرات</th><th>المشغل</th><th>الجهاز</th></tr></thead><tbody id="abody"></tbody></table></div>`;
  const diff = (o, n) => {
    o = o ? JSON.parse(o) : {}; n = n ? JSON.parse(n) : {};
    const keys = [...new Set([...Object.keys(o), ...Object.keys(n)])].filter((k) => !['created_at', 'updated_at', 'geometry_json', 'equipment_json'].includes(k)).slice(0, 8);
    return keys.map((k) => `<div class="small"><span class="muted mono">${esc(k)}</span>: ${o[k] !== undefined ? `<s style="color:#c62828">${esc(String(o[k]).slice(0, 60))}</s> ` : ''}${n[k] !== undefined ? `<span style="color:#2e7d32">${esc(String(n[k]).slice(0, 60))}</span>` : ''}</div>`).join('');
  };
  const load = async () => {
    const qs = new URLSearchParams({ limit: 300 });
    [['table', '#at'], ['action', '#aa'], ['q', '#aq']].forEach(([k, s]) => $(s).value && qs.set(k, $(s).value));
    const r = await api('/api/audit?' + qs);
    $('#acount').textContent = `${r.total} عملية`;
    $('#abody').innerHTML = r.items.map((a) => `<tr><td class="muted">${a.id}</td><td class="small">${fmtDate(a.at)}</td><td>${pill(a.action === 'DELETE' ? 'a-shortage' : a.action === 'INSERT' ? 'a-available' : 'a-needs_approval', actions[a.action])}</td>
      <td class="small">${esc(tables[a.table_name] || a.table_name)}</td><td>${a.record_id ?? '—'}</td><td>${diff(a.old_value, a.new_value)}</td><td class="small">${esc(a.actor || '')}</td><td class="small mono">${esc(a.device || '')}</td></tr>`).join('') || '<tr><td colspan="8" class="empty">لا توجد عمليات</td></tr>';
  };
  let timer;
  $('#aq').oninput = () => { clearTimeout(timer); timer = setTimeout(load, 300); };
  ['#at', '#aa'].forEach((s) => ($(s).onchange = load));
  await load();
};
