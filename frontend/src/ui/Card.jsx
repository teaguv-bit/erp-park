import "./Card.css";

export default function Card({ title, actions, padding = "md", className = "", children }) {
  return (
    <section className={`ui-card ui-card--pad-${padding} ${className}`}>
      {(title || actions) && (
        <header className="ui-card__head">
          {title ? <h3 className="ui-card__title">{title}</h3> : <span />}
          {actions ? <div className="ui-card__actions">{actions}</div> : null}
        </header>
      )}
      <div className="ui-card__body">{children}</div>
    </section>
  );
}
