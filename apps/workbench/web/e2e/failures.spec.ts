// The failure rule, on every screen: a request that fails says so beside the control that made
// it, in an alert, and what is still on screen from before is dimmed and labelled as old.
// Each request of each screen fails here in every way a request can.
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { pdf, ready } from "./examples.ts";
import { breakRequests, FAILURES, opacity, said, write } from "./steps.ts";

const NOT_A_PDF = {
  name: "notes.pdf",
  mimeType: "application/pdf",
  buffer: Buffer.from("a shopping list"),
};
const ONE_FIELD = (name: string) => `name: ${name}\nfields:\n  number: { label: Invoice No. }\n`;

const saved = (page: Page) => page.getByRole("dialog", { name: "Saved specs" });

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

for (const failure of FAILURES) {
  test.describe(`a request that fails with ${failure}`, () => {
    test("Documents: the list, first and later", async ({ page, request }) => {
      await ready(request, "invoice");
      const broken = await breakRequests(
        page,
        failure,
        (r, path) => r.method() === "GET" && path === "/api/documents",
      );
      await page.goto("/");
      await broken.shown();
      const alert = page.getByTestId("list-failure");
      await expect(alert).toHaveRole("alert");
      await expect(alert.locator("p")).toHaveText(`The list could not be loaded: ${said(failure)}`);
      await expect(page.getByText("Loading the list.")).toHaveCount(0);
      await expect(page.getByRole("table")).toHaveCount(0);

      // Asking again, once the server answers, shows the list and ends the alert.
      await broken.mend();
      await alert.getByRole("button", { name: "Try again" }).click();
      const table = page.getByRole("table");
      await expect(table).toContainText("invoice.pdf");
      await expect(alert).toHaveCount(0);
      await expect(table).toHaveAttribute("data-stale", "false");

      // A later failure: the rows stay, dimmed, and are called old.
      const again = await breakRequests(
        page,
        failure,
        (r, path) => r.method() === "GET" && path === "/api/documents",
      );
      await page.locator('input[type="file"]').setInputFiles([NOT_A_PDF]);
      await again.shown();
      await expect(alert.locator("p")).toHaveText(`The list could not be loaded: ${said(failure)}`);
      await expect(table).toHaveAttribute("data-stale", "true");
      expect(await opacity(table)).toBeLessThan(0.8);
      await expect(page.getByTestId("old-list")).toHaveText(
        "This list is from before the failure.",
      );
      await expect(table).toContainText("invoice.pdf");
    });

    test("Documents: an upload", async ({ page, request }) => {
      await ready(request, "invoice");
      const broken = await breakRequests(page, failure, (r) => r.method() === "POST");
      await page.goto("/");
      await expect(page.getByRole("table")).toContainText("invoice.pdf");
      await page.locator('input[type="file"]').setInputFiles([pdf("parts-list")]);
      await broken.shown(300);
      const alert = page.getByTestId("upload-failure");
      await expect(alert).toHaveRole("alert");
      await expect(alert).toHaveText(`parts-list.pdf was not added: ${said(failure, 300)}`);
      await expect(page.getByText(/^Sending/)).toHaveCount(0);
      // The list itself was loaded again and is current.
      await expect(page.getByRole("table")).toHaveAttribute("data-stale", "false");
      await expect(page.getByTestId("old-list")).toHaveCount(0);
    });

    test("Documents: removing a document", async ({ page, request }) => {
      await ready(request, "invoice");
      const broken = await breakRequests(page, failure, (r) => r.method() === "DELETE");
      await page.goto("/");
      const row = page.getByRole("row", { name: /invoice\.pdf/ });
      await row.getByRole("button", { name: "Remove invoice.pdf" }).click();
      await broken.shown();
      await expect(row.getByRole("alert")).toHaveText(`Not removed: ${said(failure)}`);
      await expect(row).toContainText("Ready");

      await broken.mend();
      await row.getByRole("button", { name: "Remove invoice.pdf" }).click();
      await expect(row).toHaveCount(0);
    });

    test("opening a document", async ({ page, request }) => {
      const id = await ready(request, "invoice");
      const broken = await breakRequests(
        page,
        failure,
        (r, path) => r.method() === "GET" && path === "/api/documents",
      );
      await page.goto(`/d/${id}`);
      await broken.shown();
      const alert = page.getByTestId("document-failure");
      await expect(alert).toHaveRole("alert");
      await expect(alert.locator("p")).toHaveText(
        `The list of documents could not be loaded: ${said(failure)}`,
      );
      await broken.mend();
      await alert.getByRole("button", { name: "Try again" }).click();
      await expect(page.getByRole("region", { name: "What Janus read" })).toBeVisible();
    });

    // The tables of the Inspect screen come with the inspection: they have no request of
    // their own, so this is their failure too.
    test("Inspect: the inspection, with its tables", async ({ page, request }) => {
      const id = await ready(request, "parts-list");
      const broken = await breakRequests(
        page,
        failure,
        (r, path) => path.endsWith("/inspect") && !r.url().includes("find="),
      );
      await page.goto(`/d/${id}`);
      await broken.shown();
      const alert = page.getByTestId("inspection-failure");
      await expect(alert).toHaveRole("alert");
      await expect(alert.locator("p")).toHaveText(
        `This document could not be opened: ${said(failure)}`,
      );
      await expect(page.getByText("Opening the document.")).toHaveCount(0);

      await broken.mend();
      await alert.getByRole("button", { name: "Try again" }).click();
      const side = page.getByRole("region", { name: "What Janus read" });
      await expect(side).toContainText("3 pages, 3 tables");
      await expect(side.getByRole("button", { name: /p1t0/ })).toBeVisible();
      await expect(alert).toHaveCount(0);
    });

    test("Inspect: a page image", async ({ page, request }) => {
      const id = await ready(request, "invoice");
      const broken = await breakRequests(page, failure, (_, path) => path.endsWith("/image"));
      await page.goto(`/d/${id}`);
      await broken.shown();
      const slot = page.locator('.scroller-page[data-page="1"]');
      const alert = slot.getByRole("alert");
      // The image has its own deadline, and says so in its own words.
      const why = failure === "late" ? "it did not load in 30 seconds" : said(failure);
      await expect(alert.locator("p")).toHaveText(`Page 1 could not be shown: ${why}`);
      await expect(slot.locator("img")).toHaveCount(0);
      // What Janus read on the page is still drawn and can still be reached.
      await expect(slot.getByRole("listbox")).toBeVisible();

      await broken.mend();
      await alert.getByRole("button", { name: "Load Page 1 again" }).click();
      await expect(slot.getByRole("img", { name: "Page 1" })).toHaveAttribute(
        "data-loaded",
        "true",
      );
      await expect(alert).toHaveCount(0);
    });

    test("Inspect: the layers of a page", async ({ page, request }) => {
      const id = await ready(request, "invoice");
      const broken = await breakRequests(page, failure, (_, path) => /\/pages\/\d+$/.test(path));
      await page.goto(`/d/${id}`);
      await broken.shown();
      const side = page.getByRole("region", { name: "What Janus read" });
      const alert = side.getByTestId("layout-failure");
      await expect(alert).toHaveRole("alert");
      await expect(alert.locator("p")).toHaveText(
        `The boxes of page 1 could not be loaded: ${said(failure)}`,
      );
      await side.getByRole("checkbox", { name: "Words" }).check();
      await expect(page.locator('[data-box^="word:"]')).toHaveCount(0);

      await broken.mend();
      await alert.getByRole("button", { name: "Load them again" }).click();
      await expect(page.locator('[data-box^="word:"]').first()).toBeVisible();
      await expect(alert).toHaveCount(0);
    });

    test("Inspect: a search, first and later", async ({ page, request }) => {
      const id = await ready(request, "invoice");
      // A phrase that starts with "fail" fails. Every other phrase reaches the server.
      const broken = await breakRequests(page, failure, (r) => r.url().includes("find=fail"));
      await page.goto(`/d/${id}`);
      const side = page.getByRole("region", { name: "What Janus read" });
      const box = side.getByRole("searchbox", { name: "Find a phrase" });
      const status = side.locator(".find-status");
      const alert = side.getByTestId("find-error");
      const hits = side.locator(".hits");

      // The first search fails: the alert, no "Searching", no hits.
      await box.fill("fail one");
      await broken.shown();
      await expect(alert).toHaveRole("alert");
      await expect(alert.locator("p")).toHaveText(
        `The search for "fail one" failed: ${said(failure)}`,
      );
      await expect(status).toHaveText("");
      await expect(hits).toHaveCount(0);
      await expect(page.locator('[data-box^="hit"]')).toHaveCount(0);

      // A search that answers clears the error.
      await box.fill("Total");
      await expect(status).toContainText("2 places");
      await expect(alert).toHaveCount(0);
      await expect(hits).toHaveAttribute("data-stale", "false");

      // A later search fails: the hits of "Total" stay, dimmed and named, and count as old.
      await box.fill("fail two");
      await broken.shown();
      await expect(alert.locator("p")).toHaveText(
        `The search for "fail two" failed: ${said(failure)}`,
      );
      await expect(status).toHaveText("");
      await expect(hits).toHaveAttribute("data-stale", "true");
      expect(await opacity(hits)).toBeLessThan(0.8);
      await expect(side.getByTestId("old-hits")).toHaveText(
        '2 places for the earlier phrase "Total".',
      );
      await expect(page.locator('[data-box^="hit"]')).toHaveCount(2);
      await expect(page.locator('[data-box^="hit"][data-old]')).toHaveCount(2);

      await box.fill("Invoice");
      await expect(hits).toContainText("INVOICE");
      await expect(alert).toHaveCount(0);
      await expect(hits).toHaveAttribute("data-stale", "false");
      await expect(page.locator('[data-box^="hit"][data-old]')).toHaveCount(0);
    });

    test("Spec editor: the pages", async ({ page, request }) => {
      const id = await ready(request, "invoice");
      const broken = await breakRequests(page, failure, (_, path) => path.endsWith("/inspect"));
      await page.goto(`/d/${id}/spec`);
      await broken.shown();
      const alert = page.getByTestId("pages-failure");
      await expect(alert).toHaveRole("alert");
      await expect(alert.locator("p")).toHaveText(
        `The pages could not be loaded: ${said(failure)}`,
      );
      await broken.mend();
      await alert.getByRole("button", { name: "Try again" }).click();
      await expect(page.locator('.scroller-page[data-page="1"] img')).toBeVisible();
      await expect(alert).toHaveCount(0);
    });

    test("Spec editor: a run, first and later", async ({ page, request }) => {
      const id = await ready(request, "invoice");
      const broken = await breakRequests(
        page,
        failure,
        (r) => r.method() === "POST" && (r.postData() ?? "").includes("refused"),
      );
      await page.goto(`/d/${id}/spec`);
      const results = page.getByRole("region", { name: "Results" });
      const list = results.locator(".fields");
      const alert = page.getByTestId("run-failure");

      // The first run fails: the alert, no "Running", nothing listed.
      await write(page, ONE_FIELD("refused"));
      await broken.shown();
      await expect(alert).toHaveRole("alert");
      await expect(alert.locator("p")).toHaveText(`The spec could not be run: ${said(failure)}`);
      await expect(results).not.toContainText("Running.");
      await expect(list.locator(".fieldrow")).toHaveCount(0);
      await expect(page.getByTestId("old-results")).toHaveCount(0);

      await write(page, ONE_FIELD("first"));
      await expect(results).toContainText("1 field extracted");
      await expect(alert).toHaveCount(0);

      // A later run fails: the results and their boxes stay, dimmed, and are called old.
      await write(page, ONE_FIELD("refused again"));
      await broken.shown();
      await expect(alert.locator("p")).toHaveText(`The spec could not be run: ${said(failure)}`);
      await expect(list).toHaveAttribute("data-stale", "true");
      expect(await opacity(list)).toBeLessThan(0.8);
      await expect(page.getByTestId("old-results")).toHaveText(
        "These results are for the earlier text.",
      );
      await expect(results).not.toContainText("field extracted");
      await expect(page.locator("[data-box][data-old]")).toHaveCount(1);

      // The same text, run again once the server answers.
      await broken.mend();
      await alert.getByRole("button", { name: "Run again" }).click();
      await expect(results).toContainText("1 field extracted");
      await expect(alert).toHaveCount(0);
      await expect(list).toHaveAttribute("data-stale", "false");
      await expect(page.locator("[data-box][data-old]")).toHaveCount(0);
    });

    test("Spec editor: saving", async ({ page, request }) => {
      const id = await ready(request, "invoice");
      const name = `Matrix save ${failure}`;
      const broken = await breakRequests(page, failure, (r) => r.method() === "PUT");
      await page.goto(`/d/${id}/spec`);
      await write(page, ONE_FIELD("to save"));
      await page.getByRole("textbox", { name: "Spec name" }).fill(name);
      const save = page.getByRole("button", { name: "Save", exact: true });
      await save.click();
      await broken.shown();
      const alert = page.getByTestId("save-failure");
      await expect(alert).toHaveRole("alert");
      await expect(alert).toHaveText(`Not saved: ${said(failure)}`);
      await expect(page.locator(".spec-foot")).not.toContainText("Saved");
      await expect(page.getByRole("textbox", { name: "Spec, in YAML" })).toContainText("to save");

      await broken.mend();
      await save.click();
      await expect(page.locator(".spec-foot")).toHaveText(`Saved as ${name}`);
      await expect(alert).toHaveCount(0);
      await request.delete(`/api/specs/${encodeURIComponent(name)}`);
    });

    test("Spec editor: the saved specs, first and later", async ({ page, request }) => {
      const id = await ready(request, "invoice");
      const name = `Matrix list ${failure}`;
      await request.put(`/api/specs/${encodeURIComponent(name)}`, {
        data: { text: ONE_FIELD("listed") },
      });
      const which = (r: { method(): string }, path: string) =>
        r.method() === "GET" && path === "/api/specs";
      const broken = await breakRequests(page, failure, which);
      await page.goto(`/d/${id}/spec`);
      await broken.shown();
      await page.getByRole("button", { name: "Saved specs" }).click();
      const alert = saved(page).getByTestId("specs-failure");
      await expect(alert).toHaveRole("alert");
      await expect(alert.locator("p")).toHaveText(
        `The saved specs could not be loaded: ${said(failure)}`,
      );
      await expect(saved(page).getByText("Loading the saved specs.")).toHaveCount(0);
      await expect(saved(page).getByRole("listitem")).toHaveCount(0);

      await broken.mend();
      await alert.getByRole("button", { name: "Try again" }).click();
      await expect(saved(page).getByRole("button", { name: `Open ${name}` })).toBeVisible();
      await expect(alert).toHaveCount(0);

      // A later failure: saving asks for the list again. What is listed stays, dimmed and old.
      await page.keyboard.press("Escape");
      const again = await breakRequests(page, failure, which);
      await write(page, ONE_FIELD("another"));
      await page.getByRole("textbox", { name: "Spec name" }).fill(`${name} too`);
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await again.shown();
      await page.getByRole("button", { name: "Saved specs" }).click();
      await expect(alert.locator("p")).toHaveText(
        `The saved specs could not be loaded: ${said(failure)}`,
      );
      const list = saved(page).getByRole("list", { name: "Saved specs" });
      await expect(list).toHaveAttribute("data-stale", "true");
      expect(await opacity(list)).toBeLessThan(0.8);
      await expect(saved(page).getByTestId("old-specs")).toHaveText(
        "This list is from before the failure.",
      );
      await request.delete(`/api/specs/${encodeURIComponent(name)}`);
      await request.delete(`/api/specs/${encodeURIComponent(`${name} too`)}`);
    });

    test("Spec editor: opening a saved spec", async ({ page, request }) => {
      const id = await ready(request, "invoice");
      const name = `Matrix open ${failure}`;
      const path = `/api/specs/${encodeURIComponent(name)}`;
      await request.put(path, { data: { text: ONE_FIELD("opened") } });
      const broken = await breakRequests(
        page,
        failure,
        (r, at) => r.method() === "GET" && at.startsWith("/api/specs/"),
      );
      await page.goto(`/d/${id}/spec`);
      await write(page, ONE_FIELD("mine"));
      await page.getByRole("button", { name: "Saved specs" }).click();
      const open = saved(page).getByRole("button", { name: `Open ${name}` });
      await open.click();
      await broken.shown();
      const row = saved(page).getByRole("listitem").filter({ hasText: name });
      await expect(row.getByRole("alert")).toHaveText(`Not opened: ${said(failure)}`);
      // The dialog stays, and the text in the editor is the text that was there.
      await expect(saved(page)).toBeVisible();
      await expect(page.getByRole("textbox", { name: "Spec, in YAML" })).toContainText("mine");

      await broken.mend();
      await open.click();
      await expect(saved(page)).toHaveCount(0);
      await expect(page.getByRole("textbox", { name: "Spec, in YAML" })).toContainText("opened");
      await request.delete(path);
    });

    test("Spec editor: deleting a saved spec", async ({ page, request }) => {
      const id = await ready(request, "invoice");
      const name = `Matrix delete ${failure}`;
      await request.put(`/api/specs/${encodeURIComponent(name)}`, {
        data: { text: ONE_FIELD("deleted") },
      });
      const broken = await breakRequests(page, failure, (r) => r.method() === "DELETE");
      await page.goto(`/d/${id}/spec`);
      await page.getByRole("button", { name: "Saved specs" }).click();
      await saved(page)
        .getByRole("button", { name: `Delete ${name}` })
        .click();
      const yes = saved(page).getByRole("button", { name: `Yes, delete ${name}` });
      await yes.click();
      await broken.shown();
      const row = saved(page).getByRole("listitem").filter({ hasText: name });
      await expect(row.getByRole("alert")).toHaveText(`Not deleted: ${said(failure)}`);
      await expect(row).toBeVisible();

      await broken.mend();
      await yes.click();
      await expect(row).toHaveCount(0);
    });
  });
}
