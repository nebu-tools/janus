// Unsaved text in two tabs, and in a browser that cannot store it.
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { ready } from "./examples.ts";
import { write } from "./steps.ts";

const editor = (page: Page) => page.getByRole("textbox", { name: "Spec, in YAML" });
const bar = (page: Page) => page.getByTestId("other-tab");
const stored = (page: Page, id: string) =>
  page.evaluate(
    (key) => (JSON.parse(localStorage.getItem(key) ?? "null") as { text: string } | null)?.text,
    `janus.draft.${id}`,
  );

const SENTENCE =
  "The browser cannot store unsaved text. It is kept only while this page stays open.";

test("a second tab on the same document asks which text to keep", async ({ context, request }) => {
  const id = await ready(request, "invoice");
  const a = await context.newPage();
  await a.goto(`/d/${id}/spec`);
  await a.evaluate(() => localStorage.clear());
  await a.reload();
  const b = await context.newPage();
  await b.goto(`/d/${id}/spec`);

  // A writes. B, which holds another text, shows the bar and stops writing.
  await write(a, "name: from tab A\n");
  await expect(bar(b)).toBeVisible();
  await expect(bar(b)).toHaveRole("alert");
  await expect(bar(a)).toHaveCount(0);
  await write(b, "name: from tab B\n");
  await expect(editor(b)).toContainText("from tab B");
  await expect(bar(b)).toBeVisible();
  expect(await stored(b, id)).toBe("name: from tab A\n");
  // B wrote nothing, so A has nothing to ask.
  await expect(bar(a)).toHaveCount(0);

  // "Keep this text" stores B's text. Now A holds the other text and is asked.
  await bar(b).getByRole("button", { name: "Keep this text" }).click();
  await expect(bar(b)).toHaveCount(0);
  await expect.poll(() => stored(b, id)).toBe("name: from tab B\n");
  await expect(bar(a)).toBeVisible();
  await expect(editor(a)).toContainText("from tab A");

  // "Load the other tab's text" takes it. Both tabs hold one text and neither asks.
  await bar(a).getByRole("button", { name: "Load the other tab's text" }).click();
  await expect(editor(a)).toContainText("from tab B");
  await expect(bar(a)).toHaveCount(0);
  await expect(bar(b)).toHaveCount(0);

  // Typing the other tab's text by hand ends the question too.
  await write(a, "name: third\n");
  await expect(bar(b)).toBeVisible();
  await write(b, "name: third\n");
  await expect(bar(b)).toHaveCount(0);

  // Another document's text is no concern of this tab.
  const other = await ready(request, "parts-list");
  await b.goto(`/d/${other}/spec`);
  await write(b, "name: parts\n");
  await expect.poll(() => stored(b, other)).toBe("name: parts\n");
  await expect(bar(a)).toHaveCount(0);
  await a.evaluate(() => localStorage.clear());
});

for (const [how, breakStorage] of [
  [
    "is full",
    () => {
      Storage.prototype.setItem = () => {
        throw new DOMException("full", "QuotaExceededError");
      };
    },
  ],
  [
    "is switched off",
    () => {
      Object.defineProperty(window, "localStorage", {
        get() {
          throw new DOMException("denied", "SecurityError");
        },
      });
    },
  ],
] as const) {
  test(`storage that ${how} is said once`, async ({ page, request }) => {
    const id = await ready(request, "invoice");
    await page.addInitScript(breakStorage);
    await page.goto(`/d/${id}/spec`);
    await write(page, "name: not stored\n");
    const note = page.getByTestId("unstored");
    await expect(note).toHaveRole("alert");
    await expect(note).toContainText(SENTENCE);
    await expect(editor(page)).toContainText("not stored");

    await note.getByRole("button", { name: "Understood" }).click();
    await expect(note).toHaveCount(0);
    // It is not said again: not for more text, and not for another document.
    await write(page, "name: still not stored\n");
    await expect(editor(page)).toContainText("still not stored");
    await page.getByRole("link", { name: "Inspect" }).click();
    await page.getByRole("link", { name: "Spec editor" }).click();
    await expect(editor(page)).toBeVisible();
    await expect(note).toHaveCount(0);
  });
}
