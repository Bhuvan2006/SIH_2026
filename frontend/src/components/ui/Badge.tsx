import type { ReactNode } from "react";

export type BadgeVariant = "neutral" | "primary" | "success" | "warning" | "danger";

export interface BadgeProps {
  variant?: BadgeVariant;
  children: ReactNode;
  /** Optional title attribute -- used e.g. to show a citation's full source text on hover/focus. */
  title?: string;
  className?: string;
}

/**
 * Small inline pill for statuses, tags, and citation labels.
 * Purely presentational (no role) -- the visible text IS the content, so
 * no extra ARIA is needed; wrap in a <button> at the call site if a badge
 * needs to be interactive.
 *
 * Usage:
 *   <Badge variant="success">Confirmed</Badge>
 *   <Badge variant="primary" title={citation.label}>📎 {citation.label}</Badge>
 */
export default function Badge({ variant = "neutral", children, title, className = "" }: BadgeProps) {
  return (
    <span className={["ui-badge", `ui-badge--${variant}`, className].filter(Boolean).join(" ")} title={title}>
      {children}
    </span>
  );
}
