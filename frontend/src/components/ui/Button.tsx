import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";
import Spinner from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost" | "link";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  /** Visual style. Defaults to "primary". */
  variant?: ButtonVariant;
  /** Defaults to "md". */
  size?: ButtonSize;
  /**
   * Shows an inline spinner and marks the button aria-busy. The button
   * stays disabled while loading so it can't be double-submitted, but the
   * label stays visible (not swapped for a bare spinner) so screen reader
   * and sighted users alike still know what action is pending.
   */
  loading?: boolean;
  /** Optional icon rendered before the label. Hidden from AT via aria-hidden. */
  leftIcon?: ReactNode;
  /** Optional icon rendered after the label. Hidden from AT via aria-hidden. */
  rightIcon?: ReactNode;
  /** Stretches the button to the width of its container. */
  fullWidth?: boolean;
  children: ReactNode;
  ref?: Ref<HTMLButtonElement>;
}

/**
 * Base button used across the app for every clickable action. Native
 * <button> semantics are preserved (keyboard-activatable, form-submit
 * aware via `type`) rather than reinvented on a <div>.
 *
 * Usage:
 *   <Button onClick={save} loading={saving}>Save</Button>
 *   <Button variant="danger" size="sm" onClick={remove}>Remove</Button>
 *   <Button variant="link" as button type="button">Cancel</Button>
 */
export default function Button({
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  leftIcon,
  rightIcon,
  fullWidth = false,
  className = "",
  children,
  ref,
  type = "button",
  ...rest
}: ButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <button
      ref={ref}
      type={type}
      className={[
        "ui-btn",
        `ui-btn--${variant}`,
        `ui-btn--${size}`,
        fullWidth ? "ui-btn--full" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && <Spinner size="sm" label="" className="ui-btn__spinner" />}
      {!loading && leftIcon && (
        <span className="ui-btn__icon" aria-hidden="true">
          {leftIcon}
        </span>
      )}
      <span className="ui-btn__label">{children}</span>
      {!loading && rightIcon && (
        <span className="ui-btn__icon" aria-hidden="true">
          {rightIcon}
        </span>
      )}
    </button>
  );
}
