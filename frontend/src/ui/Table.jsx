import "./Table.css";

export default function Table({ zebra = true, className = "", children }) {
  return (
    <div className="ui-table__scroll">
      <table className={`ui-table ${zebra ? "ui-table--zebra" : ""} ${className}`}>{children}</table>
    </div>
  );
}
