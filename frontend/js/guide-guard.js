/**
 * Guide page safety net: "Loading brand guide…" can never hang forever.
 *
 * After 15 seconds, if the page is still loading, this switches it to the
 * error state: "This is taking too long", with Try again and Start a new
 * guide buttons (both plain links in guide.html, so they work without
 * JavaScript).
 *
 * Why this is a separate, plain script and not part of guide.js: if guide.js
 * can't run at all (a file failed to download, or the browser mixed an old
 * cached file with a new one), a timer inside it would never start either.
 * This file has no imports, so nothing else can stop it from running.
 *
 * Only the first wait is limited. Once a job is running (data-state is
 * "running"), its progress shows instead, and api.js decides how long to
 * keep waiting (3 minutes).
 *
 * guide.js checks the state before it draws, so a guide that arrives after
 * the time limit doesn't replace this message.
 */
(() => {
  const LIMIT_MS = 15000; // keep in step with REQUEST_TIMEOUT_MS in api.js
  const page = document.querySelector('[data-guide]');
  if (!page) return;

  /** Puts text into the element that matches the selector, if it exists. */
  function setText(selector, text) {
    const element = page.querySelector(selector);
    if (element) element.textContent = text;
  }

  window.setTimeout(() => {
    if (page.dataset.state !== 'loading') return;

    const title = 'This is taking too long';
    page.dataset.state = 'error';
    page.removeAttribute('aria-busy');
    setText('[data-brand-name]', title);
    setText('[data-guide-error-message]', 'The guide didn’t load within 15 seconds. Check your connection and try again.');
    setText('[data-guide-status]', title); // read out by screen readers
  }, LIMIT_MS);
})();
