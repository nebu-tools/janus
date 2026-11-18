import { expect, test } from "@playwright/test";

import { pdf } from "./examples.ts";

interface Row {
  id: string;
}

test("documents are added, read and removed", async ({ page, request }) => {
  const rows = (await (await request.get("/api/documents")).json()) as Row[];
  for (const row of rows) await request.delete(`/api/documents/${row.id}`);

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "No documents yet" })).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles([pdf("invoice"), pdf("parts-list")]);
  const invoice = page.getByRole("row", { name: /invoice\.pdf/ });
  const parts = page.getByRole("row", { name: /parts-list\.pdf/ });
  await expect(invoice).toContainText("Ready");
  await expect(parts).toContainText("Ready");
  // The name is the row's header. The cells after it are pages, tables and engine.
  await expect(parts.getByRole("cell").nth(0)).toHaveText("3");
  await expect(parts.getByRole("cell").nth(1)).toHaveText("3");
  await expect(parts.getByRole("cell").nth(2)).toHaveText("pymupdf");
  await expect(invoice.getByRole("cell").nth(0)).toHaveText("1");

  // The same file again is the same document.
  await page.locator('input[type="file"]').setInputFiles([pdf("invoice")]);
  await expect(page.getByRole("row", { name: /invoice\.pdf/ })).toHaveCount(1);

  await page.getByRole("button", { name: "Remove invoice.pdf" }).click();
  await expect(invoice).toHaveCount(0);
  await expect(parts).toBeVisible();

  await parts.getByRole("link", { name: "parts-list.pdf" }).click();
  await expect(page).toHaveURL(/\/d\/[0-9a-f]{64}$/);
  await expect(page.getByRole("group", { name: "Pages" })).toBeVisible();
});

test("a file that is not a PDF is refused with the reason", async ({ page }) => {
  await page.goto("/");
  await page
    .locator('input[type="file"]')
    .setInputFiles([
      { name: "notes.pdf", mimeType: "application/pdf", buffer: Buffer.from("a shopping list") },
    ]);
  await expect(page.getByRole("alert")).toContainText(
    "the file is not a PDF: it does not start with %PDF-",
  );
  await expect(page.getByRole("row", { name: /notes\.pdf/ })).toHaveCount(0);
});
