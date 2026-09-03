import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

export interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Rendered as the dialog's accessible name via aria-labelledby. */
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  /** Clicking the backdrop closes the modal. Defaults to true. */
  closeOnBackdropClick?: boolean;
}

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Accessible dialog rendered into a portal at document.body, so it isn't
 * clipped by an ancestor's overflow/z-index and sits above the whole app.
 *
 * Accessibility behavior (all load-bearing, not decorative):
 *   - role="dialog" + aria-modal="true" + aria-labelledby -> the title is
 *     announced as the dialog's name when it opens.
 *   - Focus moves into the dialog on open and is trapped there (Tab/Shift+Tab
 *     cycle within it) so keyboard users can't tab into the obscured page
 *     behind the backdrop.
 *   - Escape closes it; focus is restored to whatever element opened it,
 *     so keyboard/screen-reader users aren't dropped back at the top of
 *     the page.
 *   - Body scroll is locked while open, so the page behind the backdrop
 *     doesn't scroll independently of the visible dialog.
 *
 * Usage:
 *   const [open, setOpen] = useState(false);
 *   <Modal isOpen={open} onClose={() => setOpen(false)} title="Withdraw consent?"
 *     footer={<>
 *       <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
 *       <Button variant="danger" onClick={withdraw}>Withdraw</Button>
 *     </>}>
 *     <p>This stops Arogya from using this data going forward.</p>
 *   </Modal>
 */
export default function Modal({ isOpen, onClose, title, children, footer, closeOnBackdropClick = true }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = `modal-title-${title.replace(/\s+/g, "-").toLowerCase()}`;

  useEffect(() => {
    if (!isOpen) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    const firstFocusable = dialog?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
    (firstFocusable ?? dialog)?.focus();

    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab" || !dialog) return;

      const focusables = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (focusables.length === 0) {
        e.preventDefault();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];

      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = originalOverflow;
      previouslyFocused?.focus();
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return createPortal(
    <div
      className="ui-modal-backdrop"
      onMouseDown={(e) => {
        if (closeOnBackdropClick && e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="ui-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={dialogRef}
        tabIndex={-1}
      >
        <div className="ui-modal__header">
          <h2 className="ui-modal__title" id={titleId}>
            {title}
          </h2>
          <button type="button" className="ui-modal__close" onClick={onClose} aria-label="Close dialog">
            ×
          </button>
        </div>
        <div className="ui-modal__body">{children}</div>
        {footer && <div className="ui-modal__footer">{footer}</div>}
      </div>
    </div>,
    document.body
  );
}
