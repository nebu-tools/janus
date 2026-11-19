// Every colour the workbench paints, measured: text at 4.5 to 1 against what it is painted on,
// a stroke that says something at 3 to 1, and dimmed text at 3 to 1. The colours are read from
// the two style sheets, so a later change that breaks a pair fails here.
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vite-plus/test";

type Rgb = readonly [number, number, number];

const sheet = readFileSync(join(import.meta.dirname, "styles.css"), "utf8");
const pageSheet = readFileSync(join(import.meta.dirname, "ui", "PageView.css"), "utf8");

const tokensIn = (block: string) =>
  new Map([...block.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => [m[1]!, m[2]!.trim()]));

const block = (pattern: RegExp) => {
  const found = pattern.exec(sheet);
  if (!found) throw new Error(`styles.css has no block for ${pattern}`);
  return tokensIn(found[1]!);
};

const light = block(/^:root \{([^}]+)\}/m);
const dark = new Map([
  ...light,
  ...block(/@media \(prefers-color-scheme: dark\) \{\s*:root \{([^}]+)\}/),
]);
const THEMES = [
  ["light", light],
  ["dark", dark],
] as const;

const hex = (value: string): Rgb => {
  const found = /^#([0-9a-f]{6})$/i.exec(value);
  if (!found) throw new Error(`${value} is not a six digit hex colour`);
  const n = Number.parseInt(found[1]!, 16);
  return [n >> 16, (n >> 8) & 255, n & 255];
};

/** `top` at `alpha` over `under`, as the browser blends them. */
const over = (top: Rgb, alpha: number, under: Rgb): Rgb =>
  [0, 1, 2].map((i) => top[i]! * alpha + under[i]! * (1 - alpha)) as unknown as Rgb;

const luminance = (color: Rgb) => {
  const [r, g, b] = color.map((v) => {
    const c = v / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

const ratio = (a: Rgb, b: Rgb) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
};

/** A token that is a translucent colour: `rgb(r g b / a)`. */
const veil = (value: string): { color: Rgb; alpha: number } => {
  const found = /^rgb\((\d+) (\d+) (\d+) \/ ([\d.]+)\)$/.exec(value);
  if (!found) throw new Error(`${value} is not rgb(r g b / a)`);
  return {
    color: [Number(found[1]), Number(found[2]), Number(found[3])],
    alpha: Number(found[4]),
  };
};

const TEXT = 4.5;
const STROKE = 3;
const DIMMED = 3;

// [what is painted, what it is painted on, the least ratio]. "a/b" is the veil `a` over `b`.
const PAIRS: readonly (readonly [string, string, number])[] = [
  ["--ink", "--paper", TEXT],
  ["--ink", "--raised", TEXT],
  ["--ink", "--sunk", TEXT],
  ["--ink", "--moss-wash", TEXT],
  ["--ink", "--marmalade-wash", TEXT],
  ["--ink", "--jam-wash", TEXT],
  ["--ink", "--selection", TEXT],
  ["--ink", "--wash/--paper", TEXT],
  ["--ink-2", "--paper", TEXT],
  ["--ink-2", "--raised", TEXT],
  ["--ink-2", "--moss-wash", TEXT],
  ["--ink-2", "--marmalade-wash", TEXT],
  ["--ink-2", "--wash/--paper", TEXT],
  ["--ink-2", "--wash/--raised", TEXT],
  // Placeholders, comments and line numbers.
  ["--ink-3", "--paper", TEXT],
  ["--ink-3", "--raised", TEXT],
  ["--moss-text", "--paper", TEXT],
  ["--moss-text", "--raised", TEXT],
  ["--moss-text", "--moss-wash", TEXT],
  ["--marmalade-text", "--raised", TEXT],
  ["--marmalade-text", "--marmalade-wash", TEXT],
  ["--marmalade-text", "--moss-wash", TEXT],
  ["--jam-text", "--paper", TEXT],
  ["--jam-text", "--raised", TEXT],
  ["--jam-text", "--jam-wash", TEXT],
  ["--jam-text", "--moss-wash", TEXT],
  ["--on-accent", "--moss", TEXT],
  ["--paper", "--ink", TEXT],
  // The border of a button or a field, against what lies on either side of it.
  ["--edge", "--paper", STROKE],
  ["--edge", "--raised", STROKE],
  ["--edge", "--sunk", STROKE],
  // The focus ring and the mark under the open tab.
  ["--moss", "--paper", STROKE],
  ["--moss", "--raised", STROKE],
  ["--moss", "--sunk", STROKE],
  // The bar at the edge of a failure and of a note.
  ["--jam", "--paper", STROKE],
  ["--jam", "--raised", STROKE],
  ["--marmalade-text", "--raised", STROKE],
];

// What stays on screen from an old answer is dimmed as a whole: text and its background both
// blend with what lies under the list.
const DIMMED_PAIRS: readonly (readonly [string, string, string])[] = [
  ["--ink", "--paper", "--paper"],
  ["--ink-2", "--paper", "--paper"],
  ["--ink-3", "--paper", "--paper"],
  ["--moss-text", "--paper", "--paper"],
  ["--jam-text", "--paper", "--paper"],
  ["--moss-text", "--moss-wash", "--paper"],
  ["--marmalade-text", "--marmalade-wash", "--paper"],
  ["--jam-text", "--jam-wash", "--paper"],
  ["--ink", "--raised", "--paper"],
  ["--ink-2", "--raised", "--paper"],
  ["--marmalade-text", "--raised", "--paper"],
  ["--jam-text", "--raised", "--paper"],
  ["--ink", "--raised", "--raised"],
  ["--ink-2", "--raised", "--raised"],
];

// `--rule` divides panels and rows. Nothing is told by it alone, so it has no least ratio.
const DECORATIVE = new Set(["--rule"]);

const WHITE: Rgb = [255, 255, 255];

describe("the colours of the workbench", () => {
  for (const [name, tokens] of THEMES) {
    const color = (token: string): Rgb => {
      const [top, under] = token.split("/");
      const value = tokens.get(top!);
      if (value === undefined) throw new Error(`styles.css has no ${top}`);
      if (under === undefined) return hex(value);
      const { color: tint, alpha } = veil(value);
      return over(tint, alpha, color(under));
    };

    it(`${name}: text and strokes have their ratio`, () => {
      const short = PAIRS.filter(([fg, bg, least]) => ratio(color(fg), color(bg)) < least).map(
        ([fg, bg, least]) =>
          `${fg} on ${bg}: ${ratio(color(fg), color(bg)).toFixed(2)}, under ${least}`,
      );
      expect(short).toEqual([]);
    });

    it(`${name}: dimmed text stays at 3 to 1`, () => {
      const old = Number(tokens.get("--old"));
      expect(old).toBeGreaterThan(0);
      const short = DIMMED_PAIRS.map(([fg, bg, under]) => {
        const seen = ratio(over(color(fg), old, color(under)), over(color(bg), old, color(under)));
        return [`${fg} on ${bg} over ${under}`, seen] as const;
      })
        .filter(([, seen]) => seen < DIMMED)
        .map(([what, seen]) => `${what}: ${seen.toFixed(2)}`);
      expect(short).toEqual([]);
    });
  }

  it("covers every colour token", () => {
    const measured = new Set(
      [...PAIRS.flatMap(([fg, bg]) => [fg, bg]), ...DIMMED_PAIRS.flat()].flatMap((part) =>
        part.split("/"),
      ),
    );
    const left = [...light.keys()].filter(
      (token) =>
        /^(#|rgb)/.test(light.get(token)!) &&
        !token.startsWith("--page-") &&
        !measured.has(token) &&
        !DECORATIVE.has(token),
    );
    expect(left).toEqual([]);
    // Dark names no colour that light does not.
    expect([...dark.keys()].filter((token) => !light.has(token))).toEqual([]);
  });
});

describe("what is drawn on a page", () => {
  // A page is white in both themes. In the dark theme the whole page view, with everything
  // drawn on it, is shown at this brightness.
  const brightness = Number(
    /\.pageview \{\s*filter: brightness\(([\d.]+)\)/.exec(sheet)?.[1] ?? Number.NaN,
  );
  const old = Number(/\.pageview-box\[data-old\] \{[^}]*opacity: ([\d.]+)/.exec(pageSheet)?.[1]);
  const dim = (color: Rgb): Rgb => color.map((v) => v * brightness) as unknown as Rgb;
  const palette = [...light].filter(([token]) => token.startsWith("--page-"));

  it("reads the palette, the brightness and the strength of an old box", () => {
    expect(palette.length).toBe(9);
    expect(brightness).toBeGreaterThan(0);
    expect(old).toBeGreaterThan(0);
    expect(dark.get("--page-hits")).toBe(light.get("--page-hits"));
  });

  it("every box colour is 3 to 1 on white, also as an old box and in the dark theme", () => {
    const short: string[] = [];
    for (const [token, value] of palette) {
      const cases: readonly (readonly [string, Rgb, Rgb])[] = [
        ["on white", hex(value), WHITE],
        ["old, on white", over(hex(value), old, WHITE), WHITE],
        ["dark theme", dim(hex(value)), dim(WHITE)],
        ["old, dark theme", dim(over(hex(value), old, WHITE)), dim(WHITE)],
      ];
      for (const [what, fg, bg] of cases) {
        if (ratio(fg, bg) < STROKE) short.push(`${token} ${what}: ${ratio(fg, bg).toFixed(2)}`);
      }
    }
    expect(short).toEqual([]);
  });

  it("the page view's own colours have their ratio", () => {
    const INK = "#1f1c17";
    const BORDER = "#6b6455";
    const LABEL = "#f6eedc";
    // Every colour PageView.css names is one of these. A new one has to be measured here.
    const named = new Set(pageSheet.match(/#[0-9a-f]{3,8}\b/gi));
    expect([...named].sort()).toEqual([INK, BORDER, LABEL, "#fff"].sort());
    for (const shade of [(c: Rgb) => c, dim]) {
      expect(ratio(shade(hex(INK)), shade(WHITE))).toBeGreaterThanOrEqual(TEXT);
      expect(ratio(shade(hex(LABEL)), shade(hex(INK)))).toBeGreaterThanOrEqual(TEXT);
      expect(ratio(shade(hex(BORDER)), shade(WHITE))).toBeGreaterThanOrEqual(STROKE);
    }
  });
});
