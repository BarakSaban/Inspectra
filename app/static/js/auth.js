/* Login and sign-up behaviour (the page has either #loginForm or #registerForm). */
(() => {
  'use strict';
  const { t, tm } = window.I18n;
  const $ = (id) => document.getElementById(id);

  const toastEl = $('toast'), bar = $('barFill');
  let toastTimer;
  function toast(message, kind = '') {
    toastEl.className = `toast show${kind ? ` toast--${kind}` : ''}`;
    $('toastMsg').textContent = message;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), 3200);
  }
  function progress(to, color) {
    bar.style.transition = 'width .4s var(--ease-out)';
    bar.style.background = color || '';
    bar.style.width = to;
  }

  // ----- role switch -----
  const roleInput = $('role');
  const roleButtons = document.querySelectorAll('.roles button');
  function setRole(role) {
    roleInput.value = role;
    roleButtons.forEach((b) => b.setAttribute('aria-checked', String(b.dataset.role === role)));
    $('managerCodeField')?.classList.toggle('hidden', role === 'admin');
    $('teamNameField')?.classList.toggle('hidden', role !== 'admin');
  }
  roleButtons.forEach((b) => b.addEventListener('click', () => setRole(b.dataset.role)));

  // ----- password visibility -----
  const toggle = $('togglePassword');
  toggle?.addEventListener('click', () => {
    const p = $('password');
    const show = p.type === 'password';
    p.type = show ? 'text' : 'password';
    toggle.querySelector('i').className = show ? 'fa-regular fa-eye-slash' : 'fa-regular fa-eye';
  });

  // ----- strength meter -----
  $('password')?.addEventListener('input', (e) => {
    const v = e.target.value;
    const score = (v.length > 5) + /[A-Z]/.test(v) + /[0-9]/.test(v) + /[^A-Za-z0-9]/.test(v);
    const fill = $('strengthFill');
    if (!fill) return;
    fill.style.width = `${score * 25}%`;
    fill.style.background = score < 2 ? 'var(--bad)' : score < 3 ? '#b97a00' : 'var(--live)';
    $('strengthLabel').textContent = v ? t(score < 2 ? 'a.pw.weak' : score < 3 ? 'a.pw.ok' : 'a.pw.strong') : '';
  });

  async function post(url, payload, busyKey, okKey, onOk) {
    const btn = document.querySelector('.submit');
    btn.disabled = true;
    progress('60%');
    toast(t(busyKey));
    try {
      const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.success) {
        toast(t(okKey), 'ok');
        progress('100%', 'var(--live)');
        setTimeout(() => { location.href = data.redirect || onOk; }, 650);
        return;
      }
      toast(tm(data.message || 'Server error'), 'error');
      progress('100%', 'var(--bad)');
    } catch (err) {
      toast(t('a.net'), 'error');
      progress('100%', 'var(--bad)');
    }
    setTimeout(() => progress('0%'), 700);
    btn.disabled = false;
  }

  // ----- login -----
  $('loginForm')?.addEventListener('submit', (e) => {
    e.preventDefault();
    post('/api/login', { contact: $('contact').value.trim(), password: $('password').value, role: roleInput.value }, 'a.login.progress', 'a.login.ok', '/');
  });
  $('forgotPassword')?.addEventListener('click', () => toast(t('a.login.forgotHint')));

  // ----- register -----
  $('registerForm')?.addEventListener('submit', (e) => {
    e.preventDefault();
    const password = $('password').value;
    if (password !== $('confirmPassword').value) { toast(t('a.signup.mismatch'), 'error'); return; }
    post('/api/register', {
      name: $('name').value.trim(), email: $('email').value.trim(), phone: $('phone').value.trim(),
      role: roleInput.value, manager_code: $('managerCode').value.trim(), team_name: $('teamName').value.trim(), password,
    }, 'a.signup.progress', 'a.signup.ok', '/login');
  });

  setRole('inspector');

  // An invitation link (/signup?code=ABC123) pre-fills the manager code.
  const invited = new URLSearchParams(location.search).get('code');
  if (invited && $('managerCode')) $('managerCode').value = invited.trim();
})();
