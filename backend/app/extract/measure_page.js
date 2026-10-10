/*
 * Swatchfin's measuring script. It runs inside a brand's homepage, in a
 * TinyFish Browser, and reads what the browser really draws. Python sends
 * it with Playwright's page.evaluate() (see visuals.py) and gets back plain
 * data (numbers, colour codes and some text) to analyse.
 *
 * In plain English, it:
 * 1. waits for the page's web fonts, scrolls to the top and hides cookie
 *    banners and pop-ups that cover the page (only in this private browser;
 *    nothing is clicked or accepted);
 * 2. looks at the page's elements and records, for each one that shows
 *    text, a background or a border: its kind (heading, button, link...),
 *    where it is, its size, its colours (as solid #RRGGBB, see-through
 *    colours blended onto what is behind them) and its font;
 * 3. checks a grid of points on the first screen and records which
 *    background colour is drawn at each one (photos and videos count as
 *    images), for the "share of the visible area";
 * 4. lists the web fonts the page loaded;
 * 5. copies the <head>, header, nav, footer and logo parts of the page as
 *    HTML, the same parts Fetch reads, with a number on each image and SVG
 *    so Python can find their size, visibility and colour on the page;
 * 6. copies the page's visible text and its links.
 *
 * Everything it returns is checked again in Python: a page's own scripts
 * run in the same page and could change what this script sees.
 */
async (options) => {
  const {
    structureSelectors, // the parts of the page to copy (homepage.py's STRUCTURE_SELECTORS)
    maxWalk, // how many elements to look at, at most
    maxElements, // how many to record, at most
    gridStep, // pixels between the points checked on the first screen
    maxHtmlChars, // how much HTML to copy, at most
    maxTextChars, // how much text to copy, at most
    maxLinks, // how many links to copy, at most
    fontWaitMs, // how long to wait for web fonts
  } = options;

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  await Promise.race([document.fonts.ready, sleep(fontWaitMs)]);
  window.scrollTo(0, 0);
  await sleep(100);

  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;

  /** True when an element is drawn: not display:none, not hidden, not fully see-through. */
  function isVisible(element) {
    if (typeof element.checkVisibility === 'function') {
      return element.checkVisibility({ opacityProperty: true, visibilityProperty: true });
    }
    const style = getComputedStyle(element);
    return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0;
  }

  /* ------------------------------------------------------------------------
     Colours
     ------------------------------------------------------------------------ */

  // A 1×1 canvas turns any CSS colour (rgb, hsl, oklch, color()...) into red, green, blue and alpha.
  const canvas = document.createElement('canvas');
  canvas.width = 1;
  canvas.height = 1;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  const parsed = new Map();
  const RGB = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:\s*[,/]\s*([\d.]+)(%?))?\s*\)$/;

  /** "rgba(0, 0, 0, 0.5)" -> [0, 0, 0, 0.5]; null when it is see-through or not a colour. */
  function toRgba(value) {
    if (!value || value === 'transparent' || value === 'none') return null;
    if (parsed.has(value)) return parsed.get(value);
    let colour = null;
    const match = RGB.exec(value);
    if (match) {
      let alpha = match[4] === undefined ? 1 : Number(match[4]);
      if (match[5] === '%') alpha /= 100;
      colour = [Number(match[1]), Number(match[2]), Number(match[3]), alpha];
    } else if (context) {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = '#000';
      context.fillStyle = value;
      context.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = context.getImageData(0, 0, 1, 1).data;
      colour = [r, g, b, a / 255];
    }
    if (colour && colour[3] <= 0.01) colour = null;
    parsed.set(value, colour);
    return colour;
  }

  /** A colour drawn over another: see-through colours let the one behind show through. */
  function over(top, below) {
    const a = top[3];
    return [0, 1, 2].map((i) => top[i] * a + below[i] * (1 - a)).concat(1);
  }

  /** [255, 90, 31, 1] -> "#FF5A1F". */
  function hex(colour) {
    return '#' + colour.slice(0, 3).map((n) => Math.round(n).toString(16).padStart(2, '0')).join('').toUpperCase();
  }

  const WHITE = [255, 255, 255, 1]; // what browsers paint when a page sets no background
  const backdrops = new Map();

  /**
   * The solid colour behind an element's content: its own background over
   * whatever is behind it, up to the first solid background. `image` is
   * true when a background image (a photo, a gradient) is on the way.
   */
  function backdrop(element) {
    if (!element || element.nodeType !== 1) return { colour: WHITE, image: false };
    if (backdrops.has(element)) return backdrops.get(element);
    const style = getComputedStyle(element);
    const own = fillOf(element, style, element.getBoundingClientRect());
    const image = style.backgroundImage !== 'none';
    let result;
    if (own && own[3] >= 0.99) {
      result = { colour: own, image };
    } else {
      const behind = backdrop(element.parentElement);
      result = { colour: own ? over(own, behind.colour) : behind.colour, image: image || behind.image };
    }
    backdrops.set(element, result);
    return result;
  }

  /* ------------------------------------------------------------------------
     1. Pop-ups and cookie banners
     ------------------------------------------------------------------------ */

  const POPUP = '[role="dialog"], [role="alertdialog"], [aria-modal="true"], dialog[open], #onetrust-consent-sdk, #CybotCookiebotDialog, #usercentrics-root';
  const CONSENT_WORDS = /cookie|consent|privacy|newsletter|sign up for|subscribe/i;
  let overlaysHidden = 0;

  function hide(element) {
    element.style.setProperty('display', 'none', 'important');
    overlaysHidden += 1;
  }

  for (const element of document.querySelectorAll(POPUP)) {
    if (isVisible(element)) hide(element);
  }
  // A layer fixed above the page that covers much of the screen (a pop-up and its dimmed
  // backdrop), or a pinned bar about cookies. The site's own header, pinned at the top, stays.
  for (const element of document.body.querySelectorAll('*')) {
    const style = getComputedStyle(element);
    if (style.position !== 'fixed' && style.position !== 'sticky') continue;
    const rect = element.getBoundingClientRect();
    const covers = (Math.max(0, Math.min(rect.right, viewportWidth) - Math.max(rect.left, 0)) *
      Math.max(0, Math.min(rect.bottom, viewportHeight) - Math.max(rect.top, 0))) / (viewportWidth * viewportHeight);
    const header = rect.top <= 4 && rect.height < viewportHeight * 0.25;
    const layer = style.position === 'fixed' && Number(style.zIndex) >= 1;
    if (header || covers === 0) continue;
    if ((layer && covers > 0.3) || (covers > 0.03 && CONSENT_WORDS.test(element.innerText || ''))) hide(element);
  }

  /* ------------------------------------------------------------------------
     2. Elements
     ------------------------------------------------------------------------ */

  const SKIP = new Set(['script', 'style', 'noscript', 'template', 'svg', 'iframe', 'head', 'link', 'meta', 'br', 'wbr']);
  const NAMED = new Set(['body', 'header', 'nav', 'footer', 'main', 'h1', 'h2', 'h3', 'p', 'a', 'button', 'input', 'select', 'textarea', 'hr']);
  const CODE = 'code, pre, kbd, samp';
  const buttons = new Set();

  /** The words written directly inside an element (not inside its children), tidied. */
  function ownText(element) {
    let text = '';
    for (const node of element.childNodes) {
      if (node.nodeType === 3) text += node.nodeValue;
    }
    return text.replace(/\s+/g, ' ').trim();
  }

  /** Which part of the page an element is in. */
  function regionOf(element) {
    if (element.closest('footer, [role="contentinfo"]')) return 'footer';
    if (element.closest('header, [role="banner"]')) return 'header';
    if (element.closest('nav')) return 'nav';
    return 'main';
  }

  /** True for buttons, and for links drawn as buttons: filled, or outlined with room inside, at button size. */
  function looksLikeButton(element, tag, style, rect, filled, outlined) {
    const role = element.getAttribute('role');
    const type = (element.getAttribute('type') || '').toLowerCase();
    const buttonSize = rect.width >= 32 && rect.height >= 24 && rect.height <= 120;
    if (tag === 'button' || role === 'button' || (tag === 'input' && ['submit', 'button'].includes(type))) {
      return buttonSize;
    }
    if (tag !== 'a' || !buttonSize) return false;
    const padded = parseFloat(style.paddingLeft) >= 8 && parseFloat(style.paddingTop) >= 4;
    return filled || (outlined && padded);
  }

  /**
   * A button's fill. Some sites paint it on a ::before or ::after layer
   * (Duolingo's green "Get started" is one), so those are checked too, but
   * only a layer that covers the whole element (not a link's underline).
   */
  function fillOf(element, style, rect) {
    const own = toRgba(style.backgroundColor);
    if (own && own[3] >= 0.05) return own;
    if (!element.matches('a, button, [role="button"], input')) return null;
    for (const layer of ['::before', '::after']) {
      const pseudo = getComputedStyle(element, layer);
      if (pseudo.content === 'none' || pseudo.display === 'none' || Number(pseudo.opacity) < 0.5) continue;
      const covers = parseFloat(pseudo.width) >= rect.width * 0.8 && parseFloat(pseudo.height) >= rect.height * 0.8;
      const fill = toRgba(pseudo.backgroundColor);
      if (covers && fill && fill[3] >= 0.5) return fill;
    }
    return null;
  }

  function borderOf(style) {
    const sides = ['Top', 'Right', 'Bottom', 'Left'].filter(
      (side) => parseFloat(style[`border${side}Width`]) >= 1 && !['none', 'hidden'].includes(style[`border${side}Style`]),
    );
    if (sides.length === 0) return null;
    const colour = toRgba(style[`border${sides[0]}Color`]);
    return colour && colour[3] >= 0.1 ? { colour, allSides: sides.length === 4 } : null;
  }

  const elements = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
    acceptNode: (node) => (SKIP.has(node.tagName.toLowerCase()) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  const pageWidth = document.documentElement.scrollWidth;
  let walked = 0;
  for (let element = document.body; element && walked < maxWalk && elements.length < maxElements; element = walker.nextNode()) {
    walked += 1;
    const tag = element.tagName.toLowerCase();
    const rect = element.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) continue;
    // Off the page (a "skip to content" link waiting above it, a closed side menu).
    if (rect.bottom + window.scrollY <= 0 || rect.right + window.scrollX <= 0 || rect.left + window.scrollX >= pageWidth) continue;
    if (!isVisible(element)) continue;

    const style = getComputedStyle(element);
    const text = ownText(element);
    const ownBackground = fillOf(element, style, rect);
    const filled = Boolean(ownBackground);
    const border = borderOf(style);
    const isButton = looksLikeButton(element, tag, style, rect, filled, Boolean(border && border.allSides));
    if (isButton) buttons.add(element);
    if (!text && !filled && !border && !NAMED.has(tag) && !isButton) continue;

    const owner = element.closest('a, button, [role="button"], input');
    const heading = element.closest('h1, h2, h3');
    let kind = 'box';
    if (isButton) kind = 'button';
    else if (owner && buttons.has(owner)) kind = 'button-text';
    else if (['input', 'select', 'textarea'].includes(tag)) kind = 'input';
    else if (element.closest(CODE)) kind = 'code';
    else if (heading) kind = 'heading';
    else if (owner && owner.tagName === 'A') kind = 'link';
    else if (text) kind = 'text';

    const behind = backdrop(element.parentElement).colour;
    const here = backdrop(element);
    const colour = toRgba(style.color);
    elements.push({
      tag,
      kind,
      heading: heading ? Number(heading.tagName[1]) : 0,
      region: tag === 'body' ? 'page' : regionOf(element),
      x: Math.round(rect.left + window.scrollX),
      y: Math.round(rect.top + window.scrollY),
      w: Math.round(rect.width),
      h: Math.round(rect.height),
      text: Math.min(text.length, 2000),
      color: text && colour ? hex(over(colour, here.colour)) : null,
      // What the text sits on: a solid colour, or a photo or gradient (on_image).
      back: text ? hex(here.colour) : null,
      on_image: Boolean(text && here.image),
      bg: filled ? hex(over(ownBackground, behind)) : null,
      bg_image: style.backgroundImage !== 'none',
      border: border ? hex(over(border.colour, behind)) : null,
      font: text ? style.fontFamily.slice(0, 300) : null,
      weight: Number(style.fontWeight) || 400,
      size: parseFloat(style.fontSize) || 0,
    });
  }

  /* ------------------------------------------------------------------------
     3. The first screen, point by point
     ------------------------------------------------------------------------ */

  const MEDIA = new Set(['img', 'video', 'canvas', 'picture', 'iframe', 'object', 'embed']);
  const counts = {};
  let images = 0;
  let total = 0;
  for (let y = gridStep / 2; y < viewportHeight; y += gridStep) {
    for (let x = gridStep / 2; x < viewportWidth; x += gridStep) {
      const hit = document.elementFromPoint(x, y);
      if (!hit) continue;
      total += 1;
      const tag = hit.tagName.toLowerCase();
      if (MEDIA.has(tag) || hit.closest('svg')) {
        images += 1;
        continue;
      }
      const behind = backdrop(hit);
      if (behind.image) {
        images += 1;
        continue;
      }
      const code = hex(behind.colour);
      counts[code] = (counts[code] || 0) + 1;
    }
  }

  /* ------------------------------------------------------------------------
     4. Web fonts
     ------------------------------------------------------------------------ */

  const fonts = [];
  const seenFonts = new Set();
  for (const face of document.fonts) {
    if (face.status !== 'loaded') continue;
    const family = face.family.replace(/^["']|["']$/g, '').slice(0, 100);
    const key = `${family}|${face.weight}|${face.style}`;
    if (seenFonts.has(key) || fonts.length >= 200) continue;
    seenFonts.add(key);
    fonts.push({ family, weight: String(face.weight).slice(0, 20), style: String(face.style).slice(0, 20) });
  }

  /* ------------------------------------------------------------------------
     5. The head, header, nav, footer and logo parts, with numbered images
     ------------------------------------------------------------------------ */

  const parts = [];
  for (const selector of structureSelectors) {
    let matches = [];
    try {
      matches = document.querySelectorAll(selector);
    } catch {
      continue;
    }
    for (const node of matches) {
      if (!parts.some((part) => part === node || part.contains(node))) parts.push(node);
    }
  }

  const logos = [];
  for (const part of parts) {
    if (part === document.head) continue;
    const found = part.matches('img, svg') ? [part] : [...part.querySelectorAll('img, svg')];
    for (const image of found) {
      if (logos.length >= 200) break;
      if (image.tagName.toLowerCase() === 'svg' && image.parentElement && image.parentElement.closest('svg')) continue;
      const id = String(logos.length + 1);
      image.setAttribute('data-sf-id', id);
      const rect = image.getBoundingClientRect();
      const colour = toRgba(getComputedStyle(image).color);
      logos.push({
        id,
        x: Math.round(rect.left + window.scrollX),
        y: Math.round(rect.top + window.scrollY),
        w: Math.round(rect.width),
        h: Math.round(rect.height),
        visible: rect.width >= 1 && rect.height >= 1 && isVisible(image),
        color: colour ? hex(over(colour, backdrop(image).colour)) : null,
        src: (image.getAttribute('src') || '').slice(0, 2000),
        current_src: (image.currentSrc || '').slice(0, 2000),
      });
    }
  }

  let structure = '';
  for (const part of parts) {
    const copy = part.cloneNode(true);
    // Scripts and styles out, as in Fetch's copy; an SVG keeps its own <style> (it may colour the logo).
    for (const unwanted of copy.querySelectorAll('script, noscript, template, iframe, style')) {
      if (unwanted.tagName.toLowerCase() !== 'style' || !unwanted.closest('svg')) unwanted.remove();
    }
    const html = copy.outerHTML;
    if (structure.length + html.length > maxHtmlChars) continue;
    structure += html + '\n';
  }

  /* ------------------------------------------------------------------------
     6. Text and links
     ------------------------------------------------------------------------ */

  const links = [];
  const seenLinks = new Set();
  for (const link of document.querySelectorAll('a[href]')) {
    const href = link.href;
    if (links.length >= maxLinks) break;
    if (!/^https?:/i.test(href) || seenLinks.has(href)) continue;
    seenLinks.add(href);
    links.push(href.slice(0, 2000));
  }

  const rootStyle = getComputedStyle(document.documentElement);
  const bodyStyle = getComputedStyle(document.body);

  return {
    url: location.href,
    title: document.title.slice(0, 300),
    lang: (document.documentElement.lang || '').slice(0, 20),
    viewport: { width: viewportWidth, height: viewportHeight },
    page_height: document.documentElement.scrollHeight,
    default_background: !toRgba(rootStyle.backgroundColor) && !toRgba(bodyStyle.backgroundColor),
    page_background: hex(backdrop(document.body).colour),
    overlays_hidden: overlaysHidden,
    elements,
    samples: { colors: counts, images, total },
    fonts,
    structure,
    logos,
    text: (document.body.innerText || '').slice(0, maxTextChars),
    links,
  };
}
