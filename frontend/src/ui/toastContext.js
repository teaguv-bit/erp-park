import { createContext, useContext } from "react";

// Contexto e hook em arquivo separado do componente para preservar o React
// Fast Refresh (Toast.jsx exporta somente o componente ToastProvider).
export const ToastCtx = createContext(null);

export function useToast() {
  const ctx = useContext(ToastCtx);
  return ctx || { toast: () => {} };
}
