import { describe, expect, it } from "vite-plus/test";

import { parseRoute, routePath } from "./route.ts";

const id = "ab".repeat(32);

describe("routes", () => {
  it("reads each screen from its path and writes it back", () => {
    for (const path of ["/", `/d/${id}`, `/d/${id}/spec`]) {
      expect(routePath(parseRoute(path))).toBe(path);
    }
  });

  it("shows the documents for anything else", () => {
    for (const path of ["/d/nothash", `/d/${id}/other`, `/d/${id}/spec/more`, "/x", ""]) {
      expect(parseRoute(path)).toEqual({ screen: "documents" });
    }
  });
});
