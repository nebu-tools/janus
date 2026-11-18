// How every screen shows a request that failed: an alert beside the control that asked, with
// the failure in words and, where asking again makes sense, the button that asks again.
import type { ReactNode } from "react";

interface Props {
  /** What failed, as a clause that the reason follows: "The list could not be loaded". */
  what: ReactNode;
  /** The reason, in the server's words or the client's. */
  why: string;
  /** Ask again. */
  again?: () => void;
  /** What the button that asks again says. */
  againLabel?: string;
  testId?: string;
}

export function Failure({ what, why, again, againLabel = "Try again", testId }: Props) {
  return (
    <div className="notice failure" role="alert" data-testid={testId}>
      <p>
        {what}
        {why === "" ? "." : `: ${why}`}
      </p>
      {again ? (
        <button type="button" className="button" onClick={again}>
          {againLabel}
        </button>
      ) : null}
    </div>
  );
}

/** The words that say what a dimmed, earlier answer on screen belongs to. */
export function Old({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <p className="old-label" data-testid={testId}>
      {children}
    </p>
  );
}
