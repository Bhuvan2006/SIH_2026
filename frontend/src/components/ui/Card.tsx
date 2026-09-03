import type { HTMLAttributes, ReactNode } from "react";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  title?: string;
  footer?: ReactNode;
  children: ReactNode;
}

/**
 * Generic bordered container used for grouping content (the app's
 * `.action-card` / `.prescription-card` / `.review-panel` pattern,
 * consolidated into one component instead of near-duplicate CSS per page).
 *
 * Usage:
 *   <Card title="Today's reminders">{list}</Card>
 *   <Card footer={<Button onClick={confirm}>Confirm</Button>}>{form}</Card>
 */
export default function Card({ title, footer, children, className = "", ...rest }: CardProps) {
  return (
    <div className={["ui-card", className].filter(Boolean).join(" ")} {...rest}>
      {title && <h3 className="ui-card__title">{title}</h3>}
      <div className="ui-card__body">{children}</div>
      {footer && <div className="ui-card__footer">{footer}</div>}
    </div>
  );
}
