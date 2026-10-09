/**
 * Site header, shared by every page.
 *
 * 1. Scroll state: while the page is at the very top, the bar is clear.
 *    As soon as the visitor scrolls, it gets its blurred background and
 *    bottom border back (the look is defined in components.css).
 * 2. Mobile menu (below 768px): the menu button opens and closes the list
 *    of links. It closes again on Esc, on a link click, on a click outside
 *    the header, when focus leaves the header, or when the window grows to
 *    desktop width.
 */

const header = document.querySelector('[data-site-header]');

if (header) {
  watchScroll(header);
  setUpMenu(header);
}

/**
 * Adds .sf-header--top while the page is scrolled to the top.
 * @param {HTMLElement} header
 */
function watchScroll(header) {
  let atTop = null;

  const update = () => {
    const next = window.scrollY <= 4;
    // Only touch the class when the state actually changes.
    if (next !== atTop) {
      atTop = next;
      header.classList.toggle('sf-header--top', next);
    }
  };

  update();
  // "passive" tells the browser we never block scrolling, so it stays smooth.
  window.addEventListener('scroll', update, { passive: true });
}

/**
 * Connects the menu button to the link list it controls.
 * @param {HTMLElement} header
 */
function setUpMenu(header) {
  const button = header.querySelector('[data-menu-toggle]');
  const menu = button ? document.getElementById(button.getAttribute('aria-controls')) : null;
  if (!button || !menu) return;

  const desktop = window.matchMedia('(min-width: 768px)');
  const isOpen = () => button.getAttribute('aria-expanded') === 'true';

  /** @param {boolean} open */
  const setOpen = (open) => {
    button.setAttribute('aria-expanded', String(open));
    header.classList.toggle('sf-header--menu-open', open);
  };

  button.addEventListener('click', () => setOpen(!isOpen()));

  // Following a link (including "#features" on the same page) closes the menu.
  menu.addEventListener('click', (event) => {
    if (event.target instanceof Element && event.target.closest('a')) setOpen(false);
  });

  // Esc closes the menu and puts focus back on the button.
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && isOpen()) {
      setOpen(false);
      button.focus();
    }
  });

  document.addEventListener('click', (event) => {
    if (isOpen() && event.target instanceof Node && !header.contains(event.target)) setOpen(false);
  });

  header.addEventListener('focusout', (event) => {
    const next = event.relatedTarget;
    if (isOpen() && next instanceof Node && !header.contains(next)) setOpen(false);
  });

  desktop.addEventListener('change', (event) => {
    if (event.matches) setOpen(false);
  });
}
