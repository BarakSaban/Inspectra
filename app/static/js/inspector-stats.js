/* Inspector stats page: one period at a time (day, week, month, year), with the previous one for comparison. */
(() => {
  'use strict';
  const { t, tm } = window.I18n;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const PERIODS = ['today', 'week', 'month', 'year'];
  const GOALS = [5, 10, 15, 20];
  const lang = () => window.I18n.lang;
  const num = (v) => Number(v ?? 0).toLocaleString(lang());

  let period = 'week', offset = 0, data = null, picked = null;
  try { const p = sessionStorage.getItem('inspectra.statsPeriod'); if (PERIODS.includes(p)) period = p; } catch (e) { /* ignore */ }

  // Same comfort options as the field app.
  let settings = {};
  try { settings = JSON.parse(localStorage.getItem('inspectra.settings') || '{}'); } catch (e) { /* ignore */ }
  const goal = GOALS.includes(settings.goal) ? settings.goal : 10;
  if (settings.size) document.documentElement.dataset.size = settings.size;
  if (settings.contrast) document.body.classList.add('hc');

  function toast(message) {
    const el = Object.assign(document.createElement('div'), { className: 'toast', textContent: message });
    $('toasts').appendChild(el);
    setTimeout(() => el.remove(), 5000);
  }

  async function load() {
    $('heroNum').classList.add('is-loading');
    let res;
    try { res = await fetch(`/api/me/stats?period=${period}&offset=${offset}`); } catch (e) { toast(t('s.offline')); return; }
    if (res.status === 401) { location.href = '/login'; return; }
    if (!res.ok) { toast(t('s.loadFail')); return; }
    data = await res.json();
    picked = null;
    render();
  }

  function rangeLabel() {
    const r = data.range, f = (d, o) => new Intl.DateTimeFormat(lang(), o).format(new Date(`${d}T12:00:00`));
    if (period === 'today') return offset === 0 ? t('s.today') : offset === 1 ? t('s.yesterday') : f(r.start, { weekday: 'long', day: 'numeric', month: 'long' });
    if (period === 'week') return `${f(r.start, { day: 'numeric', month: 'numeric' })} – ${f(r.end, { day: 'numeric', month: 'numeric' })}`;
    if (period === 'month') return f(r.start, { month: 'long', year: 'numeric' });
    return f(r.start, { year: 'numeric' });
  }

  function barLabel(key, index) {
    if (data.range.kind === 'hour') return index % 6 === 0 ? String(key).padStart(2, '0') : '';
    if (data.range.kind === 'month') return new Intl.DateTimeFormat(lang(), { month: 'short' }).format(new Date(`${key}-15T12:00:00`));
    const d = new Date(`${key}T12:00:00`);
    if (period === 'week') return new Intl.DateTimeFormat(lang(), { weekday: 'short' }).format(d);
    return d.getDate() === 1 || d.getDate() % 5 === 0 ? String(d.getDate()) : '';
  }
  function barName(key) {
    if (data.range.kind === 'hour') return `${String(key).padStart(2, '0')}:00`;
    if (data.range.kind === 'month') return new Intl.DateTimeFormat(lang(), { month: 'long' }).format(new Date(`${key}-15T12:00:00`));
    return new Intl.DateTimeFormat(lang(), { weekday: 'long', day: 'numeric', month: 'numeric' }).format(new Date(`${key}T12:00:00`));
  }

  function render() {
    if (!data) return;
    const tot = data.totals;
    $('heroNum').classList.remove('is-loading');
    $('heroNum').textContent = num(tot.fines);
    $('rangeLabel').textContent = rangeLabel();
    $('next').disabled = offset === 0;
    $('prev').disabled = offset >= 60;
    $('periods').innerHTML = PERIODS.map((p) => `<button type="button" role="tab" aria-selected="${p === period}" aria-checked="${p === period}" data-p="${p}">${esc(t(`s.p.${p}`))}</button>`).join('');

    const delta = $('heroDelta');
    if (data.change_percent == null) { delta.className = 'hero__delta'; delta.textContent = data.previous.fines ? '' : t('s.noPrev'); }
    else {
      const up = data.change_percent >= 0;
      delta.className = `hero__delta ${up ? 'is-up' : 'is-down'}`;
      delta.innerHTML = `<span dir="ltr">${up ? '▲' : '▼'} ${Math.abs(data.change_percent)}%</span> ${esc(t('s.vsPrev', { n: num(data.previous.fines) }))}`;
    }

    // The daily goal is shown for a day and (times seven) for a week.
    const target = period === 'today' ? goal : period === 'week' ? goal * 7 : 0;
    $('goal').hidden = !target;
    if (target) {
      $('goalRing').style.setProperty('--p', Math.min(100, Math.round((tot.fines / target) * 100)));
      $('goalNum').textContent = num(tot.fines);
      $('goalText').textContent = tot.fines >= target ? t('s.goalDone', { goal: target }) : t('s.goalLeft', { n: target - tot.fines, goal: target });
    }

    const max = Math.max(1, ...data.series.map((b) => b.fines));
    $('bars').className = `bars bars--${data.range.kind}${period === 'month' ? ' bars--dense' : ''}`;
    $('bars').innerHTML = data.series.map((b, i) => `<button type="button" class="col${b.fines === max && b.fines ? ' is-best' : ''}" data-i="${i}" aria-label="${esc(`${barName(b.key)}: ${t('s.fines.n', { n: b.fines })}`)}"><i style="height:${Math.max(3, Math.round((b.fines / max) * 100))}%"></i><span>${esc(barLabel(b.key, i))}</span></button>`).join('');
    $('bars').setAttribute('aria-label', t('s.chart'));
    $('barTip').textContent = tot.fines ? t('s.tapBar') : t('s.empty');

    const hours = (h) => t('s.hours', { n: num(h) });
    const items = [
      ['rides', 'fa-route', num(tot.rides)],
      ['perRide', 'fa-divide', tot.fines_per_ride == null ? '—' : num(tot.fines_per_ride)],
      ['shift', 'fa-clock', hours(tot.shift_hours)],
      ['perHour', 'fa-gauge-high', tot.fines_per_hour == null ? '—' : num(tot.fines_per_hour)],
      ['breaks', 'fa-mug-hot', hours(tot.break_hours)],
      ['bestHour', 'fa-sun', data.best.hour == null ? '—' : `${String(data.best.hour).padStart(2, '0')}:00`],
      ['streak', 'fa-fire', num(data.streak_days)],
    ];
    $('quality').innerHTML = items.map(([k, icon, v]) => `<div><dt><i class="fa-solid ${icon}" aria-hidden="true"></i> ${esc(t(`s.q.${k}`))}</dt><dd>${esc(v)}</dd></div>`).join('');

    const when = new Intl.DateTimeFormat(lang(), { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' });
    $('rides').innerHTML = data.rides.length ? data.rides.map((r) => `<li>
        <span class="route-badge">${esc(r.route_num || '·')}</span>
        <span class="ridelist__main"><span>${r.destination ? `<bdi>${esc(r.destination)}</bdi>` : esc(t('s.line', { line: r.route_num || '?' }))}</span>
          <small>${r.stop_name ? `<bdi>${esc(r.stop_name)}</bdi> · ` : ''}${esc(r.finished_at ? when.format(new Date(r.finished_at)) : '')}</small></span>
        <span class="ridelist__fines">${esc(t('s.fines.n', { n: r.fines }))}</span></li>`).join('')
      : `<li class="ridelist__empty">${esc(t('s.noRides'))}</li>`;
  }

  $('periods').addEventListener('click', (e) => {
    const b = e.target.closest('[data-p]');
    if (!b || b.dataset.p === period) return;
    period = b.dataset.p; offset = 0;
    try { sessionStorage.setItem('inspectra.statsPeriod', period); } catch (err) { /* ignore */ }
    load();
  });
  $('prev').addEventListener('click', () => { offset += 1; load(); });
  $('next').addEventListener('click', () => { if (offset > 0) { offset -= 1; load(); } });
  $('bars').addEventListener('click', (e) => {
    const b = e.target.closest('[data-i]');
    if (!b || !data) return;
    const bucket = data.series[Number(b.dataset.i)];
    document.querySelectorAll('.col.is-picked').forEach((x) => x.classList.remove('is-picked'));
    b.classList.add('is-picked');
    $('barTip').textContent = `${barName(bucket.key)}: ${t('s.fines.n', { n: bucket.fines })} · ${t('s.rides.n', { n: bucket.rides })}`;
  });

  // Swipe sideways to move between periods (right = back in time in LTR, mirrored in RTL).
  let touchX = null;
  document.addEventListener('touchstart', (e) => { touchX = e.touches[0].clientX; }, { passive: true });
  document.addEventListener('touchend', (e) => {
    if (touchX == null) return;
    const dx = e.changedTouches[0].clientX - touchX; touchX = null;
    if (Math.abs(dx) < 80) return;
    const back = document.documentElement.dir === 'rtl' ? dx < 0 : dx > 0;
    if (back && offset < 60) { offset += 1; load(); } else if (!back && offset > 0) { offset -= 1; load(); }
  }, { passive: true });

  document.addEventListener('langchange', render);
  load();
})();
