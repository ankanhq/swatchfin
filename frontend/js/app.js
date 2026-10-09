/**
 * Landing page (index.html).
 *
 * 1. The "Company name or URL" form: checks the input, shows a clear error
 *    if something is wrong, and otherwise opens guide.html?q=... with the
 *    Generate button locked so it can't be pressed twice.
 * 2. Example chips: clicking one only fills the input. Nothing is sent.
 * 3. "Generate a guide" buttons further down scroll back to the form and
 *    put the cursor in the input.
 *
 * Without JavaScript the form still works: the browser checks that the
 * field is not empty and submits it to guide.html on its own.
 */

import { parseQuery, createIcon } from './utils.js';

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
