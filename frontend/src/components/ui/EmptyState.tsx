import type { ReactNode } from "react";

export interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

/**
 * Placeholder for a list/section with nothing in it yet -- consolidates
 * the various one-off ".empty-state" / "no X yet" paragraphs scattered
 * across pages into one component with a consistent structure (icon,
 * heading, optional description, optional call-to-action).
 *
 * Usage:
 *   <EmptyState title="No reminders yet" description="Upload a prescription to get started."
 *     action={<Button onClick={() => navigate("/upload")}>Upload prescription</Button>} />
 */
export default function EmptyState({ icon, title, description, action, className = "" }: EmptyStateProps) {
  return (
    <div className={["ui-empty-state", className].filter(Boolean).join(" ")}>
      {icon && (
        <div className="ui-empty-state__icon" aria-hidden="true">
          {icon}
        </div>
      )}
      <p className="ui-empty-state__title">{title}</p>
      {description && <p className="ui-empty-state__description">{description}</p>}
      {action && <div className="ui-empty-state__action">{action}</div>}
    </div>
  );
}
