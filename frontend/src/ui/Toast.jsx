import { useCallback, useRef, useState } from "react";
import "./Toast.css";
import { ToastCtx } from "./toastContext";

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const seq = useRef(0);

  const remove = useCallback((id) => setItems((xs) => xs.filter((t) => t.id !== id)), []);

  const toast = useCallback(({ type = "info", message, duration = 3500 }) => {
    const id = ++seq.current;
    setItems((xs) => [...xs, { id, type, message }]);
    if (duration > 0) setTimeout(() => remove(id), duration);
  }, [remove]);

  return (
    <ToastCtx.Provider value={{ toast }}>
      {children}
      <div className="ui-toasts" role="region" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`ui-toast ui-toast--${t.type}`} onClick={() => remove(t.id)}>
            {t.message}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
