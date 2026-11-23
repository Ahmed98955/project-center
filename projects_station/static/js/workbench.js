/* Ticket workbench: map half (locate / draw) + details half (triage card, estimate, needs, tracking, original fax). */
App.pages.ticket = async (main, id) => {
  main.className = 'full';
  const S = { t: null, tab: sessionStorage.getItem('wbTab') || 'summary', drawn: null, dirty: false, preview: null, routes: [], teams: [] };
  [S.t, S.routes, S.teams] = await Promise.all([api('/api/tickets/' + id), api('/api/routes?kind=route'), api('/api/teams')]);
  const m = App.meta;
  main.innerHTML = `<div class="wb"><div class="wb-map"><div class="map" id="wbMap"></div></div>
    <div class="wb-side"><div class="wb-head" id="wbHead"></div><div class="tabs" id="wbTabs"></div><div class="tab-body" id="wbBody"></div><div class="wb-foot" id="wbFoot"></div></div></div>`;

  /* ----- map half ----- */
  const kit = MapKit.create($('#wbMap'));
  App.cleanup.push(kit.destroy);
  kit.addSearch($('#wbMap')); kit.addLegend($('#wbMap'));
  kit.history.addTo(kit.map);
  kit.loadLayers({ exclude: S.t.id });
  const info = document.createElement('div'); info.className = 'map-info'; $('#wbMap').appendChild(info);
  L.DomEvent.disableClickPropagation(info);
  kit.enableDraw({ onChange: (d) => { S.drawn = d; S.dirty = true; renderInfo(); } });
  if (S.t.geometry) kit.setDrawn(S.t.geometry); else if (S.t.location_text) setTimeout(() => autoSearch(S.t.location_text), 300);
  S.drawn = kit.getDrawn();

  function autoSearch(text) {
    const input = $('.map-search input', $('#wbMap'));
    if (!input) return;
    input.value = text.split(/[—\-–،,]/)[0].trim();
    input.dispatchEvent(new Event('input'));
  }

  function renderInfo() {
    const d = S.drawn;
    const geomTxt = !d ? '<span class="muted">لم يُحدد الموقع بعد — استخدم أدوات الرسم (يسار أعلى الخريطة): <b>العلامة</b> لنقطة العطل أو <b>الخط</b> لمسار الخط الجديد</span>'
      : d.geometry.type === 'Point' ? `📍 نقطة: <span class="mono">${d.geometry.coordinates[1].toFixed(5)}, ${d.geometry.coordinates[0].toFixed(5)}</span>`
      : `〰️ مسار بطول <b>${fmtLen(d.length)}</b> (${d.geometry.coordinates.length} نقطة)`;
    info.innerHTML = `<div>${geomTxt}</div>
      ${d ? `<div class="btn-row" style="margin-top:6px"><select class="inp" id="terrainSel" style="width:auto">${opts(m.terrains, S.t.terrain || 'open')}</select>
        <button class="btn primary sm" id="saveLoc" ${S.dirty ? '' : 'disabled'}>💾 حفظ الموقع وفحص السجل</button>
        ${!S.dirty && S.t.geometry ? '<span class="small" style="color:var(--accent)">✔ محفوظ</span>' : ''}</div>` : ''}`;
    if (d) {
      $('#saveLoc', info).onclick = saveLocation;
      $('#terrainSel', info).onchange = () => { S.dirty = true; renderInfo(); };
    }
  }

  async function saveLocation() {
    const terrain = $('#terrainSel', info)?.value;
    const r = await api(`/api/tickets/${S.t.id}/location`, { method: 'PUT', body: { geometry: S.drawn.geometry, terrain } });
    S.dirty = false; S.t = r; S.preview = null;
    toast('تم حفظ الموقع', 'ok');
    renderAll();
    showDetection(r.detection.alerts, true);
  }

  function showDetection(alerts, fromSave) {
    if (!alerts.length) { if (fromSave) toast('لا يوجد سجل سابق أو عمليات في النطاق المحيط', ''); return; }
    const urgent = alerts.some((a) => a.severity === 'urgent');
    const md = modal({ title: urgent ? '🚨 تنبيه عاجل — محرك الاكتشاف' : '🔎 نتائج فحص الموقع', urgent, wide: true,
      body: alerts.map((a) => alertHtml({ ...a, ticket_id: a.related && a.type !== 'repeat_fault' ? a.related[0].id : null })).join(''),
      footer: '<button class="btn primary" data-close>تم الاطلاع</button>' });
    bindAlertClicks(md.el);
  }

  /* ----- details half ----- */
  const TABS = [['summary', '📋 الملخص'], ['estimate', '🧮 التقدير الفني'], ['needs', '📦 الاحتياجات'], ['tracking', '⏱️ التتبع'], ['original', '📠 الفاكس الأصلي'], ['history', '🗂️ سجل النقطة']];

  function renderHead() {
    const t = S.t;
    const idx = m.statuses.findIndex((s) => s[0] === t.status);
    $('#wbHead').innerHTML = `<div class="btn-row" style="justify-content:space-between"><div class="btn-row"><a href="#/faxes" class="btn sm">→ رجوع</a><b style="font-size:15px">${esc(t.fax_no)}</b>
      ${typePill(t)} ${prioPill(t)} ${statusPill(t)} ${t.forwarded_to_command ? pill('a-available', '✔ مُمرر للقيادة') : pill('s-closed', 'لم يُمرر للقيادة')}</div>
      <span class="small muted">ورد ${fmtDate(t.received_at)} (${ago(t.received_at)})</span></div>
      <div class="title">${esc(t.title)}</div>
      <div class="status-flow">${m.statuses.map(([k, v], i) => `<span class="${i < idx ? 'done' : i === idx ? 'cur' : ''}">${v}</span>`).join('')}</div>
      ${t.status === 'awaiting_coordination' ? `<div class="small" style="margin-top:4px;color:${t.wait.overdue ? 'var(--red)' : '#b26a00'}">⏳ في الانتظار منذ ${fmtN(t.wait.hours_in_status)} ساعة — الحد المسموح ${t.wait.max_hours} ساعة ${t.wait.overdue ? '(تجاوز الحد!)' : ''}</div>` : ''}`;
  }

  function renderTabs() {
    $('#wbTabs').innerHTML = TABS.map(([k, v]) => `<button data-tab="${k}" class="${S.tab === k ? 'active' : ''}">${v}${k === 'needs' && S.t.needs.length ? ` (${S.t.needs.length})` : ''}</button>`).join('');
    $$('#wbTabs button').forEach((b) => (b.onclick = () => { S.tab = b.dataset.tab; sessionStorage.setItem('wbTab', S.tab); renderTabs(); renderBody(); }));
  }

  function renderFoot() {
    const t = S.t;
    const label = Object.fromEntries(m.statuses);
    $('#wbFoot').innerHTML = `${t.allowed_next.map((s) => `<button class="btn ${s === 'closed' ? 'navy' : ''}" data-st="${s}">← ${label[s]}</button>`).join('')}
      <span style="flex:1"></span>
      <button class="btn" id="printBtn" title="طباعة بطاقة الملخص">🖨️</button>
      ${!t.forwarded_to_command ? '<button class="btn danger sm" id="delBtn">حذف</button>' : ''}
      <button class="btn primary big" id="fwdBtn">📤 حفظ وتمرير إلى القيادة</button>`;
    $$('[data-st]', $('#wbFoot')).forEach((b) => (b.onclick = () => statusModal(b.dataset.st)));
    $('#fwdBtn').onclick = forward;
    $('#printBtn').onclick = () => window.print();
    const del = $('#delBtn'); if (del) del.onclick = async () => { if (await confirmBox('حذف هذا الفاكس نهائيًا؟', 'حذف', true)) { await api('/api/tickets/' + t.id, { method: 'DELETE' }); toast('تم الحذف', 'ok'); location.hash = '#/faxes'; } };
  }

  async function forward() {
    if (S.dirty) return toast('احفظ الموقع المرسوم أولًا', 'warn');
    if (!S.t.has_estimate && S.t.fax_type !== 'coordination' && !(await confirmBox('لم يتم حساب التقدير الفني بعد. هل تريد التمرير إلى القيادة بدون تقدير؟', 'تمرير'))) return;
    S.t = await api(`/api/tickets/${S.t.id}/forward`, { method: 'POST' });
    toast('تم الحفظ والتمرير إلى القيادة ✔ (سيظهر على شاشة القائد في الجزء الثاني)', 'ok', 5000);
    renderAll(); refreshHeader();
  }

  function statusModal(status) {
    const t = S.t, label = Object.fromEntries(m.statuses)[status];
    const teamNames = [...new Set(S.teams.map((p) => p.team_name).filter(Boolean))];
    const teamInfo = (n) => { const ps = S.teams.filter((p) => p.team_name === n); return `${n} — ${ps.some((p) => p.status === 'on_mission') ? 'في مأمورية' : 'متاحة'}`; };
    const md = modal({ title: `تغيير الحالة إلى «${label}»`, body: `<form id="stf">
      ${status === 'in_progress' || status === 'preparing' ? `<div class="field"><label>المفرزة المكلفة ${status === 'in_progress' ? '*' : ''}</label><select name="assigned_team">${opts(teamNames.map((n) => [n, teamInfo(n)]), t.assigned_team, '— اختر —')}</select></div>` : ''}
      ${status === 'closed' && t.fax_type === 'fault' ? `<div class="field"><label>سبب العطل * (يُستخدم في التنبيهات المستقبلية)</label><input name="cause" list="causes" value="${esc(t.cause || '')}">
        <datalist id="causes"><option>حفر جهة خارجية دون تنسيق</option><option>قطع بمعدات رصف</option><option>سرقة جزء من الكابل</option><option>حريق</option><option>تآكل الوصلة ودخول مياه</option><option>عيب تصنيع</option></datalist></div>` : ''}
      ${status === 'closed' ? `<div class="field"><label>الإجراءات المتخذة *</label><textarea name="resolution">${esc(t.resolution || '')}</textarea></div>` : ''}
      <div class="field"><label>ملاحظات</label><textarea name="notes"></textarea></div></form>`,
      footer: '<button class="btn primary" id="stOk">تأكيد</button><button class="btn" data-close>إلغاء</button>' });
    $('#stOk', md.el).onclick = async () => {
      const d = formData($('#stf', md.el)); d.status = status;
      S.t = await api(`/api/tickets/${S.t.id}/status`, { method: 'POST', body: d });
      md.close(); toast(`تم تغيير الحالة إلى «${label}»`, 'ok'); renderAll(); refreshHeader();
    };
  }

  /* ----- tab bodies ----- */
  const body = () => $('#wbBody');
  function renderBody() { ({ summary, estimate, needs, tracking, original, history: pointHist })[S.tab](); }

  async function summary() {
    const t = S.t;
    body().innerHTML = `<div id="detBox"></div>
      <form id="sumF" class="section"><h3>بطاقة الملخص التنفيذي</h3>
      <div class="row3"><div class="field"><label>رقم الفاكس</label><input name="fax_no" value="${esc(t.fax_no)}" required></div>
        <div class="field"><label>النوع</label><select name="fax_type">${opts(m.fax_types, t.fax_type)}</select></div>
        <div class="field"><label>الأهمية</label><select name="priority">${opts(m.priorities, t.priority)}</select></div></div>
      <div class="field"><label>العنوان</label><input name="title" value="${esc(t.title)}" required minlength="3"></div>
      <div class="field"><label>الملخص التنفيذي</label><textarea name="summary" required minlength="3">${esc(t.summary)}</textarea></div>
      <div class="field"><label>المطلوب في سطر واحد</label><input name="required_action" value="${esc(t.required_action || '')}"></div>
      <div class="row"><div class="field"><label>الموقع (وصف)</label><input name="location_text" value="${esc(t.location_text || '')}"></div>
        <div class="field"><label>الجهة الطالبة / المتسببة</label><input name="requesting_party" value="${esc(t.requesting_party || '')}"></div></div>
      <div class="row"><div class="field"><label>المسار المرتبط</label><select name="route_id">${opts(S.routes.map((r) => [r.id, r.code + ' — ' + r.axis_name]), t.route_id, '— غير مرتبط —')}</select></div>
        <div class="field"><label>المفرزة المكلفة</label><select name="assigned_team">${opts([...new Set(S.teams.map((p) => p.team_name))].map((n) => [n, n]), t.assigned_team, '—')}</select></div></div>
      ${t.fax_type === 'fault' || t.status === 'closed' ? `<div class="row"><div class="field"><label>سبب العطل</label><input name="cause" value="${esc(t.cause || '')}"></div>
        <div class="field"><label>الإجراءات المتخذة</label><input name="resolution" value="${esc(t.resolution || '')}"></div></div>` : ''}
      <button class="btn primary" type="submit">💾 حفظ البطاقة</button></form>`;
    $('#sumF').onsubmit = async (e) => {
      e.preventDefault();
      const d = formData(e.target);
      d.route_id = d.route_id ? +d.route_id : null;
      ['assigned_team', 'cause', 'resolution', 'required_action', 'location_text', 'requesting_party'].forEach((k) => { if (k in d && d[k] === '') d[k] = null; });
      S.t = await api('/api/tickets/' + t.id, { method: 'PUT', body: d });
      toast('تم حفظ البطاقة', 'ok'); renderHead(); renderFoot();
    };
    if (t.geometry) {
      const det = await api(`/api/tickets/${t.id}/detect`, { silent: true }).catch(() => ({ alerts: [] }));
      if (S.tab !== 'summary') return;
      $('#detBox').innerHTML = det.alerts.length ? `<div class="section"><h3>🔎 تنبيهات الموقع (محرك الاكتشاف)</h3>${det.alerts.map((a) => alertHtml({ ...a, ticket_id: a.related && a.type !== 'repeat_fault' ? a.related[0].id : null })).join('')}</div>` : '';
      bindAlertClicks($('#detBox'));
    } else {
      $('#detBox').innerHTML = `<div class="alert-item info"><div class="ic">📍</div><div><div class="t">الخطوة التالية: تحديد الموقع</div><div class="m">ابحث عن اسم المكان في خانة البحث على الخريطة، ثم حدد نقطة العطل أو ارسم مسار الخط الجديد واضغط «حفظ الموقع».</div></div></div>`;
    }
  }

  function estInputs() {
    const f = $('#estF');
    const d = formData(f);
    const overrides = {};
    $$('[data-ov]', body()).forEach((i) => { if (i.value !== '') overrides[i.dataset.ov] = +i.value; });
    return { task_nature: d.task_nature, terrain: d.terrain, cable_type: d.cable_type, measured_length_m: d.measured_length_m === '' ? null : +d.measured_length_m,
      reserve_pct: +d.reserve_pct, connection_points: +d.connection_points || 0, splice_closures: +d.splice_closures || 1, overrides,
      length_source: S.lengthManual ? 'manual' : 'map' };
  }

  function estimate() {
    const t = S.t, e = t.estimate || {}, s = m.settings;
    const mapLen = S.drawn && S.drawn.geometry.type !== 'Point' ? Math.round(S.drawn.length) : (t.geometry && t.geometry.type !== 'Point' ? null : 0);
    const defTask = e.task_nature || (t.fax_type === 'fault' ? 'fault_repair' : t.fax_type === 'project' ? 'cable_laying' : 'measurement');
    const route = S.routes.find((r) => r.id === t.route_id);
    const defCable = e.cable_type || (route && route.cable_type) || s.default_cable_type;
    const len = e.measured_length_m ?? (mapLen || '');
    body().innerHTML = `<form id="estF" class="section"><h3>مدخلات التقدير</h3>
      <div class="row"><div class="field"><label>طبيعة المهمة</label><select name="task_nature">${opts(m.task_natures, defTask)}</select></div>
        <div class="field"><label>طبيعة الأرض</label><select name="terrain">${opts(m.terrains, e.terrain || t.terrain || 'open')}</select></div></div>
      <div class="row"><div class="field"><label>نوع الكابل المطلوب</label><select name="cable_type">${opts(m.cable_types.map((c) => [c.code, c.name]), defCable)}</select></div>
        <div class="field"><label>المسافة المقاسة (م) <button type="button" class="btn sm" id="fromMap">📏 من الخريطة</button></label><input type="number" min="0" step="any" name="measured_length_m" value="${len}"></div></div>
      <div class="row3"><div class="field"><label>نسبة الاحتياطي والهالك: <b id="resV">${e.reserve_pct ?? s.reserve_pct_default}%</b></label>
          <input type="range" name="reserve_pct" min="${s.reserve_pct_min}" max="${s.reserve_pct_max}" step="0.5" value="${e.reserve_pct ?? s.reserve_pct_default}"></div>
        <div class="field"><label>عدد نقاط الربط والتحويل</label><input type="number" min="0" name="connection_points" value="${e.connection_points ?? (t.fax_type === 'project' ? 2 : 0)}"></div>
        <div class="field" id="closF"><label>عدد الجلب القائمة (للحام فقط)</label><input type="number" min="1" name="splice_closures" value="${e.splice_closures || 1}"></div></div>
      ${!t.geometry ? '<div class="small" style="color:var(--orange)">⚠️ لم يُحفظ موقع بعد — زمن التحرك لن يُحسب. حدد الموقع على الخريطة أولًا.</div>' : ''}</form>
      <div id="estOut"></div>`;
    const f = $('#estF');
    const sync = () => { $('#resV').textContent = f.reserve_pct.value + '%'; $('#closF').style.display = f.task_nature.value === 'fiber_splicing' ? '' : 'none'; };
    sync();
    let timer;
    const upd = () => { sync(); clearTimeout(timer); timer = setTimeout(runPreview, 200); };
    f.addEventListener('input', upd); f.addEventListener('change', upd);
    f.measured_length_m.addEventListener('input', () => (S.lengthManual = true));
    $('#fromMap').onclick = () => {
      const d = S.drawn;
      if (!d || d.geometry.type === 'Point') return toast('ارسم مسارًا (خط) على الخريطة لقياس المسافة', 'warn');
      f.measured_length_m.value = Math.round(d.length); S.lengthManual = false; upd();
    };
    runPreview(e.manual_overrides || {});
  }

  async function runPreview(initialOverrides) {
    const inp = estInputs();
    if (initialOverrides && typeof initialOverrides === 'object' && !(initialOverrides instanceof Event)) inp.overrides = { ...initialOverrides, ...inp.overrides };
    const r = await api(`/api/tickets/${S.t.id}/estimate/preview`, { method: 'POST', body: inp, silent: true }).catch((e) => { $('#estOut').innerHTML = `<div class="alert-item warning"><div class="m">${esc(e.message)}</div></div>`; });
    if (!r || S.tab !== 'estimate') return;
    S.preview = r;
    const ov = r.manual_overrides || {};
    const box = (k, label, v, unit) => `<div class="est-box ${k in ov ? 'overridden' : ''}"><div class="l">${label}</div><div class="v">${v}</div>
      ${k ? `<input data-ov="${k}" type="number" step="any" min="0" placeholder="تعديل يدوي${unit ? ' (' + unit + ')' : ''}" value="${k in ov ? ov[k] : ''}">` : ''}</div>`;
    $('#estOut').innerHTML = `<div class="section"><h3>المخرجات التقديرية <span class="muted small">(يمكن تعديل أي قيمة يدويًا بعد المعاينة الميدانية)</span></h3>
      <div class="est-grid">
        ${box('total_cable_m', `طول الكابل الكلي — ${esc(r.cable_name)}`, fmtLen(r.total_cable_m), 'م')}
        ${box('splice_closures', 'جلب اللحام / علب التوصيل', fmtN(r.splice_closures))}
        ${box('fusion_splices', 'عدد لحامات الألياف', fmtN(r.fusion_splices))}
        ${box('media_converters', 'أجهزة Media Converter', fmtN(r.media_converters))}
        ${box('travel_hours', `زمن التحرك (ذهاب وعودة ${fmtN(r.travel_km)} كم)`, fmtHours(r.travel_hours), 'ساعة')}
        ${box('laying_hours', 'زمن المد', fmtHours(r.laying_hours), 'ساعة')}
        ${box('splicing_hours', 'زمن اللحام', fmtHours(r.splicing_hours), 'ساعة')}
        ${box('testing_hours', 'زمن الاختبار', fmtHours(r.testing_hours), 'ساعة')}
        ${box('estimated_hours', `الزمن التقديري الكلي (معامل ${r.difficulty_factor})`, `${fmtN(r.estimated_hours)} ساعة<div class="small muted">≈ ${fmtN(r.estimated_days)} يوم عمل</div>`, 'ساعة')}
      </div>
      <div class="breakdown"><b>طريقة الحساب:</b><br>${r.breakdown.map(esc).join('<br>')}</div></div>
      <div class="section"><h3>المعدات والخامات المقترحة (${r.equipment.length})</h3>${equipList(r.equipment)}</div>
      <div class="btn-row"><button class="btn primary" id="saveEst">💾 حفظ التقدير</button><button class="btn navy" id="saveEstNeeds">💾 حفظ وتوليد قائمة الاحتياجات</button>
      ${S.t.estimate ? `<span class="small muted">آخر حفظ: ${fmtDate(S.t.estimate.updated_at)}</span>` : '<span class="small" style="color:var(--orange)">لم يُحفظ بعد</span>'}</div>`;
    $$('[data-ov]', $('#estOut')).forEach((i) => i.addEventListener('change', () => runPreview()));
    $('#saveEst').onclick = () => saveEst(false);
    $('#saveEstNeeds').onclick = () => saveEst(true);
  }

  function equipList(items) {
    return items.map((e) => `<details class="eq"><summary><span>${{ cable: '🧵', material: '🔩', device: '📟', tool: '🛠️' }[e.category] || '•'} <b>${esc(e.name)}</b> — ${fmtN(e.quantity)} ${esc(e.unit)}</span>
      <span>${availPill(e.availability)}</span></summary><div><div class="small muted">${esc(e.reason)}</div>
      ${e.guide ? `<div class="guide">📘 <b>إرشادات الاستخدام:</b> ${esc(e.guide)}</div>` : ''}${e.safety ? `<div class="guide safety">⚠️ ${esc(e.safety)}</div>` : ''}</div></details>`).join('');
  }

  async function saveEst(gen) {
    if (gen && S.t.needs.length && !(await confirmBox('سيتم استبدال قائمة الاحتياجات الحالية بالقائمة المقترحة. متابعة؟', 'متابعة'))) return;
    const inp = estInputs(); inp.generate_needs = gen;
    S.t = await api(`/api/tickets/${S.t.id}/estimate`, { method: 'PUT', body: inp });
    toast(gen ? 'تم حفظ التقدير وتوليد الاحتياجات' : 'تم حفظ التقدير', 'ok');
    if (gen) { S.tab = 'needs'; sessionStorage.setItem('wbTab', 'needs'); }
    renderAll();
  }

  function needs() {
    const t = S.t, c = t.needs_counts || {};
    body().innerHTML = `<div class="section"><h3>قائمة الاحتياجات الفنية للعملية</h3>
      <p class="small muted">يسجل القسم الاحتياجات فقط — قرار الإتاحة والتصديق تحت إشراف القادة عبر مؤشر الحالة.</p>
      <div class="chips" style="margin-bottom:10px">${pill('a-available', `متاح: ${c.available || 0}`)} ${pill('a-needs_approval', `يحتاج تصديق: ${c.needs_approval || 0}`)} ${pill('a-shortage', `عجز: ${c.shortage || 0}`)}
        <span style="flex:1"></span>${t.has_estimate ? '<button class="btn sm" id="regen">↻ توليد من التقدير</button>' : ''}</div>
      ${t.needs.length ? `<table class="tbl"><tr><th>البند</th><th style="width:90px">الكمية</th><th>الوحدة</th><th style="width:150px">الحالة</th><th>ملاحظات</th><th></th></tr>
        ${t.needs.map((n) => `<tr><td><b>${esc(n.item_name)}</b></td><td><input class="inp" type="number" min="0" step="any" data-q="${n.id}" value="${n.quantity}"></td><td class="small">${esc(n.unit || '')}</td>
        <td><select class="inp" data-a="${n.id}">${opts(m.availability, n.availability)}</select></td><td class="small muted">${esc(n.notes || '')}</td>
        <td><button class="btn sm danger" data-del="${n.id}">✕</button></td></tr>`).join('')}</table>` : `<div class="empty">لا توجد احتياجات — احسب التقدير الفني ثم اضغط «حفظ وتوليد قائمة الاحتياجات»، أو أضف بندًا يدويًا.</div>`}
      <form id="needF" class="row3" style="margin-top:12px;align-items:end"><div class="field"><label>بند جديد</label><input name="item_name" required list="eqList"></div>
        <div class="field"><label>الكمية</label><input name="quantity" type="number" min="0" step="any" value="1"></div>
        <div class="btn-row" style="margin-bottom:10px"><input name="unit" class="inp" placeholder="الوحدة" style="width:80px"><button class="btn primary">＋ إضافة</button></div></form>
      <datalist id="eqList"></datalist></div>`;
    api('/api/equipment', { silent: true }).then((eq) => { const dl = $('#eqList'); if (dl) dl.innerHTML = eq.map((e) => `<option value="${esc(e.name)}">`).join(''); });
    const put = async (nid, d) => { S.t = await api('/api/needs/' + nid, { method: 'PUT', body: d }); renderHead(); renderTabs(); needs(); };
    $$('[data-a]', body()).forEach((s) => (s.onchange = () => put(s.dataset.a, { availability: s.value })));
    $$('[data-q]', body()).forEach((s) => (s.onchange = () => put(s.dataset.q, { quantity: +s.value })));
    $$('[data-del]', body()).forEach((b) => (b.onclick = async () => { S.t = await api('/api/needs/' + b.dataset.del, { method: 'DELETE' }); renderTabs(); needs(); }));
    $('#needF').onsubmit = async (e) => { e.preventDefault(); const d = formData(e.target); d.quantity = +d.quantity || 1; S.t = await api(`/api/tickets/${t.id}/needs`, { method: 'POST', body: d }); renderTabs(); needs(); };
    const rg = $('#regen'); if (rg) rg.onclick = async () => { if (await confirmBox('استبدال القائمة الحالية بالمقترحة من التقدير؟')) { S.t = await api(`/api/tickets/${t.id}/needs/generate`, { method: 'POST' }); renderTabs(); needs(); } };
  }

  function tracking() {
    const t = S.t;
    body().innerHTML = `<div class="section"><h3>سجل التتبع الزمني الآلي</h3><ul class="timeline">${t.updates.map((u) => `<li class="${u.old_status === u.new_status ? 'note' : ''}">
      <div><b>${u.old_status === u.new_status ? '📝 ملاحظة' : (u.old_label ? `${esc(u.old_label)} ← ` : '') + esc(u.new_label)}</b></div>
      ${u.notes ? `<div>${esc(u.notes)}</div>` : ''}<div class="when">${fmtDate(u.at)} · ${esc(u.actor || '')}</div></li>`).join('')}</ul></div>
      <form id="noteF" class="section"><div class="field"><label>إضافة ملاحظة متابعة</label><textarea name="notes" required></textarea></div><button class="btn primary">＋ إضافة</button></form>
      <div class="section"><h3>بيانات زمنية</h3><dl class="kv"><dt>تاريخ الورود</dt><dd>${fmtDate(t.received_at)}</dd><dt>آخر تغيير حالة</dt><dd>${fmtDate(t.status_changed_at)} (${ago(t.status_changed_at)})</dd>
      <dt>المدة في الحالة الحالية</dt><dd>${fmtN(t.wait.hours_in_status)} ساعة</dd>${t.forwarded_at ? `<dt>التمرير للقيادة</dt><dd>${fmtDate(t.forwarded_at)}</dd>` : ''}${t.closed_at ? `<dt>الإغلاق</dt><dd>${fmtDate(t.closed_at)}</dd>` : ''}</dl></div>`;
    $('#noteF').onsubmit = async (e) => { e.preventDefault(); S.t = await api(`/api/tickets/${t.id}/notes`, { method: 'POST', body: formData(e.target) }); tracking(); };
  }

  function original() {
    const t = S.t;
    const url = `/api/tickets/${t.id}/file?v=${encodeURIComponent(t.updated_at)}`;
    const isPdf = (t.original_filename || t.original_file || '').toLowerCase().endsWith('.pdf');
    body().innerHTML = `<div class="section"><h3>ملف الفاكس الأصلي</h3>
      ${t.has_file ? `<div class="btn-row" style="margin-bottom:8px"><span class="muted small">${esc(t.original_filename)}</span><a class="btn sm" href="${url}" target="_blank">فتح في نافذة جديدة</a></div>
        ${isPdf ? `<iframe class="fax-preview" src="${url}"></iframe>` : `<img class="fax-preview" src="${url}" alt="الفاكس الأصلي">`}`
        : '<div class="empty">لم يُرفق ملف الفاكس الأصلي بعد</div>'}
      <div class="drop" id="drop2" style="margin-top:10px">${t.has_file ? 'استبدال الملف: ' : ''}اسحب ملف PDF أو صورة هنا أو اضغط للاختيار
        <input type="file" id="f2" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.gif,.webp" style="display:block;margin:8px auto 0;max-width:100%;font-size:12px"></div>
      ${t.has_file ? '<div class="btn-row" style="margin-top:8px"><button class="btn sm" id="extTxt" type="button">🔍 استخراج نص الفاكس</button></div><div id="extOut"></div>' : ''}
      <p class="small muted">الإضافة المساعدة على المتصفح (Browser Extension) لالتقاط الفاكس من منظومة الويب مباشرة ستُضاف في مرحلة لاحقة — الإرفاق اليدوي متاح دائمًا كبديل.</p></div>`;
    const extBtn = $('#extTxt');
    if (extBtn) extBtn.onclick = async () => {
      const out = $('#extOut');
      out.innerHTML = '<div class="small muted">⏳ جاري استخراج النص…</div>';
      const fd = new FormData(); fd.append('ticket_id', t.id);
      try {
        const r = await api('/api/files/extract-text', { method: 'POST', body: fd, silent: true });
        out.innerHTML = r.ok && r.text && r.text.trim()
          ? `<div class="section" style="margin-top:6px"><h3>🧠 النص المستخرج <span class="muted small">(${r.chars} حرف — ${r.pages} صفحة)</span></h3>
             <textarea class="inp" readonly style="width:100%;height:140px">${esc(r.text)}</textarea>
             <div class="btn-row" style="margin-top:6px"><button class="btn sm" id="cpTxt2" type="button">📋 نسخ النص</button></div></div>`
          : `<div class="alert-item info"><div class="ic">ℹ️</div><div class="m">${esc(r.message || 'لا يوجد نص قابل للاستخراج')}</div></div>`;
        const cp = $('#cpTxt2', out);
        if (cp) cp.onclick = () => navigator.clipboard && navigator.clipboard.writeText(r.text).then(() => toast('تم النسخ', 'ok'));
      } catch (e) { out.innerHTML = '<div class="small muted">تعذر الاستخراج</div>'; }
    };
    const drop = $('#drop2'), fi = $('#f2');
    const up = async (f) => { if (!f) return; const fd = new FormData(); fd.append('file', f); S.t = await api(`/api/tickets/${t.id}/file`, { method: 'POST', body: fd }); toast('تم إرفاق الملف', 'ok'); original(); };
    drop.onclick = (e) => { if (e.target !== fi) fi.click(); }; fi.onchange = () => up(fi.files[0]);
    drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); }; drop.ondragleave = () => drop.classList.remove('over');
    drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove('over'); up(e.dataTransfer.files[0]); };
  }

  async function pointHist() {
    const t = S.t;
    if (!t.geometry) { body().innerHTML = '<div class="empty">حدد الموقع على الخريطة أولًا لعرض سجل النقطة</div>'; return; }
    const r = m.settings.repeat_radius_m;
    const pt = t.geometry.type === 'Point' ? t.geometry.coordinates : null;
    const [lon, lat] = pt || [t.lon, t.lat];
    const items = (await api(`/api/history/near?lat=${lat}&lon=${lon}&radius=${t.geometry.type === 'Point' ? r : Math.max(r, 1500)}`)).filter((x) => x.id !== t.id);
    if (S.tab !== 'history') return;
    body().innerHTML = `<div class="section"><h3>كل العمليات المسجلة في نطاق ${fmtLen(t.geometry.type === 'Point' ? r : Math.max(r, 1500))} من الموقع</h3>
      ${items.length ? `<table class="tbl"><tr><th>الفاكس</th><th>النوع</th><th>الحالة</th><th>السبب</th><th>الإجراء</th><th>التاريخ</th><th>المسافة</th></tr>
      ${items.map((x) => `<tr class="click" data-ticket="${x.id}"><td>${esc(x.fax_no)}</td><td>${typePill(x)}</td><td>${statusPill(x)}</td><td class="small">${esc(x.cause || '—')}</td><td class="small">${esc(x.resolution || '—')}</td><td class="small">${fmtDate(x.closed_at || x.received_at, false)}</td><td>${fmtLen(x.distance_m)}</td></tr>`).join('')}</table>`
      : '<div class="empty">لا يوجد سجل سابق في هذا النطاق</div>'}</div>`;
    bindAlertClicks(body());
  }

  function renderAll() { renderHead(); renderTabs(); renderBody(); renderFoot(); renderInfo(); }
  renderAll();
};
