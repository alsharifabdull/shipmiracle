// Shipmiracle theme: runs in the head before the first paint, so a saved choice never flashes the wrong colours.
// The default is LIGHT. Only a saved choice ('dark') or the toggle switches the page to dark; the system setting is never read.
(function () {
  var root = document.documentElement;
  var COLORS = { light: '#F4EFE6', dark: '#17191C' };
  function paintMeta(t) {
    var cs = document.querySelector('meta[name="color-scheme"]');
    var tc = document.querySelector('meta[name="theme-color"]');
    if (cs) cs.setAttribute('content', t);
    if (tc) tc.setAttribute('content', COLORS[t]);
  }
  window.shipmTheme = {
    current: function () { return root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'; },
    apply: function (t) {
      t = t === 'dark' ? 'dark' : 'light';
      root.setAttribute('data-theme', t);
      paintMeta(t);
    }
  };
  var saved = null;
  try { saved = localStorage.getItem('shipm-theme'); } catch (e) { /* storage blocked: stay light */ }
  if (saved === 'dark') window.shipmTheme.apply('dark');
})();
