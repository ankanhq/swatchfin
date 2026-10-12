/*
 * Swatchfin's logo check. It runs in a blank tab of the guide's TinyFish
 * Browser (no website's rules apply there) and draws each cleaned copy of
 * an inline SVG logo, exactly as Swatchfin will serve it, to see whether it
 * really shows a logo. Python sends it with Playwright's page.evaluate()
 * (see visuals.py) and decides from the numbers it returns.
 *
 * In plain English, for each copy it:
 * 1. loads the SVG as an image, the way the guide page will show it;
 * 2. draws it on a hidden canvas, its longer side `size` pixels;
 * 3. counts the solid pixels ("ink"), how much of their bounding box they
 *    fill, how many of them share one colour, and the see-through holes
 *    inside that box (the inside of an "o", or letters cut out of a badge).
 *
 * A blank copy has almost no ink. A white square (Notion's logo without the
 * colours the page's CSS gives it) is one colour that fills its whole box,
 * with no holes. A real logo has letters, holes or several colours.
 */
async ({ svgs, size }) => {
  /** Loads an SVG as an image; rejects if it can't be shown. */
  function load(markup) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      const url = URL.createObjectURL(new Blob([markup], { type: 'image/svg+xml' }));
      const timer = setTimeout(() => reject(new Error('timed out')), 3000);
      image.onload = () => {
        clearTimeout(timer);
        resolve({ image, url });
      };
      image.onerror = () => {
        clearTimeout(timer);
        URL.revokeObjectURL(url);
        reject(new Error('not an image'));
      };
      image.src = url;
    });
  }

  /** The numbers for one copy (see the top of this file). */
  async function inspect(markup) {
    const { image, url } = await load(markup);
    const ratio = image.naturalWidth && image.naturalHeight ? image.naturalWidth / image.naturalHeight : 1;
    const width = Math.max(1, Math.round(ratio >= 1 ? size : size * ratio));
    const height = Math.max(1, Math.round(ratio >= 1 ? size / ratio : size));
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    context.drawImage(image, 0, 0, width, height);
    URL.revokeObjectURL(url);
    const data = context.getImageData(0, 0, width, height).data;

    // Ink: pixels at least half solid. Their bounding box, and their colours in 512 groups.
    const solid = new Uint8Array(width * height);
    const colours = new Map();
    let ink = 0;
    let left = width;
    let top = height;
    let right = -1;
    let bottom = -1;
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const i = (y * width + x) * 4;
        if (data[i + 3] < 128) continue;
        solid[y * width + x] = 1;
        ink += 1;
        left = Math.min(left, x);
        right = Math.max(right, x);
        top = Math.min(top, y);
        bottom = Math.max(bottom, y);
        const group = ((data[i] >> 5) << 6) | ((data[i + 1] >> 5) << 3) | (data[i + 2] >> 5);
        colours.set(group, (colours.get(group) || 0) + 1);
      }
    }
    if (ink === 0) return { loaded: true, width, height, ink: 0, fill: 0, main_colour: 0, holes: 0 };

    // Holes: see-through pixels inside the box that can't be reached from its edge.
    const boxWidth = right - left + 1;
    const boxHeight = bottom - top + 1;
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
    const box = boxWidth * boxHeight;
    const round = (n) => Math.round(n * 1000) / 1000;
    return {
      loaded: true,
      width,
      height,
      ink: round(ink / (width * height)),
      fill: round(ink / box),
      main_colour: round(Math.max(...colours.values()) / ink),
      holes: round((box - ink - outside) / box),
    };
  }

  const results = [];
  for (const markup of svgs) {
    try {
      results.push(await inspect(markup));
    } catch {
      results.push({ loaded: false });
    }
  }
  return results;
}
