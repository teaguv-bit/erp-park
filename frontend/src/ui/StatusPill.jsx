import "./StatusPill.css";
import { statusTone } from "./statusMap";

export default function StatusPill({ status, className = "" }) {
  const tone = statusTone(status);
  return <span className={`ui-pill ui-pill--${tone} ${className}`}>{status}</span>;
}
