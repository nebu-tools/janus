import { describe, expect, it } from "vite-plus/test";

import { nearest, readingOrder } from "./PageView.tsx";

const box = (x0: number, y0: number, x1: number, y1: number) => ({ x0, y0, x1, y1 });

describe("readingOrder", () => {
  it("reads row after row from the top, each row from the left", () => {
    const boxes = [box(200, 100, 260, 112), box(40, 300, 90, 312), box(40, 100, 90, 112)];
    expect(readingOrder(boxes)).toEqual([2, 0, 1]);
  });

  it("takes boxes whose tops are close as one row", () => {
    // The second word sits two units lower than the first, and is still on its line.
    const boxes = [box(120, 102, 180, 114), box(40, 100, 100, 112), box(40, 120, 100, 132)];
    expect(readingOrder(boxes)).toEqual([1, 0, 2]);
  });

  it("puts a box that holds others before them", () => {
    const table = box(40, 100, 400, 300);
    const cell = box(40, 100, 120, 120);
    expect(readingOrder([cell, table])).toEqual([1, 0]);
  });

  it("is empty for no boxes", () => {
    expect(readingOrder([])).toEqual([]);
  });
});

describe("nearest", () => {
  // Two columns of three rows.
  const grid = [
    box(40, 100, 100, 112),
    box(300, 100, 360, 112),
    box(40, 130, 100, 142),
    box(300, 130, 360, 142),
    box(40, 160, 100, 172),
    box(300, 160, 360, 172),
  ];

  it("goes down and up within a column", () => {
    expect(nearest(grid, 1, 1)).toBe(3);
    expect(nearest(grid, 3, 1)).toBe(5);
    expect(nearest(grid, 4, -1)).toBe(2);
  });

  it("has nothing past the last row or before the first", () => {
    expect(nearest(grid, 5, 1)).toBeNull();
    expect(nearest(grid, 0, -1)).toBeNull();
  });

  it("never stays on the row it is on", () => {
    expect(nearest([grid[0]!, grid[1]!], 0, 1)).toBeNull();
  });

  it("prefers a box straight below to a nearer one far to the side", () => {
    const boxes = [box(40, 100, 100, 112), box(400, 120, 460, 132), box(40, 150, 100, 162)];
    expect(nearest(boxes, 0, 1)).toBe(2);
  });

  it("is null for a box that is not there", () => {
    expect(nearest(grid, 9, 1)).toBeNull();
  });
});
