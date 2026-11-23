/* Commander directives: poll for incoming directives and show urgent popups on the station. */
(function () {
  let lastId = +(localStorage.getItem('cmdDirLast') || 0);
  let primed = false;

  function beep() {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      [0, 0.25, 0.5].forEach((t) => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = 'square'; o.frequency.value = 880;
        g.gain.setValueAtTime(0.08, ctx.currentTime + t);
        g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + 0.2);
        o.connect(g).connect(ctx.destination);
        o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.22);
      });
      setTimeout(() => ctx.close(), 1200);
    } catch (e) { /* audio unavailable */ }
  }

  function showDirective(d) {
    beep();
    const body = `<div class="alert-item urgent"><div class="ic">📨</div><div>
      <div class="t">توجيه مكتوب من القيادة</div>
      <div class="m" style="white-space:pre-wrap">${esc(d.message)}</div>
      <div class="m muted">${esc(d.actor)} · ${fmtDate(d.at)}</div>
      ${d.ticket_id ? `<div class="m"><a href="#/ticket/${d.ticket_id}">فتح الفاكس المرتبط ←</a> — تم تسجيل التوجيه في التتبع ووُسم الفاكس كمقروء من القيادة.</div>` : ''}
    </div></div>`;
    modal({ title: '📨 توجيه عاجل من القيادة', urgent: true, wide: true, body,
      footer: '<button class="btn primary" data-close>تم الاطلاع</button>' });
    toast('وصل توجيه جديد من شاشة القيادة', 'warn', 6000);
  }

  async function poll() {
    try {
      const items = await api('/api/command/directives?since_id=' + lastId + '&limit=100', { silent: true });
      if (!primed) {
        primed = true;
        if (!lastId && items.length) {
          // first run: only notify about the newest one to avoid a backlog of popups
          showDirective(items[items.length - 1]);
        }
      } else {
        items.forEach(showDirective);
      }
      if (items.length) {
        lastId = Math.max(lastId, ...items.map((d) => d.id));
        localStorage.setItem('cmdDirLast', lastId);
      }
    } catch (e) { /* station offline */ }
  }

  setInterval(poll, 4000);
  setTimeout(poll, 2500);
})();
