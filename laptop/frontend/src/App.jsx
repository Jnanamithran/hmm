import { useEffect } from "react";
import { Routes, Route, Navigate, useNavigate } from "react-router-dom";
import { useAuth }     from "./contexts/AuthContext.jsx";
import Login           from "./pages/Login.jsx";
import ControlRoom     from "./pages/ControlRoom.jsx";
import Dashboard       from "./pages/Dashboard.jsx";
import DetectionLog    from "./pages/DetectionLog.jsx";

function Splash({ msg = "AUTHENTICATING..." }) {
  return (
    <div style={{ display:"flex",alignItems:"center",justifyContent:"center",
      height:"100vh",background:"#050709",flexDirection:"column",gap:16 }}>
      <div style={{ fontFamily:"'Orbitron',monospace",color:"#00ff88",fontSize:13,letterSpacing:4 }}>
        {msg}
      </div>
      <div style={{ width:120,height:2,background:"#0a1a0e",borderRadius:2,overflow:"hidden" }}>
        <div style={{ height:"100%",background:"#00ff88",animation:"loadbar 1.5s ease-in-out infinite" }}/>
      </div>
      <style>{`@keyframes loadbar{0%{width:0%}50%{width:100%}100%{width:0%;margin-left:100%}}`}</style>
    </div>
  );
}

// allowRole: "controller" | "manager"
// Wrong role → redirected to their home. Not logged in → /login.
function Guard({ children, allowRole }) {
  const { user, role, loading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (loading) return;
    if (!user) { navigate("/login", { replace:true }); return; }
    if (allowRole && role && role !== allowRole) {
      navigate(role === "manager" ? "/dashboard" : "/control", { replace:true });
    }
  }, [user, role, loading, allowRole, navigate]);

  if (loading || !user)                      return <Splash/>;
  if (!role)                                 return <Splash msg="LOADING PROFILE..."/>;
  if (allowRole && role !== allowRole)       return null;
  return children;
}

export default function App() {
  const { user, role, loading } = useAuth();
  const home = role === "manager" ? "/dashboard" : "/control";

  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={
        loading ? <Splash/> : user ? <Navigate to={home} replace/> : <Login/>
      }/>

      {/* CONTROLLER ONLY */}
      <Route path="/control" element={
        <Guard allowRole="controller"><ControlRoom/></Guard>
      }/>

      {/* MANAGER ONLY */}
      <Route path="/dashboard" element={
        <Guard allowRole="manager"><Dashboard/></Guard>
      }/>
      <Route path="/detection-log" element={
        <Guard allowRole="manager"><DetectionLog/></Guard>
      }/>

      {/* Catch-all */}
      <Route path="*" element={
        loading ? <Splash/> : user ? <Navigate to={home} replace/> : <Navigate to="/login" replace/>
      }/>
    </Routes>
  );
}
