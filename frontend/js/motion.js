/**
 * Scroll-triggered motion, shared by every page.
 *
 * Elements opt in with an attribute:
 *   data-reveal    fades up once when it scrolls into view
 *   data-sequence  plays a one-off sequence (the CSS decides what moves)
 *
 * This file never animates anything itself. It only adds the class
 * "is-visible" the first time an element comes into view, and the CSS in
 * components.css / pages.css does the rest with opacity and transform
 * (which never move other content, so there is no layout shift).
 *
 * theme.js adds "sf-motion" to <html> before the page is drawn, and only
 * when the visitor has not asked for reduced motion. Without that class this
 * file does nothing and the CSS shows everything in its final state.
 */

const root = document.documentElement;

if (root.classList.contains('sf-motion')) {
  // Tell theme.js's safety timer that motion is up and running.
  root.classList.add('sf-motion-ready');
  watchForReveals();
}

/** Adds "is-visible" to each opted-in element once, as it scrolls into view. */
function watchForReveals() {
  const targets = document.querySelectorAll('[data-reveal], [data-sequence]');
  const show = (element) => element.classList.add('is-visible');

  // Very old browsers: just show everything.
  if (!('IntersectionObserver' in window)) {
    targets.forEach(show);
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        show(entry.target);
        observer.unobserve(entry.target); // play once only
      });
    },
    // Start when 15% of the element is on screen, ignoring the bottom 10%
    // of the window, so things animate just after they appear.
    { threshold: 0.15, rootMargin: '0px 0px -10% 0px' },
  );

  targets.forEach((target) => observer.observe(target));
}
