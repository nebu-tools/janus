// Calls to the workbench server. Types come from the server's OpenAPI document.
import type {
  DocumentRow,
  ExtractOut,
  Inspection,
  PageLayout,
  SpecOut,
  SpecRow,
} from "./JanusApi.gen.ts";

export type {
  Box,
  DocumentRow,
  ExtractOut,
  FieldOut,
  Heading,
  Hit,
  Inspection,
  PageLayout,
  PageSummary,
  SpecRow,
  TableSummary,
} from "./JanusApi.gen.ts";

/** The server said no, in its own words. */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function failure(response: Response): Promise<ApiError> {
  let message = `the server answered ${response.status}`;
  try {
    const body: unknown = await response.json();
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") message = detail;
    else if (Array.isArray(detail)) {
      message = detail.map((d: { msg?: unknown }) => String(d.msg ?? "")).join("; ");
    }
  } catch {
    // The body was not JSON; the status says enough.
  }
  return new ApiError(response.status, message);
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) throw await failure(response);
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

const json = (method: string, body: unknown, signal?: AbortSignal): RequestInit => ({
  method,
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
  ...(signal ? { signal } : {}),
});

const doc = (document: string) => `/api/documents/${document}`;
const spec = (name: string) => `/api/specs/${encodeURIComponent(name)}`;

export const api = {
  documents: (signal?: AbortSignal) =>
    call<DocumentRow[]>("/api/documents", signal ? { signal } : {}),
  addDocument: (file: File) =>
    call<DocumentRow>(`/api/documents?name=${encodeURIComponent(file.name.slice(0, 300))}`, {
      method: "POST",
      headers: { "content-type": "application/pdf" },
      body: file,
    }),
  deleteDocument: (document: string) => call<void>(doc(document), { method: "DELETE" }),
  inspect: (document: string, find?: string, signal?: AbortSignal) =>
    call<Inspection>(
      `${doc(document)}/inspect${find ? `?find=${encodeURIComponent(find)}` : ""}`,
      signal ? { signal } : {},
    ),
  pageLayout: (document: string, page: number) =>
    call<PageLayout>(`${doc(document)}/pages/${page}`),
  pageImage: (document: string, page: number) => `${doc(document)}/pages/${page}/image?scale=2`,
  extract: (document: string, text: string, signal?: AbortSignal) =>
    call<ExtractOut>(`${doc(document)}/extract`, json("POST", { spec: text }, signal)),
  specs: () => call<SpecRow[]>("/api/specs"),
  spec: (name: string) => call<SpecOut>(spec(name)),
  saveSpec: (name: string, text: string) => call<SpecRow>(spec(name), json("PUT", { text })),
};

export const message = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);
