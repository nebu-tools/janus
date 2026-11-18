// What a screen says to a screen reader: one polite live region, and the function that fills
// it. A screen speaks when something a person asked for has ended: a jump reached its page, a
// search has its hits, a run has its outcome. It never speaks while the pages scroll.
import { createContext, use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

type Announce = (text: string) => void;

const AnnounceContext = createContext<Announce | null>(null);

/** Holds the screen's live region. Mount one for each screen. */
export function Announcer({ children }: { children: ReactNode }) {
  const [text, setText] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  // The region is emptied first, so the same words said twice are read twice.
  const announce = useCallback((next: string) => {
    clearTimeout(timer.current);
    setText("");
    timer.current = setTimeout(() => setText(next), 60);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);
  const value = useMemo(() => announce, [announce]);
  return (
    <AnnounceContext value={value}>
      {children}
      <div className="visually-hidden" role="status" aria-live="polite" data-testid="announcer">
        {text}
      </div>
    </AnnounceContext>
  );
}

export function useAnnounce(): Announce {
  const announce = use(AnnounceContext);
  if (!announce) throw new Error("useAnnounce needs an Announcer above it");
  return announce;
}
