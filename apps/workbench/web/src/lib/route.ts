// The workbench's three places, as paths. New screens add a case here.

export type Route =
  | { screen: "documents" }
  | { screen: "inspect"; document: string }
  | { screen: "spec"; document: string };

const HASH = /^[0-9a-f]{64}$/;

export function parseRoute(path: string): Route {
  const [, d, document, tail, ...rest] = path.split("/");
  if (d === "d" && document !== undefined && HASH.test(document) && rest.length === 0) {
    if (tail === undefined || tail === "") return { screen: "inspect", document };
    if (tail === "spec") return { screen: "spec", document };
  }
  return { screen: "documents" };
}

export function routePath(route: Route): string {
  if (route.screen === "inspect") return `/d/${route.document}`;
  if (route.screen === "spec") return `/d/${route.document}/spec`;
  return "/";
}
