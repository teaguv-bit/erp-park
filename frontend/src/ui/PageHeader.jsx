import "./PageHeader.css";

export default function PageHeader({ title, crumb, actions, className = "" }) {
  return (
    <header className={`ui-pagehead ${className}`}>
      <div className="ui-pagehead__titles">
        {crumb ? <div className="ui-pagehead__crumb">{crumb}</div> : null}
        <h1 className="ui-pagehead__title">{title}</h1>
      </div>
      {actions ? <div className="ui-pagehead__actions">{actions}</div> : null}
    </header>
  );
}
