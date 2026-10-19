/*
 * Swatchfin's logo check. It runs in the guide's TinyFish Browser and draws
 * each logo, exactly as the guide will show it, to see whether it really
 * shows a logo. Python sends it with Playwright's page.evaluate() (see
 * visuals.py) and decides from the numbers it returns.
 *
 * Each item is one of:
 * - { svg }: the cleaned copy of a logo drawn with SVG code (checked in a blank tab);
 * - { src }: a picture's address. For a photo the browser took (a logo drawn
 *   with CSS) it is a data: address, checked in a blank tab. For an image file
 *   on the website, the tab first opens that file itself, so the picture is
 *   from the page's own site and the browser lets this script read it.
 * - { here: true }: the picture the tab is showing (an image file it opened).
 *   With copy: true, the answer also holds the picture as a PNG data address
 *   (`png`), so Swatchfin can keep its own copy of a tab icon: the tab
 *   opened the file itself, so the site's own rules for showing its images
 *   on other sites don't apply.
 *
 * In plain English, for each picture it:
 * 1. loads it, the way the guide page will show it;
 * 2. draws it on a hidden canvas at its own size, but with its longer side
 *    between `size` and `maxSize` pixels (a photo keeps its exact colours);
 * 3. sets aside its own background, when the picture is filled edge to edge
 *    with one colour (a logo on white in a JPG): that colour counts as paper;
 * 4. counts the solid pixels ("ink"), how much of their bounding box they
 *    fill, how many of them share one colour, and the see-through holes
 *    inside that box (the inside of an "o", or letters cut out of a badge);
 * 5. lists the logo's most used bright colours: for each family of similar
 *    colours, the exact colour most of its pixels have.
 *
 * A blank picture has almost no ink. A white square (Notion's logo without
 * the colours the page's CSS gives it) is one colour that fills its whole
 * box, with no holes. A real logo has letters, holes or several colours.
 */
async ({ items, size, maxSize, copyMax = 512 }) => {
  /** Loads a picture; rejects if it can't be shown. */
  function load(src) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      const timer = setTimeout(() => reject(new Error('timed out')), 4000);
      image.onload = () => {
        clearTimeout(timer);
        resolve(image);
      };
      image.onerror = () => {
        clearTimeout(timer);
        reject(new Error('not an image'));
      };
      image.src = src;
    });
  }

  /** How far apart two colours are, channel by channel. */
  function distance(data, i, colour) {
    return Math.max(Math.abs(data[i] - colour[0]), Math.abs(data[i + 1] - colour[1]), Math.abs(data[i + 2] - colour[2]));
  }

  /** The picture's own background: the one colour its whole edge is filled with, or null. */
  function paperOf(data, width, height) {
    const edge = [];
    for (let x = 0; x < width; x += 1) edge.push(x, (height - 1) * width + x);
    for (let y = 1; y < height - 1; y += 1) edge.push(y * width, y * width + width - 1);
    const groups = new Map();
    let solid = 0;
    for (const at of edge) {
      const i = at * 4;
      if (data[i + 3] < 250) continue;
      solid += 1;
      const group = ((data[i] >> 4) << 8) | ((data[i + 1] >> 4) << 4) | (data[i + 2] >> 4);
      groups.set(group, (groups.get(group) || []).concat(i));
    }
    if (solid < edge.length * 0.98) return null;
    const [, members] = [...groups.entries()].sort((a, b) => b[1].length - a[1].length)[0];
    if (members.length < edge.length * 0.95) return null;
    return [0, 1, 2].map((c) => members.reduce((sum, i) => sum + data[i + c], 0) / members.length);
  }

  /** "#RRGGBB" for the pixel at data[i]. */
  function hex(data, i) {
    return '#' + [0, 1, 2].map((c) => data[i + c].toString(16).padStart(2, '0')).join('').toUpperCase();
  }

  /**
   * A canvas, made the HTML way: when the tab has opened an SVG file, the page
   * is an SVG document, where document.createElement('canvas') isn't a canvas.
   */
  function newCanvas() {
    return document.createElementNS('http://www.w3.org/1999/xhtml', 'canvas');
  }

  /** The picture as a PNG data address at its own size (its longer side at most copyMax), or null. */
  function copyOf(image) {
    const naturalWidth = image.naturalWidth || 0;
    const naturalHeight = image.naturalHeight || 0;
    if (!naturalWidth || !naturalHeight) return null;
    const scale = Math.min(1, copyMax / Math.max(naturalWidth, naturalHeight));
    const canvas = newCanvas();
    canvas.width = Math.max(1, Math.round(naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(naturalHeight * scale));
    canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
    try {
      return canvas.toDataURL('image/png');
    } catch {
      return null; // the browser refused to share the pixels
    }
  }

  /** The numbers for one picture (see the top of this file). */
  async function inspect(item) {
    let src = item.here ? location.href : item.src;
    let blob = null;
    if (item.svg) {
      blob = URL.createObjectURL(new Blob([item.svg], { type: 'image/svg+xml' }));
      src = blob;
    }
    let image;
    try {
      image = await load(src);
    } finally {
      if (blob) setTimeout(() => URL.revokeObjectURL(blob), 0);
    }
    const ratio = image.naturalWidth && image.naturalHeight ? image.naturalWidth / image.naturalHeight : 1;
    const longest = Math.min(maxSize, Math.max(size, image.naturalWidth || 0, image.naturalHeight || 0));
    const width = Math.max(1, Math.round(ratio >= 1 ? longest : longest * ratio));
    const height = Math.max(1, Math.round(ratio >= 1 ? longest / ratio : longest));
    const canvas = newCanvas();
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    context.drawImage(image, 0, 0, width, height);
    const data = context.getImageData(0, 0, width, height).data;
    const paper = paperOf(data, width, height);

    // Ink: pixels at least half solid and not the paper. Their bounding box, and their colours.
    const solid = new Uint8Array(width * height);
    const groups = new Map();
    const families = new Map(); // bright colours: family -> (exact colour -> pixels)
    let ink = 0;
    let left = width;
    let top = height;
    let right = -1;
    let bottom = -1;
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const i = (y * width + x) * 4;
        if (data[i + 3] < 128 || (paper && distance(data, i, paper) <= 24)) continue;
        solid[y * width + x] = 1;
        ink += 1;
        left = Math.min(left, x);
        right = Math.max(right, x);
        top = Math.min(top, y);
        bottom = Math.max(bottom, y);
        const group = ((data[i] >> 5) << 6) | ((data[i + 1] >> 5) << 3) | (data[i + 2] >> 5);
        groups.set(group, (groups.get(group) || 0) + 1);
        // Solid, clearly coloured pixels (edges blend into what is around them), in families of similar colours.
        const spread = Math.max(data[i], data[i + 1], data[i + 2]) - Math.min(data[i], data[i + 1], data[i + 2]);
        if (data[i + 3] >= 250 && spread >= 60) {
          const family = ((data[i] >> 4) << 8) | ((data[i + 1] >> 4) << 4) | (data[i + 2] >> 4);
          const exact = families.get(family) || new Map();
          exact.set(hex(data, i), (exact.get(hex(data, i)) || 0) + 1);
          families.set(family, exact);
        }
      }
    }
    const base = { loaded: true, width, height, paper: Boolean(paper), png: item.copy ? copyOf(image) : null };
    if (ink === 0) return { ...base, ink: 0, fill: 0, main_colour: 0, holes: 0, colours: [] };

    // Holes: see-through pixels inside the box that can't be reached from its edge.
    const reached = new Uint8Array(width * height);
    const queue = [];
    const visit = (x, y) => {
      const at = y * width + x;
      if (x < left || x > right || y < top || y > bottom || solid[at] || reached[at]) return;
      reached[at] = 1;
      queue.push(at);
    };
    for (let x = left; x <= right; x += 1) {
      visit(x, top);
      visit(x, bottom);
    }
    for (let y = top; y <= bottom; y += 1) {
      visit(left, y);
      visit(right, y);
    }
    while (queue.length) {
      const at = queue.pop();
      const x = at % width;
      const y = (at - x) / width;
      visit(x + 1, y);
      visit(x - 1, y);
      visit(x, y + 1);
      visit(x, y - 1);
    }
    let outside = 0;
    for (let y = top; y <= bottom; y += 1) {
      for (let x = left; x <= right; x += 1) outside += reached[y * width + x];
    }
    const box = (right - left + 1) * (bottom - top + 1);
    const round = (n) => Math.round(n * 1000) / 1000;
    const colours = [...families.values()]
      .map((exact) => {
        const total = [...exact.values()].reduce((sum, count) => sum + count, 0);
        const [code] = [...exact.entries()].sort((a, b) => b[1] - a[1])[0];
        return [code, total];
      })
      .filter(([, total]) => total >= ink * 0.03)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([code]) => code);
    return {
      ...base,
      ink: round(ink / (width * height)),
      fill: round(ink / box),
      main_colour: round(Math.max(...groups.values()) / ink),
      holes: round((box - ink - outside) / box),
      colours,
    };
  }

  // The answer the website gave when this tab opened an image file (404 when it is missing).
  const opened = performance.getEntriesByType('navigation')[0];
  const status = opened && opened.responseStatus ? opened.responseStatus : 0;
  const results = [];
  for (const item of items) {
    try {
      results.push(await inspect(item));
    } catch {
      results.push({ loaded: false, status });
    }
  }
  return results;
}
