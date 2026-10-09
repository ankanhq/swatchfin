/**
 * Printing and "Save as PDF", shared by every page.
 *
 * print.css does most of the work. This file covers two things CSS can't:
 * 1. Scroll animations. Parts of the page that haven't scrolled into view
 *    yet are still hidden, waiting to fade in (see motion.js). Just before
 *    printing, the "sf-motion" switch on <html> is turned off, so
 *    everything prints in its final state. It is turned back on afterwards.
 * 2. Collapsed parts, such as the proof quotes under each tone trait
 *    (<details> elements). They are opened for the printout and closed
 *    again afterwards, so the page looks just as it did.
 *
 * The browser fires "beforeprint" and "afterprint" for its own Print menu,
 * Cmd/Ctrl+P and the guide's "Print or save as PDF" button alike.
 */

const root = document.documentElement;

let motionWasOn = false;
/** @type {HTMLDetailsElement[]} */
let openedForPrint = [];

window.addEventListener('beforeprint', () => {
  motionWasOn = root.classList.contains('sf-motion');
  root.classList.remove('sf-motion');

  openedForPrint = [...document.querySelectorAll('details:not([open])')];
  openedForPrint.forEach((details) => {
    details.open = true;
  });
});

window.addEventListener('afterprint', () => {
  if (motionWasOn) root.classList.add('sf-motion');

  openedForPrint.forEach((details) => {
    details.open = false;
  });
  openedForPrint = [];
});
