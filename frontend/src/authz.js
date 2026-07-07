let unauthorized = false;
const listeners = new Set();

export function setUnauthorized(v) {
  unauthorized = !!v;
  for (const fn of listeners) fn(unauthorized);
}

export function subscribeUnauthorized(fn) {
  listeners.add(fn);
  fn(unauthorized);
  return () => listeners.delete(fn);
}