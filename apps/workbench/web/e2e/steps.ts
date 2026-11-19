// Steps the browser tests share: typing a spec, moving with Tab, and making a request fail.
import { expect } from "@playwright/test";
import type { Locator, Page, Request } from "@playwright/test";

/** Replace the text of the spec editor. The first character is typed over the selection and
 * the rest is pasted, so the text is never blank on the way: a blank text clears the results. */
export const write = async (page: Page, text: string) => {
  const editor = page.getByRole("textbox", { name: "Spec, in YAML" });
  await editor.click();
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.type(text.slice(0, 1));
  await page.keyboard.insertText(text.slice(1));
};

/** Press Tab, or Shift and Tab, until `target` has focus. */
export const tabTo = async (page: Page, target: Locator, back = false) => {
  for (let i = 0; i < 80; i++) {
    if (await target.evaluate((element) => element === document.activeElement)) return;
    await page.keyboard.press(back ? "Shift+Tab" : "Tab");
  }
  await expect(target).toBeFocused();
};

/** What the screen's live region says. */
export const announcer = (page: Page) => page.getByTestId("announcer");

// Every way a request can fail: each error status, a server that never answers, and a server
// that is gone.
export const FAILURES = [400, 403, 404, 409, 413, 422, 500, "late", "gone"] as const;
export type Failure = (typeof FAILURES)[number];

/** The words the client shows for a failure. `seconds` is the deadline of the request. */
export const said = (failure: Failure, seconds = 30) =>
  typeof failure === "number"
    ? `refused with ${failure}`
    : failure === "gone"
      ? "the server did not answer"
      : `the server did not answer in ${seconds} seconds`;

export interface Broken {
  /** Wait until the failure is there to be shown. For a request that never answers, this
   * passes its deadline. */
  shown(seconds?: number): Promise<void>;
  /** Let the requests through again. */
  mend(): Promise<void>;
}

/**
 * Make every request that `which` picks fail the way `failure` names. Call it before the page
 * is opened when the failure is "late": the page's clock is taken over then.
 */
export const breakRequests = async (
  page: Page,
  failure: Failure,
  which: (request: Request, path: string) => boolean,
): Promise<Broken> => {
  let asked = 0;
  let passed = 0;
  if (failure === "late") await page.clock.install();
  const handler = async (route: Parameters<Parameters<Page["route"]>[1]>[0]) => {
    const request = route.request();
    if (!which(request, new URL(request.url()).pathname)) return route.fallback();
    asked++;
    if (typeof failure === "number") {
      return route.fulfill({ status: failure, json: { detail: `refused with ${failure}` } });
    }
    if (failure === "gone") return route.abort("connectionrefused");
    // "late": the request is never answered.
  };
  await page.route("**/api/**", handler);
  return {
    async shown(seconds = 30) {
      await expect.poll(() => asked).toBeGreaterThan(passed);
      passed = asked;
      if (failure === "late") await page.clock.fastForward((seconds + 1) * 1000);
    },
    mend: () => page.unroute("**/api/**", handler),
  };
};

export const opacity = (locator: Locator) =>
  locator.evaluate((element) => Number(getComputedStyle(element).opacity));
