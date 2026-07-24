export const VIRTUALIZATION_THRESHOLD = 80;
export const ISSUE_ROW_HEIGHT = 120;
export const ISSUE_OVERSCAN = 2;

function codePointIndex(text) {
  const index = [0];
  let utf16 = 0;
  for (const character of text) {
    utf16 += character.length;
    index.push(utf16);
  }
  return index;
}

export function buildOverlaySegments(text, matches) {
  if (typeof text !== "string" || !Array.isArray(matches)) {
    throw new TypeError("text and matches are required");
  }
  const scalarIndex = codePointIndex(text);
  const segments = [];
  let cursor = 0;
  for (const match of matches) {
    const start = scalarIndex[match.offset];
    const end = scalarIndex[match.offset + match.length];
    if (start === undefined || end === undefined || start < cursor || end <= start) continue;
    if (start > cursor) segments.push(Object.freeze({ text: text.slice(cursor, start), match: null }));
    segments.push(Object.freeze({ text: text.slice(start, end), match }));
    cursor = end;
  }
  if (cursor < text.length) segments.push(Object.freeze({ text: text.slice(cursor), match: null }));
  return Object.freeze(segments);
}

export function chunkOverlaySegments(segments, budget = 320) {
  if (!Array.isArray(segments) || !Number.isSafeInteger(budget) || budget < 1) {
    throw new TypeError("overlay segments and a positive integer budget are required");
  }
  const chunks = [];
  for (let start = 0; start < segments.length; start += budget) {
    chunks.push(Object.freeze(segments.slice(start, start + budget)));
  }
  return Object.freeze(chunks);
}

export function computeVirtualWindow({
  count,
  scrollTop,
  viewportHeight,
  rowHeight = ISSUE_ROW_HEIGHT,
  overscan = ISSUE_OVERSCAN,
  threshold = VIRTUALIZATION_THRESHOLD,
}) {
  if (![count, scrollTop, viewportHeight, rowHeight, overscan, threshold].every(Number.isFinite)) {
    throw new TypeError("virtual window inputs must be finite numbers");
  }
  if (count < 0 || scrollTop < 0 || viewportHeight < 0 || rowHeight <= 0 || overscan < 0) {
    throw new RangeError("virtual window inputs are outside their valid range");
  }
  if (count <= threshold) {
    return Object.freeze({ start: 0, end: count, paddingStart: 0, paddingEnd: 0 });
  }
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const end = Math.min(count, Math.ceil((scrollTop + viewportHeight) / rowHeight) + overscan);
  return Object.freeze({
    start,
    end,
    paddingStart: start * rowHeight,
    paddingEnd: (count - end) * rowHeight,
  });
}
