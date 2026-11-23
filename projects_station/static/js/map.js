/* Map module: offline vector basemap, network & ticket layers, drawing, place search. */
const MapKit = (() => {
  const ROAD_STYLE = {
    motorway: { color: '#e57373', weight: 3.2 }, trunk: { color: '#f0a35e', weight: 2.8 }, primary: { color: '#f3c766', weight: 2.2 },
    secondary: { color: '#c9c9c9', weight: 1.6 }, tertiary: { color: '#d8d8d8', weight: 1 }, rail: { color: '#8d8d8d', weight: 1, dashArray: '4 4' },
    river: { color: '#64b5f6', weight: 6, opacity: 0.85 },
  };
  const CABLE_COLOR = (c) => (!c ? '#5c6bc0' : c.startsWith('copper') ? '#8d6e63' : c.endsWith('96') ? '#6a1b9a' : c.endsWith('48') ? '#1565c0' : '#00897b');
  const TYPE_COLOR = { fault: '#d32f2f', project: '#2e7d32', coordination: '#f9a825' };
  let basemapCache = null;
  const loadBasemap = () => (basemapCache ||= Promise.all([
    fetch('/static/map/egypt_roads.geojson').then((r) => r.json()),
    fetch('/static/map/cairo_roads.geojson').then((r) => r.json()),
  ]));
  const style = (f) => ({ ...(ROAD_STYLE[f.properties.c] || ROAD_STYLE.tertiary), opacity: ROAD_STYLE[f.properties.c]?.opacity ?? 0.95, interactive: false });

  function haversine(a, b) {
    const R = 6371008.8, toR = Math.PI / 180;
    const dLat = (b.lat - a.lat) * toR, dLon = (b.lng - a.lng) * toR;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * toR) * Math.cos(b.lat * toR) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
  }
  function lengthOf(latlngs) { let s = 0; for (let i = 1; i < latlngs.length; i++) s += haversine(latlngs[i - 1], latlngs[i]); return s; }

  function setupDrawLocale() {
    if (!L.drawLocal) return;
    const d = L.drawLocal.draw;
    d.toolbar.buttons.polyline = 'رسم مسار خط (جديد أو متضرر)';
    d.toolbar.buttons.marker = 'تحديد نقطة العطل';
    d.toolbar.actions = { title: 'إلغاء الرسم', text: 'إلغاء' };
    d.toolbar.finish = { title: 'إنهاء الرسم', text: 'إنهاء' };
    d.toolbar.undo = { title: 'حذف آخر نقطة', text: 'حذف آخر نقطة' };
    d.handlers.marker.tooltip.start = 'اضغط على الخريطة لتحديد نقطة العطل';
    d.handlers.polyline.tooltip = { start: 'اضغط لبدء رسم المسار', cont: 'اضغط لإضافة نقطة', end: 'اضغط على آخر نقطة للإنهاء' };
    const e = L.drawLocal.edit;
    e.toolbar.buttons = { edit: 'تعديل الشكل', editDisabled: 'لا يوجد شكل', remove: 'حذف الشكل', removeDisabled: 'لا يوجد شكل' };
    e.toolbar.actions = { save: { title: 'حفظ', text: 'حفظ' }, cancel: { title: 'إلغاء', text: 'إلغاء' }, clearAll: { title: 'مسح الكل', text: 'مسح الكل' } };
    e.handlers.edit.tooltip = { text: 'اسحب النقاط لتعديل الشكل', subtext: 'اضغط إلغاء للتراجع' };
    e.handlers.remove.tooltip = { text: 'اضغط على الشكل لحذفه' };
  }
  setupDrawLocale();

  function create(el, { center, zoom, basemapKey = 'basemap' } = {}) {
    const s = App.meta.settings;
    const map = L.map(el, { zoomControl: true, preferCanvas: true, attributionControl: true })
      .setView(center || [s.map_center_lat, s.map_center_lon], zoom || s.map_zoom);
    el.setAttribute('dir', 'ltr');
    const renderer = L.canvas({ padding: 0.3 });
    const offline = L.layerGroup();
    const egyptLayer = L.geoJSON(null, { style, renderer });
    const cairoLayer = L.geoJSON(null, { style, renderer });
    offline.addLayer(egyptLayer);
    loadBasemap().then(([eg, ca]) => { egyptLayer.addData(eg); cairoLayer.addData(ca); syncZoom(); });
    const syncZoom = () => {
      if (!map.hasLayer(offline)) return;
      if (map.getZoom() >= 10) { if (!offline.hasLayer(cairoLayer)) offline.addLayer(cairoLayer); } else offline.removeLayer(cairoLayer);
    };
    map.on('zoomend', syncZoom);
    const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap' });
    const bases = { 'خريطة محلية (بدون إنترنت)': offline, 'خريطة OSM (تحتاج إنترنت)': osm };
    const chosen = localStorage.getItem(basemapKey) === 'osm' ? osm : offline;
    chosen.addTo(map);
    map.on('baselayerchange', (e) => { localStorage.setItem(basemapKey, e.layer === osm ? 'osm' : 'offline'); syncZoom(); });
    osm.on('tileerror', () => { if (!map._osmWarned) { map._osmWarned = true; toast('لا يوجد اتصال بالإنترنت — استخدم الخريطة المحلية', 'warn'); } });

    const network = L.featureGroup();
    const tickets = L.featureGroup();
    const history = L.featureGroup();
    network.addTo(map); tickets.addTo(map);
    const control = L.control.layers(bases, { 'المسارات والوصلات القائمة': network, 'العمليات الجارية': tickets, 'السجل التاريخي (مغلق)': history }, { position: 'topleft', collapsed: true }).addTo(map);
    L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);
    const kit = { map, network, tickets, history, control, layersData: null };

    kit.loadLayers = async (opts = {}) => {
      const data = await api('/api/map/layers');
      kit.layersData = data;
      network.clearLayers(); tickets.clearLayers(); history.clearLayers();
      for (const f of data.network.features) {
        const p = f.properties;
        if (p.kind === 'route') {
          L.geoJSON(f, { style: { color: CABLE_COLOR(p.cable_type), weight: 4, opacity: 0.85 } })
            .bindPopup(`<b>${esc(p.code)}</b> — ${esc(p.name)}<br>الكابل: ${esc(cableName(p.cable_type))}<br>الطول: ${fmtLen(p.length_m)}<br>الجهات المشتركة: ${esc(p.parties || '—')}`)
            .bindTooltip(p.code, { sticky: true }).addTo(network);
        } else {
          const ll = [f.geometry.coordinates[1], f.geometry.coordinates[0]];
          const big = p.kind === 'exchange';
          L.circleMarker(ll, { radius: big ? 7 : 4, color: big ? '#14213d' : '#37474f', fillColor: big ? '#ffd54f' : '#fff', fillOpacity: 1, weight: 2 })
            .bindPopup(`<b>${esc(p.code)}</b><br>${esc(p.name)}<br><span class="muted">${esc(p.kind_label)}</span>`).bindTooltip(p.code).addTo(network);
        }
      }
      for (const f of data.tickets.features) {
        const p = f.properties;
        if (opts.exclude && p.id === opts.exclude) continue;
        const target = p.status === 'closed' ? history : tickets;
        const color = p.status === 'closed' ? '#78909c' : TYPE_COLOR[p.fax_type];
        const popup = `<b>${esc(p.fax_no)}</b> ${pill('t-' + p.fax_type, p.type_label)}<br>${esc(p.title)}<br>${pill('s-' + p.status, p.status_label)} ${pill('p-' + p.priority, p.priority_label)}
          ${p.cause ? `<br>السبب: ${esc(p.cause)}` : ''}${p.assigned_team ? `<br>المفرزة: ${esc(p.assigned_team)}` : ''}<br><span class="muted">${fmtDate(p.closed_at || p.received_at)}</span>
          <br><a href="#/ticket/${p.id}">فتح شاشة العمل ←</a>`;
        if (f.geometry.type === 'Point') {
          const ll = [f.geometry.coordinates[1], f.geometry.coordinates[0]];
          L.circleMarker(ll, { radius: p.status === 'closed' ? 5 : p.priority === 'critical' ? 10 : 8, color: '#fff', weight: 2, fillColor: color, fillOpacity: 0.95, className: p.overdue ? 'blink' : '' })
            .bindPopup(popup).addTo(target);
        } else {
          L.geoJSON(f, { style: { color, weight: 6, opacity: 0.8, dashArray: p.fax_type === 'project' ? '8 6' : null } }).bindPopup(popup).addTo(target);
        }
      }
      return data;
    };

    kit.addSearch = (container) => {
      const box = document.createElement('div');
      box.className = 'map-search';
      box.innerHTML = '<input placeholder="🔍 ابحث باسم المكان أو كود المسار أو رقم الفاكس…"><div class="results"></div>';
      container.appendChild(box);
      L.DomEvent.disableClickPropagation(box); L.DomEvent.disableScrollPropagation(box);
      const input = $('input', box), results = $('.results', box);
      let timer, marker;
      input.addEventListener('input', () => {
        clearTimeout(timer);
        const q = input.value.trim();
        if (!q) { results.innerHTML = ''; return; }
        timer = setTimeout(async () => {
          const items = await api('/api/search?q=' + encodeURIComponent(q), { silent: true }).catch(() => []);
          results.innerHTML = items.length ? items.map((r, i) => `<div data-i="${i}">${esc(r.label)}<small>${esc(r.kind)}</small></div>`).join('') : '<div class="muted">لا توجد نتائج</div>';
          $$('[data-i]', results).forEach((d) => d.addEventListener('click', () => {
            const r = items[+d.dataset.i];
            map.setView([r.lat, r.lon], Math.max(map.getZoom(), r.type === 'place' ? 15 : 14));
            marker && marker.remove();
            marker = L.marker([r.lat, r.lon], { opacity: 0.75 }).addTo(map).bindTooltip(r.label, { permanent: true, direction: 'top' });
            setTimeout(() => marker && marker.remove(), 15000);
            results.innerHTML = ''; input.value = r.label;
          }));
        }, 220);
      });
      return box;
    };

    kit.addLegend = (container) => {
      const lg = document.createElement('div');
      lg.className = 'map-legend';
      lg.innerHTML = `<div><span style="background:#00897b"></span>ألياف 24</div><div><span style="background:#1565c0"></span>ألياف 48</div>
        <div><span style="background:#6a1b9a"></span>ألياف 96</div><div><span style="background:#8d6e63"></span>نحاس</div>
        <div><span class="dot" style="background:#d32f2f"></span>عطل</div><div><span class="dot" style="background:#2e7d32"></span>مشروع</div>
        <div><span class="dot" style="background:#f9a825"></span>تنسيق</div><div><span class="dot" style="background:#78909c"></span>مغلق (تاريخي)</div>`;
      container.appendChild(lg);
    };

    kit.enableDraw = ({ onChange, allowLine = true, allowPoint = true } = {}) => {
      const drawn = new L.FeatureGroup().addTo(map);
      const ctl = new L.Control.Draw({
        position: 'topleft',
        draw: { polyline: allowLine ? { shapeOptions: { color: '#ff6f00', weight: 6 }, metric: true, feet: false, showLength: true } : false,
          marker: allowPoint ? {} : false, polygon: false, rectangle: false, circle: false, circlemarker: false },
        edit: { featureGroup: drawn },
      });
      map.addControl(ctl);
      const emit = () => onChange && onChange(kit.getDrawn());
      map.on(L.Draw.Event.CREATED, (e) => { drawn.clearLayers(); drawn.addLayer(e.layer); emit(); });
      map.on(L.Draw.Event.EDITED, emit);
      map.on(L.Draw.Event.DELETED, emit);
      kit.drawn = drawn;
      return drawn;
    };
    kit.setDrawn = (geometry, fit = true) => {
      if (!kit.drawn) return;
      kit.drawn.clearLayers();
      if (!geometry) return;
      let layer;
      if (geometry.type === 'Point') layer = L.marker([geometry.coordinates[1], geometry.coordinates[0]]);
      else layer = L.polyline(geometry.coordinates.map((c) => [c[1], c[0]]), { color: '#ff6f00', weight: 6 });
      kit.drawn.addLayer(layer);
      if (fit) { if (geometry.type === 'Point') map.setView(layer.getLatLng(), 15); else map.fitBounds(layer.getBounds(), { padding: [40, 40] }); }
    };
    kit.getDrawn = () => {
      const layers = kit.drawn ? kit.drawn.getLayers() : [];
      if (!layers.length) return null;
      const l = layers[0];
      if (l instanceof L.Marker) { const p = l.getLatLng(); return { geometry: { type: 'Point', coordinates: [+p.lng.toFixed(6), +p.lat.toFixed(6)] }, length: 0 }; }
      const lls = l.getLatLngs();
      return { geometry: { type: 'LineString', coordinates: lls.map((p) => [+p.lng.toFixed(6), +p.lat.toFixed(6)]) }, length: lengthOf(lls) };
    };
    kit.destroy = () => map.remove();
    setTimeout(() => map.invalidateSize(), 50);
    return kit;
  }
  function cableName(code) { const c = (App.meta.cable_types || []).find((x) => x.code === code); return c ? c.name : code || '—'; }
  return { create, lengthOf, cableName, CABLE_COLOR };
})();
