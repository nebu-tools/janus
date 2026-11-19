// A spec's results arrive as one flat list: each field, and after a records field its cells
// as `lines/0/qty`. This groups them for the screen.
import type { FieldOut } from "../api/client.ts";

export interface FieldGroup {
  field: FieldOut;
  /** The column names of a records field, in the order they first appear. */
  columns: string[];
  /** One row for each record: the cell under each column, where there is one. */
  records: (FieldOut | undefined)[][];
}

export function groupFields(fields: readonly FieldOut[]): FieldGroup[] {
  const groups: FieldGroup[] = [];
  const byPath = new Map<string, FieldGroup>();
  for (const field of fields) {
    const parts = field.path.split("/");
    const parent = parts.length === 3 ? byPath.get(parts[0] ?? "") : undefined;
    const row = Number(parts[1]);
    const column = parts[2];
    if (parent && column !== undefined && Number.isInteger(row) && row >= 0) {
      let at = parent.columns.indexOf(column);
      if (at < 0) at = parent.columns.push(column) - 1;
      (parent.records[row] ??= [])[at] = field;
      continue;
    }
    const group: FieldGroup = { field, columns: [], records: [] };
    groups.push(group);
    byPath.set(field.path, group);
  }
  for (const group of groups) {
    group.records = Array.from(group.records, (cells) =>
      Array.from({ length: group.columns.length }, (_, i) => cells?.[i]),
    );
  }
  return groups;
}

const STATUSES = ["missing", "invalid", "ambiguous", "incomplete", "unconfirmed"] as const;

/** The outcome of a run in words: "7 fields extracted, 1 missing". It counts the fields the
 * spec names and not their cells, and uses the library's words for a status. */
export function outcome(groups: readonly FieldGroup[]): string {
  const count = (status: string) => groups.filter((g) => g.field.status === status).length;
  const good = count("extracted");
  const parts = [`${good} ${good === 1 ? "field" : "fields"} extracted`];
  for (const status of STATUSES) {
    const n = count(status);
    if (n > 0) parts.push(`${n} ${status}`);
  }
  return parts.join(", ");
}

/** What a field or a cell is and holds, for a screen reader and for a label on the page. */
export function fieldLabel(field: FieldOut, shownValue: string): string {
  const value = shownValue === "" ? "" : `: ${shownValue}`;
  return `${field.path}${value}, ${field.status}`;
}
