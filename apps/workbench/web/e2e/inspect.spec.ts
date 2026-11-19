import { expect, test } from "@playwright/test";

import { ready } from "./examples.ts";
import { opacity } from "./steps.ts";

test("the parts list shows its pages, tables and layers", async ({ page, request }) => {
  const id = await ready(request, "parts-list");
  await page.goto(`/d/${id}`);

  const side = page.getByRole("region", { name: "What Janus read" });
  await expect(side).toContainText("3 pages, 3 tables");
  await expect(side.getByRole("button", { name: /p1t0/ })).toBeVisible();
  await expect(side.locator(".tablecard").first()).toContainText("BR-1000");

  const first = page.locator('.scroller-page[data-page="1"]');
  await expect(first.locator("img")).toBeVisible();
  // Tables are drawn from the start. Words are drawn once their layer is switched on.
  await expect(first.locator('[data-box^="table"]')).toHaveCount(1);
  const before = await first.locator("[data-box]").count();
  await side.getByLabel("Words").check();
  await expect.poll(() => first.locator("[data-box]").count()).toBeGreaterThan(before + 100);
  await side.getByLabel("Words").uncheck();
  await expect(first.locator("[data-box]")).toHaveCount(before);

  // A table's card scrolls to the table.
  await side.getByRole("button", { name: /p3t0/ }).click();
  await expect(page.locator('.scroller-page[data-page="3"]')).toBeInViewport();
});

test("a phrase is found with where it is printed", async ({ page, request }) => {
  const id = await ready(request, "invoice");
  await page.goto(`/d/${id}`);

  const side = page.getByRole("region", { name: "What Janus read" });
  await side.getByRole("searchbox", { name: "Find a phrase" }).fill("Total due");
  await expect(side.locator(".find-status")).toContainText("1 place");
  const hit = side.locator(".hit");
  await expect(hit).toHaveCount(1);
  await expect(hit).toContainText("Total due: £391.20");
  await expect(hit).toContainText("begins its line");
  await expect(page.locator('[data-box^="hit"]')).toHaveCount(1);

  await side.getByRole("searchbox", { name: "Find a phrase" }).fill("due");
  await expect(side.locator(".find-status")).toContainText("places");
  await expect(side.locator(".hit").filter({ hasText: "inside a line" })).not.toHaveCount(0);

  await side.getByRole("searchbox", { name: "Find a phrase" }).fill("marmalade");
  await expect(side.locator(".find-status")).toContainText('Nothing prints "marmalade"');
});

test("hits of an earlier phrase are dimmed and named while the next search runs", async ({
  page,
  request,
}) => {
  const id = await ready(request, "invoice");
  let release = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/inspect?find=Invoice", async (route) => {
    await held;
    await route.continue();
  });
  await page.goto(`/d/${id}`);
  const side = page.getByRole("region", { name: "What Janus read" });
  const box = side.getByRole("searchbox", { name: "Find a phrase" });
  const hits = side.locator(".hits");
  const boxes = page.locator('[data-box^="hit"]');

  await box.fill("Total");
  await expect(side.locator(".find-status")).toContainText("2 places");
  await expect(hits).toHaveAttribute("data-stale", "false");
  await expect(boxes).toHaveCount(2);
  await expect(page.locator('[data-box^="hit"][data-old]')).toHaveCount(0);

  // At once, before the request is even sent: the hits on screen belong to "Total".
  await box.fill("Invoice");
  await expect(hits).toHaveAttribute("data-stale", "true");
  expect(await opacity(hits)).toBeLessThan(0.8);
  await expect(side.locator(".find-status")).toHaveText("Searching");
  await expect(side.getByTestId("old-hits")).toHaveText('2 places for the earlier phrase "Total".');
  await expect(page.locator('[data-box^="hit"][data-old]')).toHaveCount(2);
  expect(await opacity(boxes.first())).toBeLessThan(0.8);
  await boxes.first().hover();
  await expect(page.locator(".pageview-label")).toContainText('for the earlier phrase "Total"');
  await expect(hits).toContainText("Total due");

  release();
  await expect(hits).toHaveAttribute("data-stale", "false");
  await expect(hits).toContainText("INVOICE");
  await expect(side.getByTestId("old-hits")).toHaveCount(0);
  await expect(page.locator('[data-box^="hit"][data-old]')).toHaveCount(0);
  expect(await opacity(hits)).toBe(1);
});
