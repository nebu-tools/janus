import { describe, expect, it } from "vite-plus/test";

import type { FieldOut } from "../api/client.ts";
import { fieldLabel, groupFields, outcome } from "./fields.ts";

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

  it("says the outcome of a run, counting the fields the spec names", () => {
    const groups = groupFields([field("a"), field("b", "ambiguous"), field("a/0/x", "missing")]);
    expect(outcome(groups)).toBe("1 field extracted, 1 ambiguous");
    expect(outcome(groupFields([field("a"), field("b")]))).toBe("2 fields extracted");
    expect(outcome(groupFields([field("a", "missing"), field("b", "missing")]))).toBe(
      "0 fields extracted, 2 missing",
    );
  });

  it("describes a field by its path, its value and its status", () => {
    expect(fieldLabel(field("total"), "118.00 GBP")).toBe("total: 118.00 GBP, extracted");
    expect(fieldLabel(field("due", "missing"), "")).toBe("due, missing");
  });
});
