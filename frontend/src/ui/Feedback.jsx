import "./Feedback.css";

export function Spinner({ size = 20, label = "Carregando" }) {
  return <span className="ui-spinner" style={{ width: size, height: size }} role="status" aria-label={label} />;
}

export function Skeleton({ width = "100%", height = 14, radius = "var(--radius-sm)" }) {
  return <span className="ui-skeleton" style={{ width, height, borderRadius: radius }} aria-hidden="true" />;
}
