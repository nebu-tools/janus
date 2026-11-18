// A modal dialog: the browser's own <dialog>. Escape closes it, focus stays inside it while it
// is open, and focus returns to the control that opened it.
import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";

interface Props {
  title: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}

export function Dialog({ title, open, onClose, children }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  const heading = useId();

  useEffect(() => {
    const element = dialog.current;
    if (!element || !open) return;
    opener.current = document.activeElement;
    element.showModal();
    return () => {
      element.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) {
        opener.current.focus();
      }
    };
  }, [open]);

  if (!open) return null;
  return (
    <dialog
      ref={dialog}
      className="dialog"
      aria-labelledby={heading}
      onClose={onClose}
      onClick={(event) => {
        // A click on the backdrop lands on the dialog element itself.
        if (event.target === dialog.current) onClose();
      }}
    >
      <div className="dialog-head">
        <h2 id={heading}>{title}</h2>
        <button type="button" className="button" onClick={onClose}>
          Close
        </button>
      </div>
      <div className="dialog-body">{children}</div>
    </dialog>
  );
}
