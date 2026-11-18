import { describe, expect, it } from "vite-plus/test";

import type { FieldOut } from "../api/client.ts";
import { groupFields, tally } from "./fields.ts";

const field = (path: string, status: FieldOut["status"] = "extracted"): FieldOut => ({
  path,
  status,
});

describe("groupFields", () => {
  it("puts a records field's cells under it, a row for each record", () => {
    const groups = groupFields([
      field("number"),
      field("lines"),
      field("lines/0/description"),
      field("lines/0/qty"),
      field("lines/1/description"),
      field("lines/1/qty"),
      field("total", "missing"),
    ]);
    expect(groups.map((g) => g.field.path)).toEqual(["number", "lines", "total"]);
    expect(groups[1]?.columns).toEqual(["description", "qty"]);
    expect(groups[1]?.records.map((r) => r.map((c) => c?.path))).toEqual([
      ["lines/0/description", "lines/0/qty"],
      ["lines/1/description", "lines/1/qty"],
    ]);
    expect(groups[0]?.records).toEqual([]);
  });

  it("leaves a gap where a record has no cell for a column", () => {
    const groups = groupFields([field("lines"), field("lines/0/qty"), field("lines/1/amount")]);
    expect(groups[0]?.columns).toEqual(["qty", "amount"]);
    expect(groups[0]?.records.map((r) => r.map((c) => c?.path))).toEqual([
      ["lines/0/qty", undefined],
      [undefined, "lines/1/amount"],
    ]);
  });

  it("counts the fields the spec names", () => {
    const groups = groupFields([field("a"), field("b", "ambiguous"), field("a/0/x")]);
    expect(tally(groups)).toBe("1 of 2 fields extracted");
    expect(tally(groupFields([field("a")]))).toBe("1 of 1 field extracted");
  });
});
