// How values and sizes are written on screen.

/** A field's value on one line: text as it is, money as "391.20 GBP", records as a count. */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    return value.every((v) => typeof v === "object" && v !== null && !Array.isArray(v))
      ? `${value.length} ${value.length === 1 ? "record" : "records"}`
      : value.map(formatValue).join(", ");
  }
  const entries = Object.entries(value as Record<string, unknown>);
  const keys = entries
    .map(([key]) => key)
    .sort()
    .join(" ");
  if (keys === "amount currency") {
    const money = value as { amount: unknown; currency: unknown };
    return `${formatValue(money.amount)} ${formatValue(money.currency)}`;
  }
  return entries.map(([key, v]) => `${key} ${formatValue(v)}`).join(", ");
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} kB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatSeconds(seconds: number): string {
  return seconds < 10 ? `${seconds.toFixed(1)} s` : `${Math.round(seconds)} s`;
}
