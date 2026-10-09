/**
 * Where the guide page gets its data.
 *
 * Phase 2: there is no backend yet, so the only guide is the mock file for
 * Northwind Roasters, a fictional brand. In Phase 4 the body of loadGuide()
 * changes to call GET /api/v1/guides/{id}; nothing else on the page has to.
 */

/** The ID that loads the mock guide: guide.html?id=mock */
export const MOCK_ID = 'mock';

const MOCK_URL = 'mock/MOCK_northwind-roasters.json';

/** This page understands schema 1.x (see CLAUDE.md, section 6). */
const SUPPORTED_MAJOR_VERSION = '1';

/**
 * An error the page can show to people as it is: a short title and a
 * sentence that explains what happened and what to do.
 */
export class GuideError extends Error {
  /**
   * @param {string} title
   * @param {string} message
   */
  constructor(title, message) {
    super(message);
    this.name = 'GuideError';
    this.title = title;
  }
}

/**
 * Loads one brand guide.
 *
 * In plain English: download the guide's JSON, check it really is a guide
 * in a format this page understands, and hand it back. Anything that goes
 * wrong becomes a GuideError with a human-readable message.
 *
 * @param {string} id
 * @returns {Promise<Record<string, any>>}
 */
export async function loadGuide(id) {
  if (id !== MOCK_ID) {
    const shown = id.length > 40 ? `${id.slice(0, 40)}…` : id;
    throw new GuideError(
      'Guide not found',
      `There is no guide with the ID “${shown}”. Guides are kept for a limited time, so it may have expired. Generate a new one from the start page.`,
    );
  }

  let response;
  try {
    // no-store: always read the file fresh while it is being edited.
    response = await fetch(MOCK_URL, { cache: 'no-store' });
  } catch {
    throw new GuideError('Couldn’t load the guide', 'The connection failed. Check that you are online and try again.');
  }

  if (!response.ok) {
    throw new GuideError('Couldn’t load the guide', `The server answered with an error (${response.status}). Try again in a moment.`);
  }

  let data;
  try {
    data = await response.json();
  } catch {
    throw new GuideError('This guide can’t be read', 'The guide data is damaged or incomplete.');
  }

  checkGuide(data);
  return data;
}

/**
 * Throws a GuideError unless the data looks like a guide in schema 1.x.
 * Individual sections are still checked when they are shown, because a
 * real guide can be partial.
 * @param {unknown} data
 */
function checkGuide(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new GuideError('This guide can’t be read', 'The data is not a brand guide.');
  }
  const version = typeof data.schema_version === 'string' ? data.schema_version : '';
  if (version.split('.')[0] !== SUPPORTED_MAJOR_VERSION) {
    throw new GuideError(
      'Unsupported guide format',
      `This guide uses format ${version || '(unknown)'}, but this page only understands format 1. Reload the page to get the latest version.`,
    );
  }
}

/**
 * True for the mock guide. Mock IDs start with "bg_MOCK".
 * @param {Record<string, any>} guide
 * @returns {boolean}
 */
export function isMockGuide(guide) {
  return typeof guide?.id === 'string' && guide.id.startsWith('bg_MOCK');
}
