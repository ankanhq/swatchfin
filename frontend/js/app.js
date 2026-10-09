/**
 * Landing page (index.html).
 *
 * 1. The "Company name or URL" form: checks the input, shows a clear error
 *    if something is wrong, and otherwise opens guide.html?q=... with the
 *    Generate button locked so it can't be pressed twice.
 * 2. Example chips: clicking one only fills the input. Nothing is sent.
 * 3. "Generate a guide" buttons further down scroll back to the form and
 *    put the cursor in the input.
 * 4. The placeholder slowly types example brands until the visitor clicks
 *    into the input (skipped for visitors who prefer reduced motion).
 *
 * Without JavaScript the form still works: the browser checks that the
 * field is not empty and submits it to guide.html on its own.
 */

import { parseQuery, createIcon } from './utils.js';

/** Examples the placeholder types out, one after another. */
const PLACEHOLDER_EXAMPLES = ['Duolingo', 'stripe.com', 'patagonia.com'];

const form = document.querySelector('[data-generate-form]');

if (form) {
  setUpGenerateForm(form);
}

/**
 * @param {HTMLFormElement} form
 */
function setUpGenerateForm(form) {
  const input = form.querySelector('[data-generate-input]');
  const submit = form.querySelector('[data-generate-submit]');
  const label = form.querySelector('[data-generate-label]');
  const errorBox = form.querySelector('[data-generate-error]');
  if (!input || !submit || !label || !errorBox) return;

  const idleLabel = label.textContent;

  // From here on our own checks and messages replace the browser's pop-ups.
  form.noValidate = true;

  /** Shows a message under the field and marks the field as invalid. */
  const showError = (message) => {
    const text = document.createElement('span');
    text.textContent = message;
    errorBox.replaceChildren(createIcon('circle-alert', { size: 16 }), text);
    input.setAttribute('aria-invalid', 'true');
  };

  const clearError = () => {
    errorBox.replaceChildren();
    input.removeAttribute('aria-invalid');
  };

  /** Busy = button disabled, spinner on, label "Generating…". */
  const setBusy = (busy) => {
    form.setAttribute('aria-busy', String(busy));
    submit.disabled = busy;
    label.textContent = busy ? 'Generating…' : idleLabel;
  };

  form.addEventListener('submit', (event) => {
    event.preventDefault();

    const result = parseQuery(input.value);
    if (!result.ok) {
      showError(result.error);
      input.focus();
      return;
    }

    clearError();
    setBusy(true);

    // Build guide.html?q=<value> next to this page and go there.
    const target = new URL(form.getAttribute('action') || 'guide.html', window.location.href);
    target.searchParams.set('q', result.value);
    window.location.assign(target.href);
  });

  // Once the visitor starts fixing the text, the old error goes away.
  input.addEventListener('input', () => {
    if (input.hasAttribute('aria-invalid')) clearError();
  });

  // Coming back with the browser's Back button can restore this page from
  // memory with the button still locked. Unlock it.
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) setBusy(false);
  });

  // Example chips fill the input. They never submit the form.
  form.querySelectorAll('[data-example]').forEach((chip) => {
    chip.addEventListener('click', () => {
      input.value = chip.getAttribute('data-example') || '';
      clearError();
      input.focus();
    });
  });

  typePlaceholderExamples(input);

  // "Generate a guide" links elsewhere on the page jump back to the form.
  // The scroll is smooth unless the visitor asked for reduced motion
  // (base.css only turns on smooth scrolling for those who didn't).
  document.querySelectorAll('[data-focus-query]').forEach((link) => {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      form.scrollIntoView({ block: 'center' });
      input.focus({ preventScroll: true });
    });
  });
}

/**
 * Makes the input's placeholder type out example brands, like someone
 * typing: "e.g. Duolingo", pause, delete, "e.g. stripe.com", and so on.
 *
 * - Runs only when motion is allowed (theme.js sets "sf-motion" on <html>).
 * - Stops for good, and puts the normal placeholder back, as soon as the
 *   visitor focuses the input.
 * - Pauses while the input is off screen or the browser tab is hidden,
 *   so it costs nothing when nobody can see it.
 * Changing a placeholder never changes the layout.
 *
 * @param {HTMLInputElement} input
 */
function typePlaceholderExamples(input) {
  if (!document.documentElement.classList.contains('sf-motion')) return;

  const PREFIX = 'e.g. ';
  const TYPE_MS = 110; // per character typed
  const DELETE_MS = 45; // per character deleted
  const HOLD_MS = 1800; // pause on a finished word
  const START_MS = 1500; // wait before the first change

  const original = input.getAttribute('placeholder') || '';
  let text = original; // what the placeholder shows now
  let index = 0;
  let target = PREFIX + PLACEHOLDER_EXAMPLES[index]; // what it is heading to
  let timer = 0;
  let onScreen = true;
  let stopped = false;

  const isPaused = () => !onScreen || document.hidden;

  /** One keystroke: delete a character, add one, or hold on a full word. */
  const tick = () => {
    timer = 0;
    if (stopped || isPaused()) return;

    let delay;
    if (text === target) {
      // Word finished: hold it, then head for the next example.
      index = (index + 1) % PLACEHOLDER_EXAMPLES.length;
      target = PREFIX + PLACEHOLDER_EXAMPLES[index];
      delay = HOLD_MS;
    } else if (target.startsWith(text)) {
      text = target.slice(0, text.length + 1);
      delay = TYPE_MS;
    } else {
      text = text.slice(0, -1);
      delay = DELETE_MS;
    }
    input.setAttribute('placeholder', text);
    timer = window.setTimeout(tick, delay);
  };

  /** Restarts the loop after a pause, if it is not already running. */
  const resume = () => {
    if (!stopped && !timer && !isPaused()) timer = window.setTimeout(tick, TYPE_MS);
  };

  const stop = () => {
    stopped = true;
    window.clearTimeout(timer);
    observer.disconnect();
    document.removeEventListener('visibilitychange', resume);
    input.setAttribute('placeholder', original);
  };

  const observer = new IntersectionObserver(([entry]) => {
    onScreen = entry.isIntersecting;
    resume();
  });
  observer.observe(input);

  document.addEventListener('visibilitychange', resume);
  input.addEventListener('focus', stop, { once: true });

  // If the visitor switches on reduced motion while the page is open, stop.
  window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', (event) => {
    if (event.matches) stop();
  });

  timer = window.setTimeout(tick, START_MS);
}
