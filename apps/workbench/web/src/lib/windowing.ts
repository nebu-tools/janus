// Where each page sits in a tall scroller, and which pages are near the viewport.
// Page sizes are known before any image loads, so nothing moves once it is laid out.

export interface Sized {
  width: number;
  height: number;
}

export interface Stack {
  /** The top of each page, in pixels from the top of the scroller's content. */
  tops: number[];
  heights: number[];
  total: number;
}

/** Stack pages scaled to `width` pixels wide, `gap` pixels apart, with `gap` above and below. */
export function stackPages(pages: readonly Sized[], width: number, gap: number): Stack {
  const tops: number[] = [];
  const heights: number[] = [];
  let y = gap;
  for (const page of pages) {
    const height = page.width > 0 ? Math.round((page.height / page.width) * width) : 0;
    tops.push(y);
    heights.push(height);
    y += height + gap;
  }
  return { tops, heights, total: y };
}

/** The index of the last page whose top is at or above `y`; 0 when there is none. */
export function pageAt(stack: Stack, y: number): number {
  let low = 0;
  let high = stack.tops.length - 1;
  while (low < high) {
    const mid = (low + high + 1) >> 1;
    if ((stack.tops[mid] ?? 0) <= y) low = mid;
    else high = mid - 1;
  }
  return Math.max(low, 0);
}

/** The first and last index to draw: the pages in view and `overscan` pixels around them. */
export function visibleRange(
  stack: Stack,
  scrollTop: number,
  viewport: number,
  overscan: number,
): [first: number, last: number] {
  if (stack.tops.length === 0) return [0, -1];
  return [pageAt(stack, scrollTop - overscan), pageAt(stack, scrollTop + viewport + overscan)];
}
