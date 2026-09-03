import type { ReactNode } from "react";

export type AlertVariant = "info" | "success" | "warning" | "danger" | "emergency";

export interface AlertProps {
  variant?: AlertVariant;
  /** Optional heading rendered above the message body. */
  title?: string;
  children: ReactNode;
  /** Called when present; renders a dismiss ("x") button. */
  onDismiss?: () => void;
  /** Accessible label for the dismiss button. Defaults to "Dismiss". */
  dismissLabel?: string;
  className?: string;
}

const ICONS: Record<AlertVariant, string> = {
  info: "ℹ️",
  success: "✅",
  warning: "⚠️",
  danger: "⛔",
  emergency: "🚨",
};

/**
 * Inline status/message banner. `warning`, `danger`, and `emergency` use
 * role="alert" (assertive live region -- interrupts and is announced
 * immediately, appropriate for the emergency-escalation and validation-
 * failure cases they're meant for); `info` and `success` use role="status"
 * (polite -- announced without interrupting whatever the user is doing).
 *
 * Usage:
 *   <Alert variant="info">{disclaimerText}</Alert>
 *   <Alert variant="emergency" title="Seek help now">{emergencyText}</Alert>
 *   <Alert variant="warning" onDismiss={() => setShow(false)}>Low-confidence scan — please review.</Alert>
 */
export default function Alert({
  variant = "info",
  title,
  children,
  onDismiss,
  dismissLabel = "Dismiss",
  className = "",
}: AlertProps) {
  const isUrgent = variant === "danger" || variant === "warning" || variant === "emergency";

  return (
    <div
      className={["ui-alert", `ui-alert--${variant}`, className].filter(Boolean).join(" ")}
      role={isUrgent ? "alert" : "status"}
    >
      <span className="ui-alert__icon" aria-hidden="true">
        {ICONS[variant]}
      </span>
      <div className="ui-alert__body">
        {title && <p className="ui-alert__title">{title}</p>}
        <div className="ui-alert__message">{children}</div>
      </div>
      {onDismiss && (
        <button type="button" className="ui-alert__dismiss" onClick={onDismiss} aria-label={dismissLabel}>
          ×
        </button>
      )}
    </div>
  );
}
