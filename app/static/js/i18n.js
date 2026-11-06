/* Inspectra i18n: Hebrew (default), English, Arabic, Russian, with RTL handling.
 *
 * Strings live in static/js/i18n-strings.js as rows [key, he, en, ar, ru].
 * Markup:   data-i18n="key"                 -> textContent
 *           data-i18n-html="key"            -> innerHTML (the string may contain <b>; interpolated values must be escaped by the caller)
 *           data-i18n-attr="placeholder:key; aria-label:key2"
 * Script:   I18n.t('key', { name: 'Dana' }), I18n.setLang('ar'), I18n.apply(rootElement), event "langchange" on document.
 */
(() => {
  'use strict';

  const LANGS = [
    { code: 'he', name: 'עברית', dir: 'rtl' },   // Hebrew is always first
    { code: 'en', name: 'English', dir: 'ltr' },
    { code: 'ar', name: 'العربية', dir: 'rtl' },
    { code: 'ru', name: 'Русский', dir: 'ltr' },
  ];
  const CODES = LANGS.map((l) => l.code);
  const DEFAULT = 'he';

  const dict = Object.fromEntries(CODES.map((c) => [c, {}]));
  (window.I18N_ROWS || []).forEach(([key, ...values]) => CODES.forEach((c, i) => { dict[c][key] = values[i]; }));

  function readCookie() {
    const m = document.cookie.match(/(?:^|;\s*)lang=([a-z]{2})/);
    return m ? m[1] : null;
  }
  function stored() {
    let v = null;
    try { v = localStorage.getItem('lang'); } catch (e) { /* storage blocked */ }
    v = v || readCookie();
    return CODES.includes(v) ? v : DEFAULT;
  }

  let current = stored();
  const meta = (code) => LANGS.find((l) => l.code === code);

  function t(key, vars) {
    let s = dict[current][key] ?? dict.en[key] ?? key;
    if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
    return s;
  }

  /** Translate a server message (kept in English by the API) via its srv.<message> row; unknown messages pass through. */
  function tm(message) {
    return dict[current]['srv.' + message] ?? message;
  }

  function setAttrs(el) {
    el.getAttribute('data-i18n-attr').split(';').forEach((pair) => {
      const [attr, key] = pair.split(':').map((x) => x && x.trim());
      if (attr && key) el.setAttribute(attr, t(key));
    });
  }

  function apply(root = document) {
    const html = document.documentElement;
    html.lang = current;
    html.dir = meta(current).dir;
    root.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.getAttribute('data-i18n')); });
    root.querySelectorAll('[data-i18n-html]').forEach((el) => { el.innerHTML = t(el.getAttribute('data-i18n-html')); });
    root.querySelectorAll('[data-i18n-attr]').forEach(setAttrs);
    document.querySelectorAll('[data-lang-switcher]').forEach(renderSwitcher);
  }

  function setLang(code) {
    if (!CODES.includes(code) || code === current) return;
    current = code;
    try { localStorage.setItem('lang', code); } catch (e) { /* storage blocked */ }
    document.cookie = `lang=${code}; path=/; max-age=31536000; SameSite=Lax`;
    apply();
    document.dispatchEvent(new CustomEvent('langchange', { detail: { lang: code } }));
  }

  // ---------- language switcher ----------
  function renderSwitcher(host) {
    host.classList.add('i18n-switcher');
    const label = t('lang.choose');
    host.innerHTML = `
      <button type="button" class="i18n-switcher__btn" aria-haspopup="menu" aria-expanded="false" aria-label="${label}" title="${label}">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/></svg>
        <span>${meta(current).name}</span>
      </button>
      <ul class="i18n-switcher__menu" role="menu" hidden>
        ${LANGS.map((l) => `<li role="none"><button type="button" role="menuitemradio" aria-checked="${l.code === current}" data-code="${l.code}" lang="${l.code}" dir="${l.dir}">${l.name}</button></li>`).join('')}
      </ul>`;
    const btn = host.querySelector('.i18n-switcher__btn');
    const menu = host.querySelector('.i18n-switcher__menu');
    const close = () => { menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = menu.hidden;
      document.querySelectorAll('.i18n-switcher__menu').forEach((m) => { m.hidden = true; });
      menu.hidden = !open;
      btn.setAttribute('aria-expanded', String(open));
      if (open) menu.querySelector('[aria-checked="true"]')?.focus();
    });
    menu.addEventListener('click', (e) => {
      const item = e.target.closest('[data-code]');
      if (item) { setLang(item.dataset.code); }
    });
    host.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { close(); btn.focus(); }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        const items = [...menu.querySelectorAll('button')];
        const i = items.indexOf(document.activeElement);
        if (!menu.hidden) { e.preventDefault(); items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus(); }
      }
    });
  }
  document.addEventListener('click', () => {
    document.querySelectorAll('.i18n-switcher__menu').forEach((m) => { m.hidden = true; });
    document.querySelectorAll('.i18n-switcher__btn').forEach((b) => b.setAttribute('aria-expanded', 'false'));
  });

  window.I18n = { t, tm, apply, setLang, LANGS, get lang() { return current; }, get dir() { return meta(current).dir; } };

  const boot = () => apply();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
