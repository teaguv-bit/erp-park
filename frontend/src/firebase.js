import { initializeApp } from "firebase/app";
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
