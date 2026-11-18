import { describe, expect, it } from "vite-plus/test";

import { formatBytes, formatSeconds, formatValue } from "./format.ts";

describe("formatValue", () => {
  it("writes each kind of value on one line", () => {
    expect(formatValue("LC-2026-0318")).toBe("LC-2026-0318");
    expect(formatValue(4)).toBe("4");
    expect(formatValue(null)).toBe("");
    expect(formatValue({ amount: "391.20", currency: "GBP" })).toBe("391.20 GBP");
    expect(formatValue({ count: 3, percent: "12.5" })).toBe("count 3, percent 12.5");
    expect(formatValue([{ qty: 4 }, { qty: 12 }])).toBe("2 records");
    expect(formatValue([{ qty: 4 }])).toBe("1 record");
  });
});

describe("sizes and times", () => {
  it("rounds to what is worth reading", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(51598)).toBe("50 kB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(formatSeconds(2.92)).toBe("2.9 s");
    expect(formatSeconds(41.4)).toBe("41 s");
  });
});
