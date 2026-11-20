// Blocking head script: resolve appearance before styles or body can paint.
(() => {
  'use strict';
  const key = 'everlume.theme';
  const choices = new Set(['light', 'dark', 'system']);
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  const read = () => {
    try { const saved = localStorage.getItem(key); return choices.has(saved) ? saved : 'system'; }
    catch { return 'system'; }
  };
  let preference = read();
  const resolved = () => preference === 'system' ? (system.matches ? 'dark' : 'light') : preference;
  function apply() {
    const theme = resolved();
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.themePreference = preference;
    const color = document.querySelector('meta[name="theme-color"]');
    if (color) color.content = theme === 'dark' ? '#0F1117' : '#F8FAFC';
    const selector = document.getElementById('theme-preference');
    if (selector) {
      selector.value = preference;
      selector.title = preference === 'system' ? `Following system appearance: ${theme}` : `${theme === 'dark' ? 'Dark' : 'Light'} mode`;
    }
    const status = document.getElementById('theme-status');
    if (status) status.textContent = `${preference === 'system' ? 'System appearance: ' : 'Appearance: '}${theme}`;
    window.dispatchEvent(new CustomEvent('themechange', {detail: {preference, theme}}));
  }
  function setPreference(value) {
    if (!choices.has(value)) return;
    preference = value;
    try { localStorage.setItem(key, value); } catch { /* Appearance still works for this tab. */ }
    apply();
  }
  window.EverlumeTheme = Object.freeze({
    setPreference,
    get preference() { return preference; },
    get theme() { return resolved(); },
  });
  apply();
  const onSystemChange = () => { if (preference === 'system') apply(); };
  if (system.addEventListener) system.addEventListener('change', onSystemChange);
  else system.addListener(onSystemChange);
  // Hidden tabs may defer media events; refresh when the workspace returns.
  window.addEventListener('focus', onSystemChange);
  window.addEventListener('pageshow', onSystemChange);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) onSystemChange(); });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) { preference = read(); apply(); }
  });
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('theme-preference').addEventListener('change', event => setPreference(event.target.value));
    apply();
  }, {once: true});
})();
