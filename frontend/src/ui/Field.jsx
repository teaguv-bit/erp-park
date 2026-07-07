import "./Field.css";

export default function Field({ label, id, error, help, className = "", children }) {
  return (
    <div className={`ui-field ${error ? "is-error" : ""} ${className}`}>
      {label ? <label className="ui-field__label" htmlFor={id}>{label}</label> : null}
      <div className="ui-field__control">{children}</div>
      {help && !error ? <div className="ui-field__help">{help}</div> : null}
      {error ? <div className="ui-field__error">{error}</div> : null}
    </div>
  );
}
