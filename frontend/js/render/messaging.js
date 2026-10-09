/**
 * Key messaging section: tagline and mission side by side, then value
 * propositions and the audience. A missing tagline or mission is shown as
 * missing, with the reason, rather than left out.
 */

import { el, emptyState, list, sourceLink, subsection, text, verifiedBadge } from './dom.js';

/**
 * @param {Record<string, any>} guide
 * @returns {HTMLElement}
 */
export function renderMessaging(guide) {
  const messaging = guide.messaging ?? {};
  const tagline = statementText(messaging.tagline);
  const mission = statementText(messaging.mission);
  const props = list(messaging.value_props).filter((prop) => text(prop?.title) || text(prop?.quote));
  const audience = list(messaging.audience).map(text).filter(Boolean);

  if (!tagline && !mission && props.length === 0 && audience.length === 0) {
    return emptyState('No key messages found', 'None of the fetched pages had a tagline, mission or value proposition that could be verified word for word.');
  }

  return el('div', { className: 'sf-messaging' }, [
    el('div', { className: 'sf-statements' }, [
      tagline
        ? statement('Tagline', messaging.tagline, 'tagline')
        : missingStatement('Tagline', 'No tagline found', 'Swatchfin only shows a tagline that appears word for word on the site.'),
      mission
        ? statement('Mission', messaging.mission, 'mission')
        : missingStatement('Mission', 'No mission statement found', 'Swatchfin only shows a mission that appears word for word on the site.'),
    ]),
    props.length > 0 ? subsection('Value propositions', [el('ul', { className: 'sf-props' }, props.map(valueProp))]) : null,
    audience.length > 0
      ? subsection('Audience', [
          el('ul', { className: 'sf-tags' }, audience.map((item) => el('li', { className: 'sf-tag', text: item }))),
          el('p', { className: 'sf-note', text: 'Inferred from the fetched pages.' }),
        ])
      : null,
  ]);
}

/**
 * @param {unknown} value A { text, source_url, verified } object, or null.
 * @returns {string}
 */
function statementText(value) {
  return value && typeof value === 'object' ? text(value.text) : '';
}

/**
 * @param {string} label
 * @param {Record<string, any>} value
 * @param {'tagline' | 'mission'} kind
 * @returns {HTMLElement}
 */
function statement(label, value, kind) {
  return el('figure', { className: `sf-statement sf-statement--${kind}` }, [
    el('p', { className: 'sf-statement__label', text: label }),
    el('blockquote', { className: 'sf-statement__text' }, [el('p', { text: text(value.text) })]),
    el('figcaption', { className: 'sf-statement__meta' }, [verifiedBadge(value.verified), sourceLink(value.source_url)]),
  ]);
}

/**
 * @param {string} label
 * @param {string} title
 * @param {string} reason
 * @returns {HTMLElement}
 */
function missingStatement(label, title, reason) {
  return el('div', { className: 'sf-statement sf-statement--missing' }, [
    el('p', { className: 'sf-statement__label', text: label }),
    el('p', { className: 'sf-statement__missing-title', text: title }),
    el('p', { className: 'sf-statement__missing-text', text: reason }),
  ]);
}

/**
 * @param {Record<string, any>} prop { title, quote, source_url, verified }
 * @returns {HTMLElement}
 */
function valueProp(prop) {
  const quote = text(prop.quote);
  return el('li', { className: 'sf-prop' }, [
    text(prop.title) ? el('h4', { className: 'sf-prop__title', text: text(prop.title) }) : null,
    quote ? el('blockquote', { className: 'sf-prop__quote' }, [el('p', { text: quote })]) : null,
    el('div', { className: 'sf-prop__meta' }, [verifiedBadge(prop.verified), sourceLink(prop.source_url)]),
  ]);
}
