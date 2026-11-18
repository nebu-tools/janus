// Moving between screens with the History API. Links are real links: they open in a new tab,
// and the browser's back button works.
import { createContext, use, useCallback, useEffect, useMemo, useState } from "react";
import type { AnchorHTMLAttributes, MouseEvent, ReactNode } from "react";

import { parseRoute, routePath } from "../lib/route.ts";
import type { Route } from "../lib/route.ts";

interface Nav {
  route: Route;
  go: (route: Route) => void;
}

const NavContext = createContext<Nav | null>(null);

export function NavProvider({ children }: { children: ReactNode }) {
  const [route, setRoute] = useState(() => parseRoute(window.location.pathname));
  useEffect(() => {
    const onPop = () => setRoute(parseRoute(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const go = useCallback((next: Route) => {
    window.history.pushState(null, "", routePath(next));
    setRoute(next);
  }, []);
  const nav = useMemo(() => ({ route, go }), [route, go]);
  return <NavContext value={nav}>{children}</NavContext>;
}

export function useNav(): Nav {
  const nav = use(NavContext);
  if (!nav) throw new Error("useNav needs a NavProvider above it");
  return nav;
}

type LinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & { to: Route };

export function Link({ to, onClick, ...rest }: LinkProps) {
  const { go } = useNav();
  const follow = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    go(to);
  };
  return <a {...rest} href={routePath(to)} onClick={follow} />;
}
