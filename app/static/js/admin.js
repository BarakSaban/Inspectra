/* Helpers shared by the manager pages and the profile page. */
(() => {
  'use strict';
  const { t, tm } = window.I18n;

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ----- navigation -----
  const burger = document.getElementById('navToggle');
  const nav = document.getElementById('mainNav');
  burger?.addEventListener('click', () => {
    const open = nav.classList.toggle('open');
    burger.setAttribute('aria-expanded', String(open));
  });

  document.getElementById('tabMore')?.addEventListener('click', () => burger?.click());
  document.addEventListener('click', (e) => {   // tapping outside the open menu closes it
    if (nav?.classList.contains('open') && !e.target.closest('#mainNav, #navToggle, #tabMore')) { nav.classList.remove('open'); burger?.setAttribute('aria-expanded', 'false'); }
  });

  // ----- theme (light/dark, remembered) -----
  document.getElementById('themeToggle')?.addEventListener('click', () => {
    const dark = document.documentElement.dataset.theme !== 'dark';
    if (dark) document.documentElement.dataset.theme = 'dark'; else delete document.documentElement.dataset.theme;
    try { localStorage.setItem('inspectra.theme', dark ? 'dark' : 'light'); } catch (e) { /* ignore */ }
  });

  // ----- live updates: the server says "something changed", the page re-reads its data. Polling stays as the fallback. -----
  function onLive(callback) {
    if (!('EventSource' in window)) return;
    let timer = null;
    const source = new EventSource('/api/events');
    source.addEventListener('change', () => { clearTimeout(timer); timer = setTimeout(callback, 300); });
  }

  // ----- toast -----
  let toastEl, toastTimer;
  function toast(message, kind = '') {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'toast';
      toastEl.setAttribute('role', 'status');
      document.body.appendChild(toastEl);
    }
    toastEl.className = `toast show${kind ? ` toast--${kind}` : ''}`;
    toastEl.textContent = message;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), 3400);
  }

  // ----- dialogs -----
  let lastFocus = null;
  function closeDialog() {
    document.getElementById('dialogRoot')?.remove();
    document.removeEventListener('keydown', onKey);
    lastFocus?.focus?.();
  }
  function onKey(e) {
    if (e.key === 'Escape') closeDialog();
  }
  /** Opens a modal. `html` is trusted markup built with esc(); returns the dialog element. */
  function openDialog(html, { label } = {}) {
    closeDialog();
    lastFocus = document.activeElement;
    const root = document.createElement('div');
    root.id = 'dialogRoot';
    root.className = 'overlay';
    root.innerHTML = `<div class="dialog" role="dialog" aria-modal="true" aria-label="${esc(label || '')}">${html}</div>`;
    root.addEventListener('mousedown', (e) => { if (e.target === root) closeDialog(); });
    document.body.appendChild(root);
    document.addEventListener('keydown', onKey);
    window.I18n.apply(root);
    const dlg = root.firstElementChild;
    (dlg.querySelector('input, button') || dlg).focus();
    return dlg;
  }
  function confirmDialog({ title, text, okKey = 'c.delete', danger = true }) {
    return new Promise((resolve) => {
      const dlg = openDialog(`
        <h3>${esc(title)}</h3><p>${esc(text)}</p>
        <div class="dialog__actions">
          <button type="button" class="btn btn--quiet" data-act="no">${esc(t('c.cancel'))}</button>
          <button type="button" class="btn ${danger ? 'btn--danger' : ''}" data-act="yes">${esc(t(okKey))}</button>
        </div>`, { label: title });
      dlg.addEventListener('click', (e) => {
        const act = e.target.closest('[data-act]')?.dataset.act;
        if (!act) return;
        closeDialog();
        resolve(act === 'yes');
      });
    });
  }

  /** JSON request. Resolves { ok, status, data }; never throws on HTTP errors. */
  async function api(url, { method = 'GET', body } = {}) {
    try {
      const res = await fetch(url, {
        method, credentials: 'same-origin',
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      if (res.status === 401) { location.href = '/login'; return { ok: false, status: 401, data: {} }; }
      const data = await res.json().catch(() => ({}));
      return { ok: res.ok, status: res.status, data };
    } catch (e) {
      return { ok: false, status: 0, data: { error: 'network' } };
    }
  }
  const errorText = (r) => (r.status === 0 ? t('c.net') : tm(r.data.error || r.data.message || 'Server error'));

  async function copy(text, okKey = 'c.copied') {
    try { await navigator.clipboard.writeText(text); toast(t(okKey), 'ok'); return true; }
    catch (e) { toast(text); return false; }
  }

  let qrLoading = null;
  function loadQr() {
    if (window.QRCode) return Promise.resolve();
    qrLoading = qrLoading || new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js';
      s.onload = resolve; s.onerror = () => { qrLoading = null; reject(new Error('qr')); };
      document.head.appendChild(s);
    });
    return qrLoading;
  }

  /** Invite dialog: the manager code with copy, a sign-up link that pre-fills it, and one-tap sharing. */
  function inviteDialog(code) {
    const link = `${location.origin}/signup?code=${encodeURIComponent(code)}`;
    const message = t('inv.message', { link, code });
    const canShare = typeof navigator.share === 'function';
    const dlg = openDialog(`
      <h3>${esc(t('inv.title'))}</h3>
      <p>${esc(t('inv.text'))}</p>
      <div class="pw" style="margin-bottom:6px"><span>${esc(code)}</span>
        <button type="button" class="btn btn--quiet btn--small" data-act="code">${esc(t('inv.copyCode'))}</button></div>
      <div class="pw" style="font-size:.8125rem;letter-spacing:0;font-weight:600"><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(link)}</span>
        <button type="button" class="btn btn--quiet btn--small" data-act="link">${esc(t('inv.copyLink'))}</button></div>
      <div class="qrbox"><div class="qr" id="inviteQr" aria-hidden="true"></div><p>${esc(t('inv.qr'))}</p></div>
      <div class="dialog__actions" style="justify-content:flex-start">
        ${canShare ? `<button type="button" class="btn" data-act="share"><i class="fa-solid fa-share-nodes" aria-hidden="true"></i>${esc(t('inv.share'))}</button>` : ''}
        <a class="btn ${canShare ? 'btn--quiet' : ''}" target="_blank" rel="noopener" href="https://wa.me/?text=${encodeURIComponent(message)}"><i class="fa-brands fa-whatsapp" aria-hidden="true"></i>WhatsApp</a>
        <button type="button" class="btn btn--quiet" data-act="message">${esc(t('inv.copyMessage'))}</button>
      </div>
      <div class="dialog__actions"><button type="button" class="btn btn--quiet" data-act="close">${esc(t('c.close'))}</button></div>`, { label: t('inv.title') });
    loadQr().then(() => { const box = dlg.querySelector('#inviteQr'); if (box && window.QRCode) new window.QRCode(box, { text: link, width: 148, height: 148, correctLevel: window.QRCode.CorrectLevel.M }); })
      .catch(() => dlg.querySelector('.qrbox')?.remove());   // offline or blocked: the code and link still work
    dlg.addEventListener('click', async (e) => {
      const act = e.target.closest('[data-act]')?.dataset.act;
      if (act === 'code') copy(code);
      if (act === 'link') copy(link);
      if (act === 'message') copy(message);
      if (act === 'close') closeDialog();
      if (act === 'share') { try { await navigator.share({ title: 'Inspectra', text: message }); } catch (err) { /* cancelled */ } }
    });
  }

  window.Admin = { esc, toast, openDialog, closeDialog, confirmDialog, api, errorText, copy, inviteDialog, onLive };
})();
