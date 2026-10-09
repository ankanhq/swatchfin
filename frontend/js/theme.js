/**
 * Swatchfin theme switcher (light / dark).
 *
 * Why this is a normal <script> in <head> and not an ES module:
 * modules run only after the page has been drawn, so a visitor who chose
 * dark mode would first see a flash of the light theme. This file is tiny
 * and runs before the first paint, so the right theme shows straight away.
 * Everything sits inside one function, so it adds no global variables.
 *
 * How the theme is decided:
 *   1. If the visitor clicked the toggle before, use their saved choice.
 *   2. Otherwise follow the system setting (handled by CSS alone).
 * The choice is stored in localStorage under "sf-theme".
 *
 * It also sets one more before-paint flag: the "sf-motion" class on <html>,
 * which allows the page's entrance animations (see motion.js). It is only
 * added when the visitor has not asked for reduced motion.
 */
(() => {
  const STORAGE_KEY = 'sf-theme';
  const THEME_COLORS = { light: '#fafaf7', dark: '#0b0f19' };
  const root = document.documentElement;
  const systemDark = window.matchMedia('(prefers-color-scheme: dark)');

  /**
   * Reads the saved theme. Returns null if nothing valid is saved, or if
   * storage is blocked (private mode, strict privacy settings).
   * @returns {'light' | 'dark' | null}
   */
  function readSaved() {
    try {
      const value = localStorage.getItem(STORAGE_KEY);
      return value === 'light' || value === 'dark' ? value : null;
    } catch {
      return null;
    }
  }

  /** @param {'light' | 'dark'} theme */
  function save(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // Storage blocked: the toggle still works for this page view.
    }
  }

  /**
   * The theme on screen right now: the explicit choice, or the system one.
   * @returns {'light' | 'dark'}
   */
  function activeTheme() {
    const explicit = root.getAttribute('data-theme');
    if (explicit === 'light' || explicit === 'dark') return explicit;
    return systemDark.matches ? 'dark' : 'light';
  }

  /**
   * Updates everything that depends on the theme but is not plain CSS:
   * the toggle button's pressed state and the browser UI colour.
   */
  function syncUi() {
    const theme = activeTheme();
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      button.setAttribute('aria-pressed', String(theme === 'dark'));
    });
    // An explicit choice overrides both <meta name="theme-color"> tags.
    if (root.hasAttribute('data-theme')) {
      document.querySelectorAll('meta[name="theme-color"]').forEach((meta) => {
        meta.setAttribute('content', THEME_COLORS[theme]);
      });
    }
  }

  /** Flips light <-> dark and remembers the choice. */
  function toggle() {
    const next = activeTheme() === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    save(next);
    syncUi();
  }

  // Step 1, before the page is drawn: apply the saved choice.
  const saved = readSaved();
  if (saved) root.setAttribute('data-theme', saved);

  // Motion flag. CSS hides elements that will animate in only while
  // <html> has "sf-motion", so setting it before the first paint avoids a
  // flash. motion.js answers by adding "sf-motion-ready". If it never does
  // (the file failed to load), drop the flag so nothing stays hidden.
  if (window.matchMedia('(prefers-reduced-motion: no-preference)').matches) {
    root.classList.add('sf-motion');
    window.setTimeout(() => {
      if (!root.classList.contains('sf-motion-ready')) root.classList.remove('sf-motion');
    }, 2500);
  }

  // Step 2, once the HTML has loaded: connect the toggle buttons.
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      button.addEventListener('click', toggle);
    });
    syncUi();
  });

  // If the system theme changes while the page is open, keep the
  // toggle's pressed state in sync (CSS already updates the colours).
  systemDark.addEventListener('change', syncUi);
})();
