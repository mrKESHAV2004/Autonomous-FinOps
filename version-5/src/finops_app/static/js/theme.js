/* Light/dark theme: the saved choice, else the system setting. Loaded in
 * <head> (not deferred) so the page never flashes the wrong theme. */
(function () {
  'use strict';
  var KEY = 'finops-theme';
  var root = document.documentElement;
  var media = window.matchMedia('(prefers-color-scheme: dark)');
  function saved() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function apply(theme) {
    root.dataset.theme = theme;
    document.dispatchEvent(new Event('themechange'));
  }
  root.dataset.theme = saved() || (media.matches ? 'dark' : 'light');
  media.addEventListener('change', function (e) { if (!saved()) { apply(e.matches ? 'dark' : 'light'); } });

  document.addEventListener('DOMContentLoaded', function () {
    var button = document.querySelector('[data-theme-toggle]');
    if (!button) { return; }
    var sync = function () { button.setAttribute('aria-pressed', String(root.dataset.theme === 'dark')); };
    button.hidden = false;
    sync();
    button.addEventListener('click', function () {
      var next = root.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(KEY, next); } catch (e) { /* private mode: still switch for this page */ }
      apply(next);
      sync();
    });
  });
})();
