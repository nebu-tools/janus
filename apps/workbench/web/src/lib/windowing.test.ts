import { describe, expect, it } from "vite-plus/test";

import { pageAt, stackPages, visibleRange } from "./windowing.ts";

const a4 = { width: 595, height: 842 };

describe("stackPages", () => {
  it("scales each page to the width and keeps its shape", () => {
    const stack = stackPages([a4, { width: 842, height: 595 }], 595, 10);
    expect(stack.heights).toEqual([842, 420]);
    expect(stack.tops).toEqual([10, 862]);
    expect(stack.total).toBe(10 + 842 + 10 + 420 + 10);
  });

  it("is empty for no pages", () => {
    expect(stackPages([], 600, 10)).toEqual({ tops: [], heights: [], total: 10 });
  });
});

describe("visibleRange", () => {
  const stack = stackPages(
    Array.from({ length: 300 }, () => a4),
    595,
    10,
  );

  it("draws a few pages of a 300-page document", () => {
    const [first, last] = visibleRange(stack, 100 * 852, 900, 600);
    expect(first).toBe(99);
    expect(last).toBe(101);
  });

  it("starts at the first page and ends at the last", () => {
    expect(visibleRange(stack, 0, 900, 600)).toEqual([0, 1]);
    expect(visibleRange(stack, stack.total - 900, 900, 600)[1]).toBe(299);
  });

  it("draws nothing when there are no pages", () => {
    expect(visibleRange(stackPages([], 595, 10), 0, 900, 600)).toEqual([0, -1]);
  });

  it("finds the page that holds a position", () => {
    expect(pageAt(stack, 0)).toBe(0);
    expect(pageAt(stack, 10 + 852 * 7 + 3)).toBe(7);
    expect(pageAt(stack, 1e9)).toBe(299);
  });
});
