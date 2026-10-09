/**
 * Tone of voice section: a summary, traits that open to show their proof
 * quotes, four tone scales, and do / don't lists.
 */

import { el, createIcon, emptyState, list, siteHost, sourceLink, subsection, text, verifiedBadge } from './dom.js';

/** The four scales in the schema: 0 is the left word, 100 the right. */
const SCALES = [
  { key: 'formal_casual', left: 'Formal', right: 'Casual' },
  { key: 'serious_playful', left: 'Serious', right: 'Playful' },
  { key: 'technical_simple', left: 'Technical', right: 'Simple' },
  { key: 'reserved_bold', left: 'Reserved', right: 'Bold' },
];

/**
 * @param {Record<string, any>} guide
 * @returns {HTMLElement}
 */
export function renderVoice(guide) {
  const voice = guide.voice ?? {};
  const summary = text(voice.summary);
  const traits = list(voice.traits).filter((trait) => text(trait?.name));
  const scales = SCALES.filter(({ key }) => Number.isFinite(voice.spectrum?.[key]));
  const dos = list(voice.do).map(text).filter(Boolean);
  const donts = list(voice.dont).map(text).filter(Boolean);
  const site = siteHost(guide);

  if (!summary && traits.length === 0 && scales.length === 0 && dos.length === 0 && donts.length === 0) {
    return emptyState('No tone of voice found', 'There wasn’t enough text on the fetched pages to describe how the brand writes.');
  }

  return el('div', { className: 'sf-voice' }, [
    summary ? el('p', { className: 'sf-voice__summary', text: summary }) : null,
    traits.length > 0
      ? subsection('Traits', [el('div', { className: 'sf-traits' }, traits.map((trait, i) => traitCard(trait, i === 0, site)))])
      : null,
    scales.length > 0
      ? subsection('Tone scales', [
          el('div', { className: 'sf-scales', attrs: { 'data-sequence': '' } }, scales.map((scale) => scaleRow(scale, voice.spectrum[scale.key]))),
        ])
      : null,
    dos.length > 0 || donts.length > 0
      ? subsection('Do and don’t', [
          el('div', { className: 'sf-dodont' }, [
            dos.length > 0 ? ruleList('Do', 'circle-check', 'do', dos) : null,
            donts.length > 0 ? ruleList('Don’t', 'circle-x', 'dont', donts) : null,
          ]),
        ])
      : null,
  ]);
}

/**
 * A trait as a native <details>: the name and description are always
 * visible, and opening it shows the quotes that back it up. The first
 * trait starts open, so people see that the others open too.
 * @param {Record<string, any>} trait
 * @param {boolean} open
 * @param {string} site The brand's host, for short source links.
 * @returns {HTMLElement}
 */
function traitCard(trait, open, site) {
  const evidence = list(trait.evidence).filter((item) => text(item?.quote));
  const description = text(trait.description);

  const details = el('details', { className: 'sf-trait' }, [
    el('summary', { className: 'sf-trait__summary' }, [
      el('span', { className: 'sf-trait__text' }, [
        el('span', { className: 'sf-trait__name', text: text(trait.name) }),
        description ? el('span', { className: 'sf-trait__desc', text: description }) : null,
      ]),
      el('span', { className: 'sf-trait__count', text: evidence.length === 1 ? '1 quote' : `${evidence.length} quotes` }),
      createIcon('chevron-down', { size: 16, className: 'sf-trait__chevron' }),
    ]),
    el('div', { className: 'sf-trait__evidence' },
      evidence.length > 0
        ? evidence.map((item) => quote(item, site))
        : [el('p', { className: 'sf-trait__none', text: 'No quote could be verified for this trait.' })],
    ),
  ]);
  details.open = open;
  return details;
}

/**
 * A quote from the site with its verified badge and source link.
 * @param {Record<string, any>} item { quote, source_url, verified }
 * @param {string} site The brand's host, for a short source link.
 * @returns {HTMLElement}
 */
function quote(item, site) {
  return el('figure', { className: 'sf-quote' }, [
    el('blockquote', { className: 'sf-quote__text' }, [el('p', { text: text(item.quote) })]),
    el('figcaption', { className: 'sf-quote__meta' }, [verifiedBadge(item.verified), sourceLink(item.source_url, { site })]),
  ]);
}

/**
 * One tone scale: the two end words, a track with a marker at the value,
 * and a sentence for screen readers ("Formal to casual: 70 out of 100,
 * leans casual"). The marker position comes from --sf-value in the CSS.
 * @param {{ left: string, right: string }} scale
 * @param {number} raw
 * @returns {HTMLElement}
 */
function scaleRow({ left, right }, raw) {
  const value = Math.min(Math.max(Math.round(raw), 0), 100);
  const lean = describeLean(value, left, right);

  const row = el('div', { className: 'sf-scale' }, [
    el('div', { className: 'sf-scale__labels', attrs: { 'aria-hidden': 'true' } }, [
      el('span', { text: left }),
      el('span', { className: 'sf-scale__lean', text: lean }),
      el('span', { className: 'sf-scale__right', text: right }),
    ]),
    el('div', { className: 'sf-scale__track', attrs: { 'aria-hidden': 'true' } }, [
      el('span', { className: 'sf-scale__fill' }),
      el('span', { className: 'sf-scale__rail' }, [el('span', { className: 'sf-scale__dot' })]),
    ]),
    el('p', { className: 'visually-hidden', text: `${left} to ${right.toLowerCase()}: ${value} out of 100, ${lean.toLowerCase()}.` }),
  ]);
  row.style.setProperty('--sf-value', String(value));
  return row;
}

/**
 * 0–15 "Strongly formal", 16–35 "Leans formal", 36–64 "Balanced",
 * 65–84 "Leans casual", 85–100 "Strongly casual".
 * @param {number} value
 * @param {string} left
 * @param {string} right
 * @returns {string}
 */
function describeLean(value, left, right) {
  if (value <= 15) return `Strongly ${left.toLowerCase()}`;
  if (value <= 35) return `Leans ${left.toLowerCase()}`;
  if (value >= 85) return `Strongly ${right.toLowerCase()}`;
  if (value >= 65) return `Leans ${right.toLowerCase()}`;
  return 'Balanced';
}

/**
 * @param {string} title
 * @param {string} icon
 * @param {'do' | 'dont'} kind
 * @param {string[]} items
 * @returns {HTMLElement}
 */
function ruleList(title, icon, kind, items) {
  return el('div', { className: `sf-rules sf-rules--${kind}` }, [
    el('h4', { className: 'sf-rules__title' }, [createIcon(icon, { size: 20 }), title]),
    el('ul', { className: 'sf-rules__list' }, items.map((item) => el('li', { text: item }))),
  ]);
}
