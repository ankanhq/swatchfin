/**
 * Sources section: how many calls each TinyFish API made for this guide,
 * then every page that was read, with the API that read it.
 */

import { formatDate, safeUrl } from '../utils.js';
import { el, createIcon, emptyState, list, lookup, sourceLink, text } from './dom.js';

/** Each TinyFish API: its label and icon. */
const APIS = {
  search: { label: 'Search', icon: 'search' },
  fetch: { label: 'Fetch', icon: 'file-text' },
  browser: { label: 'Browser', icon: 'app-window' },
};

/**
 * @param {Record<string, any>} guide
 * @returns {HTMLElement}
 */
export function renderSources(guide) {
  const sources = list(guide.sources).filter((source) => safeUrl(source?.url));
  const usage = guide.tinyfish_usage ?? {};

  return el('div', { className: 'sf-sources' }, [
    el('ul', { className: 'sf-usage', attrs: { 'aria-label': 'TinyFish API usage for this guide' } }, [
      usageTile('search', usage.search_calls, 'Search call', 'Search calls', 'Found the site and its key pages'),
      usageTile('fetch', usage.fetch_urls, 'URL fetched', 'URLs fetched', 'Read the homepage and sub-pages'),
      usageTile('browser', usage.browser_sessions, 'Browser session', 'Browser sessions', 'Measured the computed styles'),
    ]),
    sources.length > 0
      ? el('ol', { className: 'sf-source-list' }, sources.map(sourceRow))
      : emptyState('No sources listed', 'This guide doesn’t say which pages were read.'),
    el('p', { className: 'sf-note' }, [
      'Swatchfin uses three TinyFish APIs, each with its own job. ',
      el('a', { text: 'How Swatchfin uses TinyFish', attrs: { href: 'about.html' } }),
    ]),
  ]);
}

/**
 * @param {keyof typeof APIS} api
 * @param {unknown} count
 * @param {string} singular
 * @param {string} plural
 * @param {string} job
 * @returns {HTMLElement}
 */
function usageTile(api, count, singular, plural, job) {
  const known = Number.isInteger(count) && count >= 0;
  return el('li', { className: 'sf-usage__tile' }, [
    el('span', { className: 'sf-usage__api' }, [createIcon(APIS[api].icon, { size: 16 }), `TinyFish ${APIS[api].label}`]),
    el('span', { className: 'sf-usage__count' }, [
      el('span', { className: 'sf-usage__number', text: known ? String(count) : '–' }),
      el('span', { className: 'sf-usage__unit', text: count === 1 ? singular : plural }),
    ]),
    el('span', { className: 'sf-usage__job', text: job }),
  ]);
}

/**
 * @param {Record<string, any>} source { url, title, api, fetched_at }
 * @returns {HTMLElement}
 */
function sourceRow(source) {
  const api = lookup(APIS, source.api);
  const title = text(source.title);
  const when = formatDate(source.fetched_at, { withTime: true });

  return el('li', { className: 'sf-source' }, [
    api
      ? el('span', { className: `sf-badge sf-source__api sf-source__api--${source.api}` }, [createIcon(api.icon, { size: 16 }), api.label])
      : el('span', { className: 'sf-badge sf-source__api', text: 'Unknown' }),
    el('span', { className: 'sf-source__page' }, [
      title ? el('span', { className: 'sf-source__title', text: title }) : null,
      sourceLink(source.url),
    ]),
    when ? el('time', { className: 'sf-source__time', text: when, attrs: { datetime: source.fetched_at } }) : null,
  ]);
}
