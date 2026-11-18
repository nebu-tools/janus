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

/** How long an answer may take, in ms. An upload may take longer. */
const DEADLINE = 30_000;
const UPLOAD_DEADLINE = 300_000;

// Every request ends: with an answer, with the server's refusal in its own words, or with a
// message that says the server is out of reach or did not answer in time.
const body = <T>(response: Response) =>
  response.status === 204 ? Promise.resolve(undefined as T) : (response.json() as Promise<T>);

async function call<T>(
  path: string,
  init: RequestInit = {},
  deadline = DEADLINE,
  read: (response: Response) => Promise<T> = body,
): Promise<T> {
  const late = new AbortController();
  const timer = setTimeout(() => late.abort(), deadline);
  const asked = init.signal ?? null;
  const signal = asked ? AbortSignal.any([asked, late.signal]) : late.signal;
  try {
    const response = await fetch(path, { ...init, signal });
    if (!response.ok) throw await failure(response);
    return await read(response);
  } catch (error) {
    // A refusal, and a request the caller stopped, stay what they are.
    if (error instanceof ApiError || asked?.aborted) throw error;
    if (late.signal.aborted) {
      throw new Error(`the server did not answer in ${deadline / 1000} seconds`, { cause: error });
    }
    throw new Error("the server did not answer", { cause: error });
  } finally {
    clearTimeout(timer);
  }
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
    call<DocumentRow>(
      `/api/documents?name=${encodeURIComponent(file.name)}`,
      { method: "POST", headers: { "content-type": "application/pdf" }, body: file },
      UPLOAD_DEADLINE,
    ),
  deleteDocument: (document: string) => call<void>(doc(document), { method: "DELETE" }),
  inspect: (document: string, find?: string, signal?: AbortSignal) =>
    call<Inspection>(
      `${doc(document)}/inspect${find ? `?find=${encodeURIComponent(find)}` : ""}`,
      signal ? { signal } : {},
    ),
  pageLayout: (document: string, page: number) =>
    call<PageLayout>(`${doc(document)}/pages/${page}`),
  /** Why a page image did not load: the request made again, for the words of its failure. */
  whyNot: (url: string) =>
    call(url, {}, DEADLINE, () => Promise.resolve("")).catch((error: unknown) => message(error)),
  pageImage: (document: string, page: number) => `${doc(document)}/pages/${page}/image?scale=2`,
  extract: (document: string, text: string, signal?: AbortSignal) =>
    call<ExtractOut>(`${doc(document)}/extract`, json("POST", { spec: text }, signal)),
  specs: (signal?: AbortSignal) => call<SpecRow[]>("/api/specs", signal ? { signal } : {}),
  spec: (name: string) => call<SpecOut>(spec(name)),
  deleteSpec: (name: string) => call<void>(spec(name), { method: "DELETE" }),
  saveSpec: (name: string, text: string) => call<SpecRow>(spec(name), json("PUT", { text })),
};

export const message = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);
