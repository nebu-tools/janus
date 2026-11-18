// An accessibility scan of every screen and dialog, in the light and the dark theme.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { ready, spec } from "./examples.ts";
import { write } from "./steps.ts";

const OLD = '[data-stale="true"]';

// Zero violations, with one exception. What is drawn from an old answer is dimmed, and dimmed
// text may drop to 3:1 because a line beside it says that it is old. The scan asks 4.5:1 of all
// text, so inside an old answer the contrast rule is left out here. `contrast.test.ts` measures
// the dimmed colours against 3:1 instead.
const scan = async (page: Page) => {
  const current = await new AxeBuilder({ page }).exclude(OLD).analyze();
  const old =
    (await page.locator(OLD).count()) === 0
      ? []
      : (await new AxeBuilder({ page }).include(OLD).disableRules(["color-contrast"]).analyze())
          .violations;
  // What failed and where, in a form a person can read in the test's output.
  expect(
    [...current.violations, ...old].map((v) => ({
      rule: v.id,
      help: v.help,
      where: v.nodes.map((n) => n.target),
    })),
  ).toEqual([]);
};

for (const theme of ["light", "dark"] as const) {
  test.describe(`the ${theme} theme`, () => {
    test.use({ colorScheme: theme });
    // A scan of a page with every box drawn takes its time, most of all in Firefox.
    test.setTimeout(240_000);

    test("Documents", async ({ page, request }) => {
      await ready(request, "invoice");
      await page.goto("/");
      await expect(page.getByRole("row", { name: /invoice\.pdf/ })).toContainText("Ready");
      await scan(page);
      // With a failure on screen.
      await page
        .locator('input[type="file"]')
        .setInputFiles([
          { name: "notes.pdf", mimeType: "application/pdf", buffer: Buffer.from("a list") },
        ]);
      await expect(page.getByTestId("upload-failure")).toBeVisible();
      await scan(page);
    });

    // The one-page invoice: a page of the parts list has some thousand boxes with every layer
    // on, and the scan of it does not end in Firefox.
    test("Inspect, with every layer and a search", async ({ page, request }) => {
      const id = await ready(request, "invoice");
      await page.goto(`/d/${id}`);
      const side = page.getByRole("region", { name: "What Janus read" });
      await expect(side.getByRole("checkbox")).toHaveCount(5);
      for (const layer of await side.getByRole("checkbox").all()) await layer.check();
      await expect(page.getByRole("option", { name: /^Word: / }).first()).toBeAttached();
      await side.getByRole("searchbox", { name: "Find a phrase" }).fill("Total");
      await expect(side.locator(".find-status")).toContainText(/place/);
      await page.getByRole("listbox", { name: /^Page 1, / }).focus();
      await scan(page);

      // An old answer, dimmed and labelled.
      await page.route("**/inspect?find=fail*", (route) => route.abort("connectionrefused"));
      await side.getByRole("searchbox", { name: "Find a phrase" }).fill("fail");
      await expect(side.getByTestId("find-error")).toBeVisible();
      await scan(page);

      await page.getByRole("button", { name: "Keyboard shortcuts" }).click();
      await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
      await scan(page);
    });

    test("Inspect, a document with tables", async ({ page, request }) => {
      const id = await ready(request, "parts-list");
      await page.goto(`/d/${id}`);
      const side = page.getByRole("region", { name: "What Janus read" });
      await side.locator(".tablecard-head").nth(1).click();
      await expect(page.getByRole("listbox", { name: /^Page 2, / })).toBeVisible();
      await scan(page);
    });

    test("Spec editor, with results and the saved specs", async ({ page, request }) => {
      const id = await ready(request, "invoice");
      const name = `Scan ${theme}`;
      await request.put(`/api/specs/${encodeURIComponent(name)}`, {
        data: { text: spec("invoice") },
      });
      await page.goto(`/d/${id}/spec`);
      await write(page, spec("invoice"));
      const results = page.getByRole("region", { name: "Results" });
      await expect(results).toContainText("8 fields extracted");
      await results.locator(".fieldrow").first().click();
      await scan(page);

      // A spec with a problem, and results that are for the earlier text.
      await write(page, "fields: [");
      await expect(page.getByTestId("spec-problem")).toBeVisible();
      await scan(page);

      await page.getByRole("button", { name: "Saved specs" }).click();
      const dialog = page.getByRole("dialog", { name: "Saved specs" });
      await dialog.getByRole("button", { name: `Delete ${name}` }).click();
      await scan(page);
      await request.delete(`/api/specs/${encodeURIComponent(name)}`);
    });
  });
}
