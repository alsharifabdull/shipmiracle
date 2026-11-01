// Shipmiracle site: progressive enhancement only. The page reads and works in full without this file.
// Theme toggle, scroll reveal, panel tabs (crossfade), copy buttons, the sample approve button, the details toggle, the nav marker and the mobile menu.
(function () {
  'use strict';
  var d = document, root = d.documentElement;
  root.classList.add('js');
  var $ = function (s, c) { return (c || d).querySelector(s); };
  var $$ = function (s, c) { return Array.prototype.slice.call((c || d).querySelectorAll(s)); };

  function ready(fn) { if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', fn); else fn(); }

  ready(function () {
    /* theme: light by default, a saved choice wins (theme.js applied it before first paint); the system setting is not read */
    var themeBtn = $('.theme'), KEY = 'shipm-theme';
    var T = window.shipmTheme || { current: function () { return root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'; }, apply: function (t) { root.setAttribute('data-theme', t); } };
    function paint() { if (themeBtn) themeBtn.setAttribute('aria-label', T.current() === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'); }
    if (themeBtn) {
      themeBtn.addEventListener('click', function () {
        var next = T.current() === 'dark' ? 'light' : 'dark';
        T.apply(next);
        try { localStorage.setItem(KEY, next); } catch (e) { /* storage blocked: the choice lasts for this visit */ }
        paint();
      });
      paint();
    }

    /* scroll reveal: fade and rise once, stagger 50 ms (at most 6 steps). CSS only hides these when motion is allowed. */
    var reveal = $$('.sec-head, .step, .rail-box, .role, .pane, .mem, .tabs, .fsum, .fcard, .cmds > li, .req, .repo, .faq details, .note');
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if ('IntersectionObserver' in window && !reduce) {
      reveal.forEach(function (el) { el.setAttribute('data-r', ''); });
      var io = new IntersectionObserver(function (entries) {
        var batch = entries.filter(function (e) { return e.isIntersecting; });
        batch.sort(function (a, b) { return a.boundingClientRect.top - b.boundingClientRect.top || a.boundingClientRect.left - b.boundingClientRect.left; });
        batch.forEach(function (e, i) {
          io.unobserve(e.target);
          window.setTimeout(function () { e.target.classList.add('in'); }, Math.min(i, 5) * 50);
        });
      }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
      reveal.forEach(function (el) { io.observe(el); });
    }

    /* nav: mark the section being read */
    var map = { how: 'how', team: 'team', control: 'team', memory: 'team', panel: 'features', features: 'features', install: 'install', faq: 'install' };
    if ('IntersectionObserver' in window) {
      var spy = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (!e.isIntersecting) return;
          var key = map[e.target.id];
          $$('.nav a').forEach(function (a) {
            var on = a.getAttribute('href') === '#' + key;
            a.classList.toggle('on', on);
            if (on) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
          });
        });
      }, { rootMargin: '-45% 0px -50% 0px' });
      $$('main section[id], .hero').forEach(function (s) { if (s.classList.contains('hero') || map[s.id]) spy.observe(s); });
    }

    /* the mobile menu closes after a choice */
    $$('.m-menu a').forEach(function (a) {
      a.addEventListener('click', function () { var m = a.closest('details'); if (m) m.removeAttribute('open'); });
    });

    /* panel tabs: roving tabindex, arrows, Home and End; the panels crossfade (CSS) */
    $$('[data-tabs]').forEach(function (box) {
      var tabs = $$('[role="tab"]', box), panels = tabs.map(function (t) { return d.getElementById(t.getAttribute('aria-controls')); });
      function select(i, focus) {
        tabs.forEach(function (t, j) {
          var on = i === j;
          t.setAttribute('aria-selected', on ? 'true' : 'false');
          t.tabIndex = on ? 0 : -1;
          if (panels[j]) panels[j].classList.toggle('on', on);
        });
        if (focus) tabs[i].focus();
      }
      tabs.forEach(function (t, i) {
        t.addEventListener('click', function () { select(i, false); });
        t.addEventListener('keydown', function (e) {
          var n = tabs.length, k = e.key, to = -1;
          if (k === 'ArrowRight' || k === 'ArrowDown') to = (i + 1) % n;
          else if (k === 'ArrowLeft' || k === 'ArrowUp') to = (i - 1 + n) % n;
          else if (k === 'Home') to = 0;
          else if (k === 'End') to = n - 1;
          if (to < 0) return;
          e.preventDefault(); select(to, true);
        });
      });
      select(0, false);
      box.classList.add('ready');
    });

    /* copy buttons */
    function selectIn(btn) {
      var code = $('code', btn.parentNode), sel = window.getSelection();
      if (!code || !sel) return;
      var r = d.createRange(); r.selectNodeContents(code); sel.removeAllRanges(); sel.addRange(r);
    }
    $$('button.copy').forEach(function (btn) {
      var label = $('.copy-t', btn);
      btn.addEventListener('click', function () {
        var text = btn.getAttribute('data-copy') || '';
        var done = function (ok) {
          btn.classList.toggle('done', ok);
          if (label) label.textContent = ok ? 'Copied' : 'Press Ctrl+C';
          window.setTimeout(function () { btn.classList.remove('done'); if (label) label.textContent = 'Copy'; }, 1800);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(function () { done(true); }, function () { selectIn(btn); done(false); });
        } else { selectIn(btn); done(false); }
      });
    });

    /* sample approve button */
    var plan = d.getElementById('plan-card');
    if (plan) {
      $$('[data-act]', plan).forEach(function (b) {
        b.addEventListener('click', function () {
          var approve = b.getAttribute('data-act') === 'approve';
          plan.classList.toggle('ok', approve);
          var next = $(approve ? '[data-act="reset"]' : '[data-act="approve"]', plan);
          if (next) next.focus();
        });
      });
    }

    /* feature details */
    var tg = $('[data-toggle-detail]'), grid = d.getElementById('fgrid');
    if (tg && grid) {
      tg.addEventListener('click', function () {
        var on = tg.getAttribute('aria-pressed') !== 'true';
        tg.setAttribute('aria-pressed', on ? 'true' : 'false');
        grid.classList.toggle('full', on);
        var t = $('span', tg); if (t) t.textContent = on ? 'Hide details' : 'Show details';
      });
    }
  });
})();
