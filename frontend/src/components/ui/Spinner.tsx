export type SpinnerSize = "sm" | "md" | "lg";

export interface SpinnerProps {
  size?: SpinnerSize;
  /**
   * Screen-reader text announced via the live region. Pass "" to suppress
   * (use this when a visible label already sits next to the spinner, e.g.
   * inside Button, so screen readers don't hear the status twice).
   */
  label?: string;
  className?: string;
}

/**
 * Accessible loading indicator. Visually a spinning ring (respects
 * prefers-reduced-motion by falling back to a pulsing opacity instead of
 * a spin); for assistive tech it's a role="status" live region so a
 * "Loading" announcement fires without needing a separate aria-live
 * wrapper at each call site.
 *
 * Usage:
 *   <Spinner />                              // page/section loading
 *   <Spinner size="sm" label="Sending..." />  // inline, custom label
 */
export default function Spinner({ size = "md", label = "Loading…", className = "" }: SpinnerProps) {
  return (
    <span
      className={["ui-spinner", `ui-spinner--${size}`, className].filter(Boolean).join(" ")}
      role="status"
    >
      <span className="ui-spinner__ring" aria-hidden="true" />
      {label && <span className="ui-visually-hidden">{label}</span>}
    </span>
  );
}
