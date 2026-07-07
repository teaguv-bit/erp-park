import "./EmptyState.css";

export default function EmptyState({ icon = null, title, message, action = null, className = "" }) {
  return (
    <div className={`ui-empty ${className}`}>
      {icon ? <div className="ui-empty__icon" aria-hidden="true">{icon}</div> : null}
      {title ? <div className="ui-empty__title">{title}</div> : null}
      {message ? <div className="ui-empty__msg">{message}</div> : null}
      {action ? <div className="ui-empty__action">{action}</div> : null}
    </div>
  );
}
