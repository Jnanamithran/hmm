import { createContext, useContext, useEffect, useState } from "react";
import { onAuthStateChanged, signInWithEmailAndPassword, signOut } from "firebase/auth";
import { ref, get, set } from "firebase/database";
import { auth, db } from "../firebase";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user,    setUser]    = useState(undefined);  // undefined = loading
  const [role,    setRole]    = useState(null);        // "manager" | "controller"
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const unsub = onAuthStateChanged(auth, async (u) => {
      if (u) {
        setUser(u);
        // Fetch role from DB. Default to "controller" if not set.
        try {
          const snap = await get(ref(db, `users/${u.uid}/role`));
          const r = snap.exists() ? snap.val() : "controller";
          // Write default if missing
          if (!snap.exists()) {
            await set(ref(db, `users/${u.uid}`), {
              role:  "controller",
              email: u.email,
              name:  u.displayName || u.email.split("@")[0],
            });
          }
          setRole(r);
        } catch {
          setRole("controller");
        }
      } else {
        setUser(null);
        setRole(null);
      }
      setLoading(false);
    });
    return unsub;
  }, []);

  const login = (email, password) =>
    signInWithEmailAndPassword(auth, email, password);

  const logout = () => signOut(auth);

  return (
    <AuthContext.Provider value={{ user, role, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
