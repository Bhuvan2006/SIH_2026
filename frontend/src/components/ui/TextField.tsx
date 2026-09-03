import { useId } from "react";
import type { InputHTMLAttributes, Ref } from "react";

export interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id"> {
  /** Visible label. Always required -- this component never renders a
   * placeholder-only "label" (a placeholder disappears on focus/input and
   * fails WCAG 1.3.1 / 3.3.2 for anyone who loses their place). */
  label: string;
  /** Explicit id; auto-generated via useId() when omitted, so callers
   * never have to invent one just to satisfy label association. */
  id?: string;
  /** Validation message. When present, sets aria-invalid and is announced
   * via aria-describedby; also switches the field into its error style. */
  error?: string;
  /** Supplementary guidance shown under the field when there's no error. */
  helperText?: string;
  /**
   * Visually hides the label (e.g. a compact search/chat box where a
   * placeholder already conveys purpose to sighted users) while keeping
   * it in the accessibility tree -- screen readers still announce it.
   * Prefer a visible label whenever there's room for one.
   */
  hideLabel?: boolean;
  ref?: Ref<HTMLInputElement>;
}

/**
 * Labeled text input with built-in error/helper text wiring. Every input
 * gets a real <label htmlFor>, so clicking the label focuses the field and
 * screen readers announce it correctly -- unlike the bare <input> +
 * sibling <label> pairs (no htmlFor) used ad hoc elsewhere in this app.
 *
 * Usage:
 *   <TextField label="Phone number" type="tel" value={phone}
 *     onChange={(e) => setPhone(e.target.value)} placeholder="+91XXXXXXXXXX" />
 *
 *   <TextField label="OTP" error={error ?? undefined} required
 *     value={otp} onChange={(e) => setOtp(e.target.value)} />
 */
export default function TextField({
  label,
  id,
  error,
  helperText,
  hideLabel = false,
  required,
  className = "",
  ref,
  ...rest
}: TextFieldProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const errorId = `${inputId}-error`;
  const helperId = `${inputId}-helper`;
  const describedBy = error ? errorId : helperText ? helperId : undefined;

  return (
    <div className={["ui-field", error ? "ui-field--error" : "", className].filter(Boolean).join(" ")}>
      <label
        className={["ui-field__label", hideLabel ? "ui-visually-hidden" : ""].filter(Boolean).join(" ")}
        htmlFor={inputId}
      >
        {label}
        {required && (
          <span className="ui-field__required" aria-hidden="true">
            {" "}
            *
          </span>
        )}
      </label>
      <input
        ref={ref}
        id={inputId}
        className="ui-field__input"
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        {...rest}
      />
      {error ? (
        <p className="ui-field__error" id={errorId} role="alert">
          {error}
        </p>
      ) : helperText ? (
        <p className="ui-field__helper" id={helperId}>
          {helperText}
        </p>
      ) : null}
    </div>
  );
}
