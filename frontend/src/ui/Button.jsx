import "./Button.css";

export default function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon = null,
  disabled = false,
  className = "",
  children,
  ...rest
}) {
  return (
    <button
      className={`ui-btn ui-btn--${variant} ui-btn--${size} ${loading ? "is-loading" : ""} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <span className="ui-btn__spinner" aria-hidden="true" /> : icon ? <span className="ui-btn__icon" aria-hidden="true">{icon}</span> : null}
      <span className="ui-btn__label">{children}</span>
    </button>
  );
}
