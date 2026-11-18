// Pictures of every screen, in both themes and at two widths, for a person to look at. They
// are taken only when JANUS_SHOTS names a directory.
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { ready, spec } from "./examples.ts";
import { write } from "./steps.ts";

const OUT = process.env["JANUS_SHOTS"];

test.skip(OUT === undefined, "JANUS_SHOTS is not set");

for (const theme of ["light", "dark"] as const) {
  for (const width of [1280, 900]) {
    test.describe(`${theme}, ${width} wide`, () => {
      test.use({ colorScheme: theme, viewport: { width, height: 800 } });
      const shot = async (page: Page, name: string) => {
        mkdirSync(OUT!, { recursive: true });
        await page.screenshot({ path: join(OUT!, `${name}-${theme}-${width}.png`) });
      };

      test("every screen", async ({ page, request }) => {
        const invoice = await ready(request, "invoice");
        const parts = await ready(request, "parts-list");
        await request.put("/api/specs/Invoice", { data: { text: spec("invoice") } });

        await page.goto("/");
        await expect(page.getByRole("row", { name: /invoice\.pdf/ })).toContainText("Ready");
        await page
          .locator('input[type="file"]')
          .setInputFiles([
            { name: "notes.pdf", mimeType: "application/pdf", buffer: Buffer.from("a list") },
          ]);
        await expect(page.getByTestId("upload-failure")).toBeVisible();
        await shot(page, "documents");

        await page.goto(`/d/${parts}`);
        const side = page.getByRole("region", { name: "What Janus read" });
        const find = side.getByRole("searchbox", { name: "Find a phrase" });
        await find.fill("Bearing");
        await expect(side.locator(".find-status")).toContainText(/place/);
        await side.getByRole("checkbox", { name: "Table cells" }).check();
        const listbox = page.getByRole("listbox", { name: /^Page 1, / });
        await listbox.focus();
        await page.keyboard.press("ArrowRight");
        await expect(page.locator('[data-page="1"] img')).toHaveAttribute("data-loaded", "true");
        await shot(page, "inspect");

        await page.route("**/inspect?find=fail*", (route) => route.abort("connectionrefused"));
        await find.fill("fail");
        await expect(side.getByTestId("find-error")).toBeVisible();
        await shot(page, "inspect-search-failed");

        await page.route("**/image*", (route) => route.fulfill({ status: 500, json: {} }));
        await page.goto(`/d/${invoice}`);
        await expect(page.getByRole("button", { name: "Load Page 1 again" })).toBeVisible();
        await shot(page, "inspect-image-failed");
        await page.unroute("**/image*");

        await page.keyboard.press("?");
        await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
        await shot(page, "help");
        await page.keyboard.press("Escape");

        await page.goto(`/d/${invoice}/spec`);
        await write(page, spec("invoice"));
        const results = page.getByRole("region", { name: "Results" });
        await expect(results).toContainText("8 fields extracted");
        await results.locator(".fieldrow").nth(2).click();
        await expect(page.locator('[data-page="1"] img')).toHaveAttribute("data-loaded", "true");
        await shot(page, "spec-editor");

        await results.locator(".records-wrap").first().scrollIntoViewIfNeeded();
        await shot(page, "spec-editor-records");

        await write(page, `${spec("invoice")}\n  nonsense: [`);
        await expect(page.getByTestId("spec-problem")).toBeVisible();
        await shot(page, "spec-editor-problem");

        await page.route("**/extract", (route) => route.abort("connectionrefused"));
        await write(page, spec("invoice").replace("Invoice", "Invoice "));
        await expect(page.getByTestId("run-failure")).toBeVisible();
        await shot(page, "spec-editor-run-failed");
        await page.unroute("**/extract");

        await page.getByRole("button", { name: "Saved specs" }).click();
        const dialog = page.getByRole("dialog", { name: "Saved specs" });
        await dialog.getByRole("button", { name: "Delete Invoice" }).click();
        await shot(page, "saved-specs");
      });
    });
  }
}
