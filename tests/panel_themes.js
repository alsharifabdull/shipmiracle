// Reads the real VS Code default theme JSON (read-only, only when VS Code is installed) and turns it into the variable table the panel reads, over the panel test's own
// built-in-default table. Used by tests/panel_v3_a11y_test.js: contrast on the installed themes (Dark Modern, Light Modern, 2026 Dark/Light, High Contrast) and a report of every
// difference between the test table (Dark+ / Light+ / High Contrast) and the installed theme files. Not a test.
const fs = require('fs'), path = require('path');
const DIR = '/Applications/Visual Studio Code.app/Contents/Resources/app/extensions/theme-defaults/themes/';
const KEYS = { '--vscode-foreground': 'foreground', '--vscode-descriptionForeground': 'descriptionForeground', '--vscode-panel-border': 'panel.border', '--vscode-editorWidget-background': 'editorWidget.background',
  '--vscode-editorWarning-foreground': 'editorWarning.foreground', '--vscode-textLink-foreground': 'textLink.foreground', '--vscode-testing-iconPassed': 'testing.iconPassed', '--vscode-errorForeground': 'errorForeground',
  '--vscode-sideBar-background': 'sideBar.background', '--vscode-button-foreground': 'button.foreground', '--vscode-input-background': 'input.background', '--vscode-contrastBorder': 'contrastBorder' };
function available() { try { return fs.statSync(DIR).isDirectory(); } catch (e) { return false; } }
function jsonc(text) {                                              // comments (whole-line and block) and trailing commas are the only extras the theme files use
  const t = text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').replace(/,(\s*[}\]])/g, '$1');
  return JSON.parse(t);
}
function colorsOf(name, seen = []) {                                // the colours of a theme file with its `include` chain resolved (the including file wins)
  if (seen.includes(name)) return {};
  const j = jsonc(fs.readFileSync(path.join(DIR, name), 'utf8'));
  return { ...(j.include ? colorsOf(path.basename(j.include), [...seen, name]) : {}), ...(j.colors || {}) };
}
const norm = v => (typeof v === 'string' ? v.toLowerCase() : v);
// -> { vars, from }: the panel variables for a theme file over `base` (the table values stand in for the workbench's built-in defaults); `from[key]` = 'theme' | 'default'
function resolve(file, base) {
  const c = colorsOf(file), vars = { ...base }, from = {};
  for (const [v, k] of Object.entries(KEYS)) { if (c[k]) { vars[v] = norm(c[k]); from[v] = 'theme'; } else from[v] = 'default'; }
  return { vars, from };
}
// every panel variable of `table` against the theme file: [{ key, table, theme, same }] (theme null = the file does not set it: the workbench default applies)
function compare(file, table) {
  const c = colorsOf(file);
  return Object.entries(KEYS).filter(([v]) => v in table).map(([v, k]) => ({ key: v, table: norm(table[v]), theme: c[k] ? norm(c[k]) : null, same: c[k] ? norm(c[k]) === norm(table[v]) : null }));
}
module.exports = { DIR, KEYS, available, colorsOf, resolve, compare };
