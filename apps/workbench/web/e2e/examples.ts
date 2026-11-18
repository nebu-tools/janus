// The example documents of this repository, and how a test puts one on the server.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { APIRequestContext } from "@playwright/test";

const EXAMPLES = join(import.meta.dirname, "..", "..", "..", "..", "examples");

export type Example = "invoice" | "purchase-order" | "parts-list";

export const pdf = (example: Example) => ({
  name: `${example}.pdf`,
  mimeType: "application/pdf",
  buffer: readFileSync(join(EXAMPLES, example, "document.pdf")),
});

export const spec = (example: Example) =>
  readFileSync(join(EXAMPLES, example, "spec.yaml"), "utf8");

interface Row {
  id: string;
  status: string;
}

/** Send the example and wait until it is read. Sending it again gives the same document. */
export const ready = async (request: APIRequestContext, example: Example): Promise<string> => {
  const file = pdf(example);
  const sent = await request.post(`/api/documents?name=${file.name}`, {
    headers: { "content-type": "application/pdf" },
    data: file.buffer,
  });
  const { id } = (await sent.json()) as Row;
  for (let i = 0; i < 200; i++) {
    const rows = (await (await request.get("/api/documents")).json()) as Row[];
    const row = rows.find((r) => r.id === id);
    if (row?.status === "ready") return id;
    if (row?.status === "failed") throw new Error(`${example} could not be read`);
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`${example} was not read in time`);
};
