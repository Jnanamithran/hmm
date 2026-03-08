// ControlRoom.jsx — controller view: Live stream + Analytics tab
// Refactored from App.jsx v4, adds:
//   - Tab switcher (LIVE / ANALYTICS)
//   - Firebase SessionLogger integration
//   - Logout + nav to dashboard (for managers)

import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import VideoFeed  from "../components/VideoFeed.jsx";
import Controls   from "../components/Controls.jsx";
import StatusBar  from "../components/StatusBar.jsx";
import Analytics  from "../components/Analytics.jsx";
import { useAuth } from "../contexts/AuthContext.jsx";
import { SessionLogger } from "../utils/sessionLogger.js";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const KEY_MAP = {
  w:"forward", W:"forward", ArrowUp:"forward",
  s:"backward",S:"backward",ArrowDown:"backward",
  a:"left",    A:"left",    ArrowLeft:"left",
  d:"right",   D:"right",   ArrowRight:"right",
};

function fmtTime(s) {
  if (s == null) return "00:00";
  return `${String(Math.floor(s/60)).padStart(2,"0")}:${String(Math.floor(s%60)).padStart(2,"0")}`;
}

export default function ControlRoom() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState("live"); // "live" | "analytics"

  // ── Server state ───────────────────────────────────────────────────────────
  const [aiEnabled,      setAiEnabled]      = useState(true);
  const [thermalEnabled, setThermalEnabled] = useState(false);
  const [thermalAlpha,   setThermalAlpha]   = useState(45);
  const [piConnected,    setPiConnected]    = useState(false);
  const [aiConnected,    setAiConnected]    = useState(false);
  const [thermalOnline,  setThermalOnline]  = useState(false);
  const [detections,     setDetections]     = useState([]);
  const [gasData,        setGasData]        = useState({
    ppm:null, level:"OFFLINE", voltage:null,
    gas:"CH4 / Methane", sensor:"MQ4", available:false,
  });
  const [recStatus, setRecStatus] = useState({
    recording:false, filename:null, duration_s:null, frames:0
  });

  // ── Drive ──────────────────────────────────────────────────────────────────
  const [lastCmd,    setLastCmd]    = useState("stop");
  const [cmdError,   setCmdError]   = useState(null);
  const [activeKeys, setActiveKeys] = useState(new Set());
  const keysRef     = useRef(new Set());
  const lastSentRef = useRef("stop");

  // ── Session logger ─────────────────────────────────────────────────────────
  const loggerRef      = useRef(null);
  const gasReadingsRef = useRef([]);   // local copy for analytics

  useEffect(() => {
    const logger = new SessionLogger(user);
    loggerRef.current = logger;
    logger.start().catch(console.error);

    const handleUnload = () => logger.finish();
    window.addEventListener("beforeunload", handleUnload);
    return () => {
      window.removeEventListener("beforeunload", handleUnload);
      logger.finish();
    };
  }, [user]);

  // ── Motor ──────────────────────────────────────────────────────────────────
  const sendCommand = useCallback(async (dir) => {
    if (lastSentRef.current === dir) return;
    lastSentRef.current = dir;
    setLastCmd(dir);
    setCmdError(null);
    try {
      const r = await fetch(`${API}/move/${dir}`, { method:"POST" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
    } catch(e) { setCmdError(e.message); }
  }, []);

  // ── Keyboard ───────────────────────────────────────────────────────────────
  useEffect(() => {
    const down = (e) => {
      if (e.repeat) return;
      const dir = KEY_MAP[e.key]; if (!dir) return;
      e.preventDefault();
      keysRef.current.add(e.key.toLowerCase());
      setActiveKeys(new Set(keysRef.current));
      sendCommand(dir);
    };
    const up = (e) => {
      const dir = KEY_MAP[e.key]; if (!dir) return;
      e.preventDefault();
      keysRef.current.delete(e.key.toLowerCase());
      setActiveKeys(new Set(keysRef.current));
      if (keysRef.current.size === 0) sendCommand("stop");
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup",   up);
    return () => { window.removeEventListener("keydown",down); window.removeEventListener("keyup",up); };
  }, [sendCommand]);

  // ── Poll health + detections ───────────────────────────────────────────────
  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/detections`, {signal:AbortSignal.timeout(1500)});
        if (r.ok) {
          const dets = await r.json();
          setDetections(dets);
          setAiConnected(true);
          loggerRef.current?.addDetections(dets);
        } else setAiConnected(false);
      } catch { setAiConnected(false); }

      try {
        const r = await fetch(`${API}/health`, {signal:AbortSignal.timeout(1500)});
        if (r.ok) {
          const h = await r.json();
          setPiConnected(h.pi_connected  || false);
          setThermalOnline(h.thermal_online || false);
          setAiEnabled(h.ai_enabled ?? true);
          setThermalEnabled(h.thermal_enabled ?? false);
          if (h.thermal_alpha != null) setThermalAlpha(Math.round(h.thermal_alpha * 100));
          if (h.recording) setRecStatus(h.recording);
        }
      } catch {}
    };
    poll();
    const id = setInterval(poll, 300);
    return () => clearInterval(id);
  }, []);

  // ── Poll gas + log readings ────────────────────────────────────────────────
  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/gas`, {signal:AbortSignal.timeout(1500)});
        if (r.ok) {
          const g = await r.json();
          setGasData(g);
          if (g.ppm != null) {
            loggerRef.current?.addGasReading(g.ppm, g.level);
            const t = (Date.now() - (loggerRef.current?.startMs || Date.now()));
            gasReadingsRef.current.push({ t, ppm: g.ppm });
          }
        }
      } catch {}
    };
    poll();
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
  }, []);

  // ── Toggles ────────────────────────────────────────────────────────────────
  const toggleAI = async () => {
    try { const r = await fetch(`${API}/ai/toggle`,{method:"POST"}); if(r.ok){const d=await r.json();setAiEnabled(d.ai_enabled);} }
    catch { setAiEnabled(v=>!v); }
  };
  const toggleThermal = async () => {
    try { const r = await fetch(`${API}/thermal/toggle`,{method:"POST"}); if(r.ok){const d=await r.json();setThermalEnabled(d.thermal_enabled);} }
    catch { setThermalEnabled(v=>!v); }
  };
  const setAlpha = async (val) => {
    setThermalAlpha(val);
    try { await fetch(`${API}/thermal/opacity`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({alpha:val/100})}); }
    catch {}
  };
  const toggleRec = async () => {
    const ep = recStatus.recording ? "/recording/stop" : "/recording/start";
    try { const r = await fetch(`${API}${ep}`,{method:"POST"}); if(r.ok) setRecStatus(await r.json()); }
    catch {}
  };

  const gasLevel = gasData.level || "OFFLINE";

  return (
    <div className="shell">
      {/* ══ HEADER ══════════════════════════════════════════════════════════ */}
      <header className="header">
        <div className="header-left">
          <div className="brand">
            <span className="brand-viper">VIPER</span>
            <span className="brand-ctrl">CTRL</span>
          </div>
          <div className="conn-row">
            <ConnDot label="PI" ok={piConnected}/>
            <ConnDot label="AI" ok={aiConnected}/>
          </div>
        </div>

        <div className="header-center">
          <div className={`gas-hdr-badge lv-${gasLevel.toLowerCase()}`}>
            <span className="gas-hdr-icon">◈</span>
            <span className="gas-hdr-label">GAS</span>
            <span className="gas-hdr-ppm">
              {gasData.ppm !== null ? `${Math.round(gasData.ppm)} PPM` : "--- PPM"}
            </span>
            <span className="gas-hdr-level">{gasLevel}</span>
          </div>
        </div>

        <div className="header-right">
          <button className={`rec-btn ${recStatus.recording?"rec-on":"rec-off"}`} onClick={toggleRec}>
            <span className="rec-dot"/>
            {recStatus.recording ? `REC  ${fmtTime(recStatus.duration_s)}` : "REC"}
          </button>

          <TogBtn active={aiEnabled}      label="AI VISION"  onClick={toggleAI}      color="green" />
          <TogBtn active={thermalEnabled} label="THERMAL IR" onClick={toggleThermal} color="orange"/>

          {thermalEnabled && (
            <div className="opacity-row">
              <span className="opacity-lbl">α</span>
              <input className="opacity-range" type="range" min="10" max="80"
                value={thermalAlpha} onChange={e=>setAlpha(Number(e.target.value))}/>
              <span className="opacity-val">{thermalAlpha}%</span>
            </div>
          )}

          {/* Tab nav */}
          <div className="tab-nav">
            <button className={`tab-btn ${tab==="live"?"tab-active":""}`} onClick={()=>setTab("live")}>
              ◎ LIVE
            </button>
            <button className={`tab-btn ${tab==="analytics"?"tab-active":""}`} onClick={()=>setTab("analytics")}>
              ◈ ANALYTICS
            </button>
          </div>

          <button className="dash-logout sm" onClick={async()=>{await logout();navigate("/login");}}>
            ⏻
          </button>
        </div>
      </header>

      {/* ══ BODY ════════════════════════════════════════════════════════════ */}
      <div className="body">
        {tab === "live" ? (
          <>
            <section className="video-panel">
              <VideoFeed
                streamUrl={`${API}/stream`}
                piConnected={piConnected}
                aiEnabled={aiEnabled}
                thermalEnabled={thermalEnabled}
                thermalOnline={thermalOnline}
                isRecording={recStatus.recording}
              />
            </section>
            <aside className="sidebar">
              <Controls
                direction={lastCmd}
                sendCommand={sendCommand}
              />
              <StatusBar
                detections={detections}
                gasData={gasData}
                piConnected={piConnected}
                aiConnected={aiConnected}
                thermalOnline={thermalOnline}
                thermalEnabled={thermalEnabled}
                aiEnabled={aiEnabled}
                lastCmd={lastCmd}
                recStatus={recStatus}
              />
            </aside>
          </>
        ) : (
          <div className="analytics-page">
            <Analytics
              session={loggerRef.current
                ? { detections: loggerRef.current._detections, peakGasPpm: loggerRef.current._peakPpm, avgGasPpm: loggerRef.current._gasCount > 0 ? loggerRef.current._totalPpm / loggerRef.current._gasCount : 0 }
                : {}}
              detections={detections}
              gasReadings={gasReadingsRef.current}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function ConnDot({label, ok}) {
  return (
    <div className="conn-dot-wrap">
      <span className={`conn-dot ${ok?"up":"down"}`}/>
      <span className={`conn-label ${ok?"up":"down"}`}>{label}</span>
    </div>
  );
}
function TogBtn({active, label, onClick, color}) {
  return (
    <button className={`tog-btn tog-${color} ${active?"tog-on":""}`} onClick={onClick}>
      <span className="tog-dot">{active?"●":"○"}</span>
      {label}
    </button>
  );
}
