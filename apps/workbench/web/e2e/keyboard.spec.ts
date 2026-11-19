// Every screen with the keyboard alone, from an upload to a saved spec. No test here clicks.
// What is checked is what a screen reader is given: roles, names, the active option of a page,
// and the words of the live region.
import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";

import { pdf, ready, spec } from "./examples.ts";
import { announcer, tabTo } from "./steps.ts";

interface Row {
  id: string;
}

/** The option of a page's listbox that the keyboard is on. */
const activeOption = async (page: Page, listbox: Locator) => {
  await expect(listbox).toHaveAttribute("aria-activedescendant", /.+/);
  const id = await listbox.getAttribute("aria-activedescendant");
  return page.locator(`[id="${id}"]`);
};

/** Press `key` until the active option's name matches. */
const moveTo = async (page: Page, listbox: Locator, key: string, name: RegExp) => {
  for (let i = 0; i < 60; i++) {
    const label = await (await activeOption(page, listbox)).getAttribute("aria-label");
    if (name.test(label ?? "")) return;
    await page.keyboard.press(key);
  }
  throw new Error(`no box named ${name} was reached with ${key}`);
};

test("from an upload to a search, with the keyboard", async ({ page, request }) => {
  const rows = (await (await request.get("/api/documents")).json()) as Row[];
  for (const row of rows) await request.delete(`/api/documents/${row.id}`);

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "No documents yet" })).toBeVisible();

  // The first stop is the skip link. It goes to the main region.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to the main region" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();

  // An upload.
  await tabTo(page, page.getByRole("button", { name: "Choose PDFs" }).first());
  const chooser = page.waitForEvent("filechooser");
  await page.keyboard.press("Enter");
  await (await chooser).setFiles([pdf("invoice")]);
  const row = page.getByRole("row", { name: /invoice\.pdf/ });
  await expect(row).toContainText("Ready");
  await expect(announcer(page)).toHaveText("invoice.pdf is ready");

  // Open it.
  await tabTo(page, row.getByRole("link", { name: "invoice.pdf", exact: true }));
  await page.keyboard.press("Enter");
  await expect(page).toHaveTitle("Inspect: invoice.pdf · Janus workbench");
  await expect(page.getByRole("heading", { level: 1, name: "Inspect invoice.pdf" })).toBeAttached();
  await expect(page.getByRole("main")).toBeFocused();
  const side = page.getByRole("region", { name: "What Janus read" });
  await expect(side).toContainText("1 page");

  // "/" goes to the phrase field. A letter typed there is text, not a shortcut.
  const box = side.getByRole("searchbox", { name: "Find a phrase" });
  await page.keyboard.press("/");
  await expect(box).toBeFocused();
  await page.keyboard.type("Total");
  await expect(box).toHaveValue("Total");
  await expect(announcer(page)).toHaveText("2 places found");
  await page.keyboard.type("n");
  await expect(box).toHaveValue("Totaln");
  await expect(announcer(page)).toHaveText("Nothing prints the phrase");
  await page.keyboard.press("Backspace");
  await expect(announcer(page)).toHaveText("2 places found");

  // The page is one tab stop. Its boxes are the options of a listbox.
  const listbox = page.getByRole("listbox", { name: /^Page 1, \d+ boxes$/ });
  await tabTo(page, listbox, true);
  const first = await activeOption(page, listbox);
  await expect(first).toHaveRole("option");
  await expect(first).toHaveAccessibleName(/^(Heading|Table|Phrase)/);
  const firstName = await first.getAttribute("aria-label");
  // The label that hover shows is shown for the keyboard too.
  await expect(page.locator(".pageview-label")).toHaveText(firstName ?? "");

  await page.keyboard.press("End");
  const last = await activeOption(page, listbox);
  await expect(last).not.toHaveAccessibleName(firstName ?? "");
  await page.keyboard.press("ArrowUp");
  await expect(listbox).not.toHaveAttribute(
    "aria-activedescendant",
    (await last.getAttribute("id")) ?? "",
  );
  await page.keyboard.press("Home");
  await expect(await activeOption(page, listbox)).toHaveAccessibleName(firstName ?? "");
  await page.keyboard.press("ArrowRight");
  await expect(await activeOption(page, listbox)).not.toHaveAccessibleName(firstName ?? "");
  await page.keyboard.press("ArrowLeft");
  await expect(await activeOption(page, listbox)).toHaveAccessibleName(firstName ?? "");

  // Enter on a phrase box does what a click does: it picks that place in the list.
  await moveTo(page, listbox, "ArrowRight", /^Phrase: /);
  const phrase = await activeOption(page, listbox);
  await page.keyboard.press("Enter");
  await expect(announcer(page)).toHaveText(/^Place \d of 2, page 1: /);
  await expect(phrase).toHaveAttribute("aria-selected", "true");
  await expect(side.locator(".hit[aria-pressed=true]")).toHaveCount(1);

  // Away from text, "n" and "p" step through the places.
  await page.keyboard.press("Home");
  await page.keyboard.press("n");
  const said = (await announcer(page).textContent()) ?? "";
  await expect(announcer(page)).toHaveText(/^Place \d of 2, page 1: /);
  await page.keyboard.press("p");
  await expect(announcer(page)).not.toHaveText(said);
  await expect(announcer(page)).toHaveText(/^Place \d of 2, page 1: /);

  // Escape hands the keyboard back to the page: no box is active, the page keeps focus.
  await page.keyboard.press("Escape");
  await expect(listbox).not.toHaveAttribute("aria-activedescendant");
  await expect(listbox).toBeFocused();
  await expect(page.locator(".pageview-label")).toHaveCount(0);

  // "?" opens the help sheet, Escape closes it, and focus is back where it was.
  await page.keyboard.press("?");
  const help = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(help).toBeVisible();
  await expect(help).toContainText("Next place the phrase is printed");
  await expect(help).toContainText("Next page");
  // No shortcut fires under the sheet.
  await page.keyboard.press("n");
  await page.keyboard.press("Escape");
  await expect(help).toHaveCount(0);
  await expect(listbox).toBeFocused();

  // A layer is a checkbox with a name.
  const words = side.getByRole("checkbox", { name: /Words/ });
  await tabTo(page, words);
  await page.keyboard.press("Space");
  await expect(words).toBeChecked();
  await tabTo(page, listbox, true);
  await moveTo(page, listbox, "ArrowRight", /^Word: /);
});

test("from one page to the next, with the keyboard", async ({ page, request }) => {
  const id = await ready(request, "parts-list");
  await page.goto(`/d/${id}`);
  const one = page.getByRole("listbox", { name: /^Page 1, / });
  await tabTo(page, one);
  await page.keyboard.press("PageDown");
  await expect(announcer(page)).toHaveText("Page 2 of 3");
  const two = page.getByRole("listbox", { name: /^Page 2, / });
  await expect(two).toBeFocused();
  await expect(await activeOption(page, two)).toHaveRole("option");
  await page.keyboard.press("PageUp");
  await expect(announcer(page)).toHaveText("Page 1 of 3");
  await expect(one).toBeFocused();

  // The same with the shortcuts, from anywhere that is not a text field.
  await page.keyboard.press("]");
  await expect(announcer(page)).toHaveText("Page 2 of 3");
  await page.keyboard.press("]");
  await expect(announcer(page)).toHaveText("Page 3 of 3");
  await page.keyboard.press("[");
  await expect(announcer(page)).toHaveText("Page 2 of 3");

  // A table in the list jumps to its page and says so.
  const side = page.getByRole("region", { name: "What Janus read" });
  await tabTo(page, side.getByRole("button", { name: /p3t0/ }));
  await page.keyboard.press("Enter");
  await expect(announcer(page)).toHaveText("Page 3 of 3");

  // The views of the document are a named navigation.
  const views = page.getByRole("navigation", { name: "Views of this document" });
  await tabTo(page, views.getByRole("link", { name: "Spec editor" }), true);
  await page.keyboard.press("Enter");
  await expect(page).toHaveTitle("Spec editor: parts-list.pdf · Janus workbench");
  await expect(page.getByRole("main")).toBeFocused();
});

test("from a spec to a saved spec, with the keyboard", async ({ page, request }, info) => {
  const id = await ready(request, "invoice");
  const name = `Keyboard spec ${info.project.name}`;
  await request.delete(`/api/specs/${encodeURIComponent(name)}`);
  await page.goto(`/d/${id}/spec`);
  await page.evaluate(() => localStorage.clear());
  await page.reload();

  await tabTo(page, page.getByRole("textbox", { name: "Spec name" }));
  await page.keyboard.type(name);
  const editor = page.getByRole("textbox", { name: "Spec, in YAML" });
  await tabTo(page, editor);
  // The text arrives as a paste does. The editor indents typed lines itself.
  await page.keyboard.insertText(spec("invoice"));
  await expect(announcer(page)).toHaveText("8 fields extracted");
  await expect(page.getByTestId("run-status")).toHaveText("8 fields extracted");

  // Save from inside the editor.
  await page.keyboard.press("ControlOrMeta+s");
  await expect(announcer(page)).toHaveText(`Saved as ${name}`);

  // Tab indents in the editor. Escape, then Tab, leaves it.
  await page.keyboard.press("Tab");
  await expect(editor).toBeFocused();
  await page.keyboard.press("Escape");
  await page.keyboard.press("Tab");
  await expect(editor).not.toBeFocused();
  // The indent that Tab typed is a change: run it away again.
  await tabTo(page, editor, true);
  await page.keyboard.press("ControlOrMeta+z");
  await page.keyboard.press("Escape");

  // A field row says its status in words. Enter picks it, and its box on the page with it.
  const results = page.getByRole("region", { name: "Results" });
  const total = results.getByRole("button", { name: /^total extracted 391\.20 GBP/ });
  await tabTo(page, total);
  await page.keyboard.press("Enter");
  await expect(total).toHaveAttribute("aria-pressed", "true");
  const picked = page.getByRole("option", { name: "Field total: 391.20 GBP, extracted" });
  await expect(picked).toHaveAttribute("aria-selected", "true");

  // A cell of a records table says its column, row, value and status.
  await expect(
    results.getByRole("cell", { name: /^qty, row 1: .+, extracted/ }).first(),
  ).toBeVisible();

  // On the page, Enter on a field's box picks the field.
  const listbox = page.getByRole("listbox", { name: /^Page 1, / });
  await tabTo(page, listbox);
  await page.keyboard.press("Home");
  await moveTo(page, listbox, "ArrowRight", /^Field number: /);
  await page.keyboard.press("Enter");
  await expect(results.getByRole("button", { name: /^number extracted/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  // The saved specs are a dialog. Escape closes it and focus returns to the button.
  const opener = page.getByRole("button", { name: "Saved specs" });
  const dialog = page.getByRole("dialog", { name: "Saved specs" });
  // The way back goes through the editor, which keeps Tab until Escape is pressed.
  await tabTo(page, editor, true);
  await page.keyboard.press("Escape");
  await tabTo(page, opener, true);
  await page.keyboard.press("Enter");
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();

  // Delete asks first. "Keep" leaves the spec.
  await page.keyboard.press("Enter");
  await tabTo(page, dialog.getByRole("button", { name: `Delete ${name}` }));
  await page.keyboard.press("Enter");
  await expect(dialog.getByRole("button", { name: `Yes, delete ${name}` })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: `Keep ${name}` })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog.getByRole("button", { name: `Delete ${name}` })).toBeFocused();

  // Open it.
  await tabTo(page, dialog.getByRole("button", { name: `Open ${name}` }), true);
  await page.keyboard.press("Enter");
  await expect(dialog).toHaveCount(0);
  await expect(announcer(page)).toHaveText(`Opened ${name}`);
  await expect(opener).toBeFocused();

  // Delete it.
  await page.keyboard.press("Enter");
  await tabTo(page, dialog.getByRole("button", { name: `Delete ${name}` }));
  await page.keyboard.press("Enter");
  await page.keyboard.press("Enter");
  await expect(announcer(page)).toHaveText(`Deleted ${name}`);
  await expect(dialog.getByRole("button", { name: `Open ${name}` })).toHaveCount(0);
  // Focus is still inside the dialog.
  expect(await dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(opener).toBeFocused();
});
