import "./Toolbar.css";

export default function Toolbar({ className = "", children }) {
  return <div className={`ui-toolbar ${className}`}>{children}</div>;
}
Toolbar.Spacer = function Spacer() { return <div className="ui-toolbar__spacer" />; };
