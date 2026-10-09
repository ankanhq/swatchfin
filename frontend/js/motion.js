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
 *
 * Pages that add content later (the guide page renders after its data
 * loads) call observeMotion(container) once the new elements are in place.
 */

const root = document.documentElement;
const motionOn = root.classList.contains('sf-motion');

/** One shared observer: adds "is-visible" once, then stops watching. */
const observer =
  motionOn && 'IntersectionObserver' in window
    ? new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target); // play once only
          });
        },
        // Start when 15% of the element is on screen, ignoring the bottom 10%
        // of the window, so things animate just after they appear.
        { threshold: 0.15, rootMargin: '0px 0px -10% 0px' },
      )
    : null;

if (motionOn) {
  // Tell theme.js's safety timer that motion is up and running.
  root.classList.add('sf-motion-ready');
  observeMotion(document);
}

/**
 * Starts watching every [data-reveal] / [data-sequence] element inside
 * `container` that has not played yet.
 * @param {ParentNode} container
 */
export function observeMotion(container) {
  if (!motionOn) return;
  const targets = container.querySelectorAll('[data-reveal]:not(.is-visible), [data-sequence]:not(.is-visible)');

  // Very old browsers: just show everything.
  if (!observer) {
    targets.forEach((target) => target.classList.add('is-visible'));
    return;
  }
  targets.forEach((target) => observer.observe(target));
}
