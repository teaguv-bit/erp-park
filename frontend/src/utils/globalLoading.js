const EVENT_NAME = "trml-global-loading";

export function showGlobalLoading(label = "Carregando...") {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(EVENT_NAME, { detail: { open: true, label } }));
}

export function hideGlobalLoading() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(EVENT_NAME, { detail: { open: false, label: "" } }));
}

export async function withGlobalLoading(label, fn) {
  showGlobalLoading(label);
  try {
    return await fn();
  } finally {
    hideGlobalLoading();
  }
}

export function subscribeGlobalLoading(handler) {
  if (typeof window === "undefined") return () => {};
  const listener = (event) => handler(event?.detail || { open: false, label: "" });
  window.addEventListener(EVENT_NAME, listener);
  return () => window.removeEventListener(EVENT_NAME, listener);
}
