import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

export default function Login() {
  const { login, role } = useAuth();
  const navigate        = useNavigate();
  const [email, setEmail]   = useState("");
  const [pass,  setPass]    = useState("");
  const [err,   setErr]     = useState("");
  const [busy,  setBusy]    = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email || !pass) { setErr("Enter email and password."); return; }
    setBusy(true);
    setErr("");
    try {
      await login(email, pass);
      // Role-based redirect — AuthContext will have updated role by now
      // Use a tiny delay so the context role state settles
      setTimeout(() => {
        const r = localStorage.getItem("__viper_role__") || "controller";
        navigate(r === "manager" ? "/dashboard" : "/control", { replace: true });
      }, 200);
    } catch (e) {
      const msg = e.code === "auth/invalid-credential"
        ? "Invalid email or password."
        : e.code === "auth/too-many-requests"
        ? "Too many attempts — try again later."
        : "Login failed. Check your connection.";
      setErr(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-shell">
      {/* Animated scan lines */}
      <div className="login-bg">
        <div className="login-grid"/>
        <div className="login-scanline"/>
      </div>

      <div className="login-card">
        {/* Brand */}
        <div className="login-brand">
          <div className="login-logo">
            <span className="login-logo-v">V</span>
            <div className="login-logo-bar"/>
          </div>
          <div className="login-title">
            <span className="login-title-viper">VIPER</span>
            <span className="login-title-ndt">NDT PIPELINE INSPECTION</span>
          </div>
        </div>

        <div className="login-divider"/>

        <div className="login-subtitle">SECURE ACCESS PORTAL</div>

        <form className="login-form" onSubmit={handleSubmit}>
          <div className="login-field">
            <label className="login-label">EMAIL</label>
            <input
              className="login-input"
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="operator@company.com"
              autoComplete="email"
              disabled={busy}
            />
          </div>

          <div className="login-field">
            <label className="login-label">PASSWORD</label>
            <input
              className="login-input"
              type="password"
              value={pass}
              onChange={e => setPass(e.target.value)}
              placeholder="••••••••••"
              autoComplete="current-password"
              disabled={busy}
            />
          </div>

          {err && <div className="login-err">⚠ {err}</div>}

          <button className="login-btn" type="submit" disabled={busy}>
            {busy ? (
              <><span className="login-spinner"/>AUTHENTICATING...</>
            ) : (
              <>ENTER SYSTEM →</>
            )}
          </button>
        </form>

        <div className="login-footer">
          <span className="login-footer-dot"/>
          SYSTEM SECURE
          <span className="login-footer-dot"/>
          AES-256
          <span className="login-footer-dot"/>
          VIPER v2.0
        </div>
      </div>
    </div>
  );
}
