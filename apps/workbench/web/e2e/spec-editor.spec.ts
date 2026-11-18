import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { ready, spec } from "./examples.ts";

const write = async (page: Page, text: string) => {
  const editor = page.getByRole("textbox", { name: "Spec, in YAML" });
  await editor.click();
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.insertText(text);
};

test("a spec runs as it is typed and its fields point at the page", async ({ page, request }) => {
  const id = await ready(request, "invoice");
  await page.goto(`/d/${id}/spec`);
  const results = page.getByRole("region", { name: "Results" });
  await expect(results).toContainText("Write a spec on the left");

  await write(page, spec("invoice"));
  await expect(results).toContainText("8 of 8 fields extracted");
  const total = results.locator('.fieldrow[data-path="total"]');
  await expect(total).toContainText("extracted");
  await expect(total).toContainText("391.20 GBP");
  await expect(results.locator('.cellbutton[data-path="lines/0/qty"]')).toHaveText("4");

  // Selecting a field draws its box strongly. Hovering the box names the field.
  await total.click();
  const box = page.locator('[data-box="total"]');
  await expect(box).toHaveAttribute("data-look", "strong");
  await box.hover();
  await expect(page.getByRole("tooltip")).toContainText("total: 391.20 GBP");

  // Clicking a box selects its field.
  await page.locator('[data-box="number"]').click();
  await expect(results.locator('.fieldrow[data-path="number"]')).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("a spec that does not load is marked on its line", async ({ page, request }) => {
  const id = await ready(request, "invoice");
  await page.goto(`/d/${id}/spec`);
  await write(page, "name: Broken\nfields:\n  total: { labl: Total due }\n");
  await expect(page.getByTestId("spec-problem")).toHaveText("Line 3: total: unknown key labl");
  await expect(page.locator(".cm-lint-marker-error")).toHaveCount(1);

  await write(page, "name: Mended\nfields:\n  total: { label: Total due, type: money GBP }\n");
  await expect(page.getByTestId("spec-problem")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Results" })).toContainText(
    "1 of 1 field extracted",
  );
});

test("a slow answer for an older edit does not replace a newer one", async ({ page, request }) => {
  const id = await ready(request, "invoice");
  let held = 0;
  await page.route("**/extract", async (route) => {
    if (route.request().postData()?.includes("older")) {
      held += 1;
      await new Promise((r) => setTimeout(r, 2500));
    }
    await route.continue().catch(() => {});
  });
  await page.goto(`/d/${id}/spec`);
  const results = page.getByRole("region", { name: "Results" });

  await write(page, "name: older\nfields:\n  number: { label: Invoice No. }\n");
  await expect.poll(() => held).toBe(1);
  await write(page, "name: newer\nfields:\n  customer: { label: Customer }\n");
  await expect(results.locator('.fieldrow[data-path="customer"]')).toContainText(
    "Tern Street Riders",
  );
  await page.waitForTimeout(3000);
  await expect(results.locator('.fieldrow[data-path="customer"]')).toBeVisible();
  await expect(results.locator('.fieldrow[data-path="number"]')).toHaveCount(0);
});

test("a spec is saved under a name and opened again", async ({ page, request }) => {
  const id = await ready(request, "purchase-order");
  await page.goto(`/d/${id}/spec`);
  await write(page, spec("purchase-order"));
  await page.getByRole("textbox", { name: "Spec name" }).fill("Purchase order");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".spec-foot")).toContainText("Saved");

  await page.reload();
  await expect(page.getByRole("region", { name: "Results" })).toContainText(
    "Write a spec on the left",
  );
  await page.getByRole("combobox", { name: "Open a saved spec" }).selectOption("Purchase order");
  await expect(page.getByRole("textbox", { name: "Spec, in YAML" })).toContainText("fitting_days");
  await expect(page.getByRole("region", { name: "Results" })).toContainText("fields extracted");
});

test("old results are never shown as current while a newer edit runs", async ({
  page,
  request,
}) => {
  const id = await ready(request, "invoice");
  let held = 0;
  await page.route("**/extract", async (route) => {
    if (route.request().postData()?.includes("slow")) {
      held += 1;
      await new Promise((r) => setTimeout(r, 2500));
    }
    await route.continue().catch(() => {});
  });
  await page.goto(`/d/${id}/spec`);
  const results = page.getByRole("region", { name: "Results" });
  const list = results.locator(".fields");

  await write(page, "name: first\nfields:\n  number: { label: Invoice No. }\n");
  await expect(list).toHaveAttribute("data-stale", "false");
  await expect(results.locator('.fieldrow[data-path="number"]')).toBeVisible();

  await write(page, "name: slow\nfields:\n  customer: { label: Customer }\n");
  await expect(list).toHaveAttribute("data-stale", "true");
  await expect(results).toContainText("These results are for the earlier text.");
  await expect.poll(() => held).toBe(1);

  // From here on, note every set of fields the list shows as current.
  await page.evaluate(() => {
    const seen: string[] = [];
    (window as unknown as { seen: string[] }).seen = seen;
    const note = () => {
      const fields = document.querySelector(".fields");
      if (fields && fields.getAttribute("data-stale") !== "true") {
        const paths = [...fields.querySelectorAll(".fieldrow")].map((r) =>
          r.getAttribute("data-path"),
        );
        seen.push(paths.join(","));
      }
    };
    new MutationObserver(note).observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      characterData: true,
    });
  });

  // Typing while the slow request is out.
  await write(page, "name: newer\nfields:\n  total: { label: Total due, type: money GBP }\n");
  await expect(results.locator('.fieldrow[data-path="total"]')).toContainText("391.20 GBP");
  await expect(list).toHaveAttribute("data-stale", "false");
  await page.waitForTimeout(3000); // past the time the slow answer would have come
  const seen = await page.evaluate(() => (window as unknown as { seen: string[] }).seen);
  expect(new Set(seen)).toEqual(new Set(["total"]));
});

test("what was typed is kept per document until it is saved", async ({ page, request }) => {
  const invoice = await ready(request, "invoice");
  const order = await ready(request, "purchase-order");
  const editor = page.getByRole("textbox", { name: "Spec, in YAML" });
  const typed = "name: Unsaved\nfields:\n  number: { label: Invoice No. }\n";

  await page.goto(`/d/${invoice}/spec`);
  await write(page, typed);
  await page.getByRole("textbox", { name: "Spec name" }).fill("Kept draft");
  await page.reload();
  await expect(editor).toContainText("name: Unsaved");
  await expect(page.getByRole("textbox", { name: "Spec name" })).toHaveValue("Kept draft");

  await page.goto(`/d/${order}/spec`);
  await expect(page.getByRole("region", { name: "Results" })).toContainText(
    "Write a spec on the left",
  );

  await page.goto(`/d/${invoice}/spec`);
  await expect(editor).toContainText("name: Unsaved");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".spec-foot")).toContainText("Saved as Kept draft");
  await page.reload();
  await expect(page.getByRole("region", { name: "Results" })).toContainText(
    "Write a spec on the left",
  );
  await request.delete(`/api/specs/${encodeURIComponent("Kept draft")}`);
});
