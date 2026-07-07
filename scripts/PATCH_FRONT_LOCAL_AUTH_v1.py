from pathlib import Path
import re

root = Path(r"C:\TRML_LOCAL\ERP\frontend\src")

firebase_path = root / "firebase.js"
app_path = root / "App.jsx"
api_path = root / "api.js"

# =========================
# firebase.js local-safe
# =========================
firebase_path.write_text(r'''import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider } from "firebase/auth";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FB_API_KEY,
  authDomain: import.meta.env.VITE_FB_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FB_PROJECT_ID,
  appId: import.meta.env.VITE_FB_APP_ID,
};

export const LOCAL_AUTH_MODE = !firebaseConfig.apiKey;

let authInstance = null;
let providerInstance = null;

if (!LOCAL_AUTH_MODE) {
  const app = initializeApp(firebaseConfig);
  authInstance = getAuth(app);
  providerInstance = new GoogleAuthProvider();
} else {
  const localUser = {
    email: "local@trml",
    displayName: "Administrador Local",
    getIdToken: async () => "",
  };

  authInstance = {
    currentUser: localUser,
    onAuthStateChanged(callback) {
      setTimeout(() => callback(localUser), 0);
      return () => {};
    },
  };

  providerInstance = {};
}

export const auth = authInstance;
export const googleProvider = providerInstance;
''', encoding="utf-8")

# =========================
# App.jsx: bypass local auth
# =========================
app = app_path.read_text(encoding="utf-8")

app = app.replace(
    'import { auth } from "./firebase";',
    'import { auth, LOCAL_AUTH_MODE } from "./firebase";'
)

old_effect = '''  useEffect(() => {
    return onAuthStateChanged(auth, (u) => setUser(u || null));
  }, []);
'''
new_effect = '''  useEffect(() => {
    if (LOCAL_AUTH_MODE) {
      setUser({
        email: "local@trml",
        displayName: "Administrador Local",
        getIdToken: async () => "",
      });
      return;
    }

    return onAuthStateChanged(auth, (u) => setUser(u || null));
  }, []);
'''
if old_effect not in app:
    raise SystemExit("Não encontrei o bloco onAuthStateChanged esperado em App.jsx")
app = app.replace(old_effect, new_effect)

# Troca signOut(auth) por helper seguro.
if "async function safeSignOut" not in app:
    marker = '''  useEffect(() => {
    let cancelled = false;
'''
    helper = '''  async function safeSignOut() {
    if (LOCAL_AUTH_MODE) {
      setUser({
        email: "local@trml",
        displayName: "Administrador Local",
        getIdToken: async () => "",
      });
      return;
    }

    try {
      await signOut(auth);
    } catch {}
  }

'''
    app = app.replace(marker, helper + marker)

app = app.replace('try { await signOut(auth); } catch {}', 'await safeSignOut()')

app_path.write_text(app, encoding="utf-8")

# =========================
# api.js: getTokenSafe tolerante ao modo local
# =========================
api = api_path.read_text(encoding="utf-8")

old = '''async function getTokenSafe() {
  if (auth.currentUser) {
    try {
      return await auth.currentUser.getIdToken();
    } catch {
      return await auth.currentUser.getIdToken(true);
    }
  }

  // espera auth inicializar
  return await new Promise((resolve) => {
    const unsub = auth.onAuthStateChanged(async (u) => {
      unsub();
      if (!u) return resolve(null);
      try {
        resolve(await u.getIdToken());
      } catch {
        resolve(null);
      }
    });
  });
}
'''
new = '''async function getTokenSafe() {
  if (!auth) return null;

  if (auth.currentUser) {
    try {
      const token = await auth.currentUser.getIdToken?.();
      return token || null;
    } catch {
      try {
        const token = await auth.currentUser.getIdToken?.(true);
        return token || null;
      } catch {
        return null;
      }
    }
  }

  if (typeof auth.onAuthStateChanged !== "function") return null;

  // espera auth inicializar
  return await new Promise((resolve) => {
    const unsub = auth.onAuthStateChanged(async (u) => {
      try { unsub?.(); } catch {}
      if (!u) return resolve(null);
      try {
        const token = await u.getIdToken?.();
        resolve(token || null);
      } catch {
        resolve(null);
      }
    });
  });
}
'''
if old not in api:
    raise SystemExit("Não encontrei getTokenSafe esperado em api.js")

api = api.replace(old, new)
api_path.write_text(api, encoding="utf-8")

print("OK: modo local sem Firebase aplicado em firebase.js, App.jsx e api.js")
