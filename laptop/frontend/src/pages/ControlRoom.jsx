  // ControlRoom.jsx v6
  // NEW: Auto-stop motors on gas DANGER, severity badges, pipe map in sidebar

  import { useState, useEffect, useCallback, useRef } from "react";
  import { useNavigate } from "react-router-dom";
  import VideoFeed  from "../components/VideoFeed.jsx";
  import Controls   from "../components/Controls.jsx";
  import StatusBar  from "../components/StatusBar.jsx";
  import Analytics  from "../components/Analytics.jsx";
  import PipeMap    from "../components/PipeMap.jsx";
  import { useAuth } from "../contexts/AuthContext.jsx";
  import { SessionLogger } from "../utils/sessionLogger.js";

  const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

  const KEY_MAP = {
    w:"forward",  W:"forward",  ArrowUp:"forward",
    s:"backward", S:"backward", ArrowDown:"backward",
    a:"left",     A:"left",     ArrowLeft:"left",
    d:"right",    D:"right",    ArrowRight:"right",
    " ":"stop",
  };

  const SEV_COLOR = { CRITICAL:"#ff3333", MODERATE:"#ffa826", MINOR:"#00ff88" };
  const SEV_BG    = { CRITICAL:"#2a0808", MODERATE:"#1a1000", MINOR:"#0a1a0f" };

  function fmtTime(s) {
    if (s==null) return "00:00";
    return `${String(Math.floor(s/60)).padStart(2,"0")}:${String(Math.floor(s%60)).padStart(2,"0")}`;
  }

  export default function ControlRoom() {
    const { user, logout } = useAuth();
    const navigate = useNavigate();
    const [tab, setTab] = useState("live");

    const [aiEnabled,      setAiEnabled]      = useState(true);
    const [thermalEnabled, setThermalEnabled] = useState(false);
    const [thermalAlpha,   setThermalAlpha]   = useState(45);
    const [piConnected,    setPiConnected]    = useState(false);
    const [aiConnected,    setAiConnected]    = useState(false);
    const [thermalOnline,  setThermalOnline]  = useState(false);
    const [detections,     setDetections]     = useState([]);
    const [gasData,        setGasData]        = useState({
      ppm:null,level:"OFFLINE",voltage:null,gas:"CH4 / Methane",sensor:"MQ4",available:false
    });
    const [recStatus,    setRecStatus]    = useState({recording:false,filename:null,duration_s:null,frames:0});
    const [piTemp,       setPiTemp]       = useState(null);
    const [piTempStatus, setPiTempStatus] = useState("ok");
    const [pingMs,       setPingMs]       = useState(null);
    const [thermalAvgC,  setThermalAvgC]  = useState(null);
    const [thermalMinC,  setThermalMinC]  = useState(null);
    const [thermalMaxC,  setThermalMaxC]  = useState(null);

    // Distance + Speed
    const [distanceM, setDistanceM] = useState(0.0);
    const [speedKmh,  setSpeedKmh]  = useState(0.0);
    const [isMoving,  setIsMoving]  = useState(false);
    const distanceRef = useRef(0.0);

    // Session
    const loggerRef        = useRef(null);
    const [isLogging,      setIsLogging]      = useState(false);
    const [sessionStartMs, setSessionStartMs] = useState(null);
    const [sessionTimer,   setSessionTimer]   = useState("00:00");
    const gasReadingsRef   = useRef([]);

    // ── Pipe map detection history ─────────────────────────────────────────────
    const [detHistory, setDetHistory] = useState([]);  // [{label, severity, distance_m, timestamp}]

    // ── Auto-stop state ────────────────────────────────────────────────────────
    const [gasAlert,         setGasAlert]         = useState(false);  // true when DANGER triggered
    const [gasAlertDismissed,setGasAlertDismissed] = useState(false);
    const autoStoppedRef = useRef(false);

    // Session timer tick
    useEffect(() => {
      if (!isLogging || !sessionStartMs) return;
      const id = setInterval(() => {
        const elapsed = Math.floor((Date.now()-sessionStartMs)/1000);
        setSessionTimer(fmtTime(elapsed));
      },1000);
      return () => clearInterval(id);
    },[isLogging,sessionStartMs]);

    // Init logger
    useEffect(() => {
      const logger = new SessionLogger(user);
      loggerRef.current = logger;
      const handleUnload = () => { if(logger.isLogging) logger.finish(); };
      window.addEventListener("beforeunload",handleUnload);
      return () => { window.removeEventListener("beforeunload",handleUnload); if(logger.isLogging) logger.finish(); };
    },[user]);

    const toggleSession = useCallback(async () => {
      const logger = loggerRef.current;
      if (!logger) return;
      if (!isLogging) {
        await logger.start();
        setIsLogging(true);
        setSessionStartMs(Date.now());
        setSessionTimer("00:00");
        gasReadingsRef.current = [];
        setDetHistory([]);        // reset pipe map
        setGasAlert(false);
        setGasAlertDismissed(false);
        autoStoppedRef.current = false;
        fetch(`${API}/distance/reset`,{method:"POST"}).catch(()=>{});
        setDistanceM(0.0); distanceRef.current=0.0;
      } else {
        await logger.stop();
        setIsLogging(false); setSessionStartMs(null); setSessionTimer("00:00");
      }
    },[isLogging]);

    // ── Drive ──────────────────────────────────────────────────────────────────
    const [lastCmd,  setLastCmd]  = useState("stop");
    const [cmdError, setCmdError] = useState(null);
    const keysRef = useRef(new Set());

    const sendCommand = useCallback(async (dir) => {
      setLastCmd(dir); setCmdError(null);
      try {
        const r = await fetch(`${API}/move/${dir}`,{method:"POST"});
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
      } catch(e) {
        setCmdError(e.message);
        if (dir!=="stop") { try{await fetch(`${API}/move/stop`,{method:"POST"});}catch{} setLastCmd("stop"); }
      }
    },[]);

    useEffect(() => {
      const down=(e)=>{ if(e.repeat)return; const d=KEY_MAP[e.key]; if(!d)return; e.preventDefault(); keysRef.current.add(e.key.toLowerCase()); sendCommand(d); };
      const up=(e)=>{ const d=KEY_MAP[e.key]; if(!d)return; e.preventDefault(); keysRef.current.delete(e.key.toLowerCase()); if(keysRef.current.size===0)sendCommand("stop"); };
      window.addEventListener("keydown",down); window.addEventListener("keyup",up);
      return ()=>{ window.removeEventListener("keydown",down); window.removeEventListener("keyup",up); };
    },[sendCommand]);

    // Poll distance + speed
    useEffect(() => {
      const poll = async () => {
        try {
          const r = await fetch(`${API}/distance`,{signal:AbortSignal.timeout(1000)});
          if (r.ok) {
            const d = await r.json();
            setDistanceM(d.distance_m); setSpeedKmh(d.speed_kmh||0);
            setIsMoving(d.moving); distanceRef.current=d.distance_m;
          }
        } catch {}
      };
      poll(); const id=setInterval(poll,300); return()=>clearInterval(id);
    },[]);

    const resetOdometer = async () => {
      try { await fetch(`${API}/distance/reset`,{method:"POST"}); setDistanceM(0.0); distanceRef.current=0.0; } catch {}
    };

    // Poll health + detections
    useEffect(() => {
      const poll = async () => {
        try {
          const r = await fetch(`${API}/detections`,{signal:AbortSignal.timeout(1500)});
          if (r.ok) {
            const dets=await r.json(); setDetections(dets); setAiConnected(true);
            if (loggerRef.current?.isLogging) loggerRef.current.addDetections(dets,distanceRef.current);

            // Update pipe map history with new detections
            if (dets.length > 0) {
              setDetHistory(prev => {
                const now = Date.now();
                const newItems = dets
                  .filter(d => d.label && d.severity)
                  .map(d => ({
                    label:      d.label,
                    severity:   d.severity || "MINOR",
                    distance_m: d.distance_m ?? distanceRef.current,
                    timestamp:  now,
                  }));
                // Dedup: skip if same label at same distance (within 0.1m) in last 3s
                const filtered = newItems.filter(n =>
                  !prev.some(p => p.label===n.label && Math.abs(p.distance_m-n.distance_m)<0.1 && now-p.timestamp<3000)
                );
                return filtered.length > 0 ? [...prev, ...filtered] : prev;
              });
            }
          } else setAiConnected(false);
        } catch { setAiConnected(false); }

        try {
          const r = await fetch(`${API}/health`,{signal:AbortSignal.timeout(1500)});
          if (r.ok) {
            const h=await r.json();
            setPiConnected(h.pi_connected||false); setThermalOnline(h.thermal_online||false);
            setAiEnabled(h.ai_enabled??true); setThermalEnabled(h.thermal_enabled??false);
            if(h.thermal_alpha!=null) setThermalAlpha(Math.round(h.thermal_alpha*100));
            if(h.recording) setRecStatus(h.recording);
            if(h.pi_temp!=null) setPiTemp(h.pi_temp);
            if(h.pi_temp_status) setPiTempStatus(h.pi_temp_status);
            if(h.ping_ms!=null) setPingMs(h.ping_ms);
            if(h.thermal_avg_c!=null) { setThermalAvgC(h.thermal_avg_c); if(loggerRef.current?.isLogging) loggerRef.current.addThermalReading(h.thermal_avg_c); }
            if(h.thermal_min_c!=null) setThermalMinC(h.thermal_min_c);
            if(h.thermal_max_c!=null) setThermalMaxC(h.thermal_max_c);
            if(h.distance_m!=null) { setDistanceM(h.distance_m); distanceRef.current=h.distance_m; }
            if(h.speed_kmh!=null) setSpeedKmh(h.speed_kmh);
          }
        } catch {}
      };
      poll(); const id=setInterval(poll,300); return()=>clearInterval(id);
    },[]);

    // ── Gas polling + AUTO-STOP ───────────────────────────────────────────────
    useEffect(() => {
      const poll = async () => {
        try {
          const r=await fetch(`${API}/gas`,{signal:AbortSignal.timeout(1500)});
          if (r.ok) {
            const g=await r.json(); setGasData(g);
            if(g.ppm!=null && loggerRef.current?.isLogging) {
              loggerRef.current.addGasReading(g.ppm,g.level);
              gasReadingsRef.current.push({t:Date.now()-(loggerRef.current?.startMs||Date.now()),ppm:g.ppm});
            }

            // ── AUTO-STOP on DANGER gas level ──────────────────────────────
            if (g.level==="DANGER" && !autoStoppedRef.current && !gasAlertDismissed) {
              autoStoppedRef.current = true;
              setGasAlert(true);
              // Send stop command
              fetch(`${API}/move/stop`,{method:"POST"}).catch(()=>{});
              setLastCmd("stop");
              console.warn("[VIPER] GAS DANGER — auto-stopped motors at",g.ppm,"PPM");
            }
            // Reset auto-stop flag when gas drops below danger
            if (g.level!=="DANGER") {
              autoStoppedRef.current = false;
            }
          }
        } catch {}
      };
      poll(); const id=setInterval(poll,500); return()=>clearInterval(id);
    },[gasAlertDismissed]);

    const toggleAI=async()=>{ try{const r=await fetch(`${API}/ai/toggle`,{method:"POST"}); if(r.ok){const d=await r.json();setAiEnabled(d.ai_enabled);}}catch{setAiEnabled(v=>!v);} };
    const toggleThermal=async()=>{ try{const r=await fetch(`${API}/thermal/toggle`,{method:"POST"}); if(r.ok){const d=await r.json();setThermalEnabled(d.thermal_enabled);}}catch{setThermalEnabled(v=>!v);} };
    const setAlpha=async(val)=>{ setThermalAlpha(val); try{await fetch(`${API}/thermal/opacity`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({alpha:val/100})});}catch{} };
    const toggleRec=async()=>{ const ep=recStatus.recording?"/recording/stop":"/recording/start"; try{const r=await fetch(`${API}${ep}`,{method:"POST"}); if(r.ok)setRecStatus(await r.json());}catch{} };

    const gasLevel=gasData.level||"OFFLINE";

    return (
      <div className="shell">
        {/* ── GAS DANGER ALERT OVERLAY ── */}
        {gasAlert && !gasAlertDismissed && (
          <div style={{
            position:"fixed",inset:0,
            background:"rgba(255,0,0,0.18)",
            border:"3px solid #ff3333",
            zIndex:1000,
            display:"flex",alignItems:"center",justifyContent:"center",
            animation:"pulse 0.8s ease-in-out infinite",
            pointerEvents:"none",
          }}>
            <div style={{
              background:"#1a0000",border:"2px solid #ff3333",
              borderRadius:8,padding:"28px 40px",textAlign:"center",
              pointerEvents:"all",maxWidth:480,
            }}>
              <div style={{fontSize:40,marginBottom:8}}>⚠️</div>
              <div style={{fontFamily:"var(--disp)",fontSize:22,color:"#ff3333",letterSpacing:3,marginBottom:6}}>
                DANGER — GAS DETECTED
              </div>
              <div style={{fontFamily:"var(--mono)",fontSize:13,color:"#ff9999",marginBottom:4}}>
                {gasData.ppm!=null?`${Math.round(gasData.ppm)} PPM`:""} — MOTORS AUTO-STOPPED
              </div>
              <div style={{fontFamily:"var(--mono)",fontSize:11,color:"#cc6666",marginBottom:20}}>
                Do not resume until area is safe
              </div>
              <button
                onClick={()=>{ setGasAlert(false); setGasAlertDismissed(true); }}
                style={{
                  padding:"8px 28px",border:"1px solid #ff3333",borderRadius:4,
                  background:"#2a0808",color:"#ff3333",fontFamily:"var(--mono)",
                  fontSize:12,cursor:"pointer",letterSpacing:1,
                }}
              >
                ACKNOWLEDGE & DISMISS
              </button>
            </div>
          </div>
        )}

        <header className="header">
          <div className="header-left">
            <div className="brand" style={{cursor:"pointer"}} onClick={()=>navigate("/")}>
              <span className="brand-viper">VIPER</span><span className="brand-ctrl">CTRL</span>
            </div>
            <div className="conn-row">
              <ConnDot label="PI" ok={piConnected}/>
              <ConnDot label="AI" ok={aiConnected}/>
            </div>
          </div>

          <div className="header-center">
            <button className={`session-btn ${isLogging?"session-active":"session-idle"}`} onClick={toggleSession}>
              {isLogging?(<><span className="session-pulse"/>LOGGING {sessionTimer}<span className="session-stop-hint">■ STOP</span></>):(<><span className="session-dot-idle"/>START SESSION</>)}
            </button>
            <div className="dist-badge">
              <span className="dist-icon">⟷</span>
              <span className="dist-val">{distanceM.toFixed(2)}m</span>
              {isMoving&&<span className="dist-moving-dot"/>}
              <span style={{color:"#00d4ff",fontFamily:"var(--mono)",fontSize:12,marginLeft:4}}>
                {speedKmh.toFixed(2)} km/h
              </span>
              <button className="dist-reset-btn" onClick={resetOdometer} title="Reset">↺</button>
            </div>
            <div className={`gas-hdr-badge lv-${gasLevel.toLowerCase()}`}>
              <span className="gas-hdr-icon">◈</span>
              <span className="gas-hdr-label">GAS</span>
              <span className="gas-hdr-ppm">{gasData.ppm!==null?`${Math.round(gasData.ppm)} PPM`:"--- PPM"}</span>
              <span className="gas-hdr-level">{gasLevel}</span>
            </div>
          </div>

          <div className="header-right">
            <button className={`rec-btn ${recStatus.recording?"rec-on":"rec-off"}`} onClick={toggleRec}>
              <span className="rec-dot"/>
              {recStatus.recording?`REC  ${fmtTime(recStatus.duration_s)}`:"REC"}
            </button>
            <TogBtn active={aiEnabled}      label="AI VISION"  onClick={toggleAI}      color="green"/>
            <TogBtn active={thermalEnabled} label="THERMAL IR" onClick={toggleThermal} color="orange"/>
            {thermalEnabled&&(
              <div className="opacity-row">
                <span className="opacity-lbl">α</span>
                <input className="opacity-range" type="range" min="10" max="80" value={thermalAlpha} onChange={e=>setAlpha(Number(e.target.value))}/>
                <span className="opacity-val">{thermalAlpha}%</span>
              </div>
            )}
            <div className="tab-nav">
              <button className={`tab-btn ${tab==="live"?"tab-active":""}`} onClick={()=>setTab("live")}>◎ LIVE</button>
              <button className={`tab-btn ${tab==="analytics"?"tab-active":""}`} onClick={()=>setTab("analytics")}>◈ ANALYTICS</button>
              <button className="tab-btn" onClick={()=>navigate("/system-health")}>⬡ HEALTH</button>
            </div>
            <button className="dash-logout sm" onClick={async()=>{await logout();navigate("/login");}}>⏻</button>
          </div>
        </header>

        <div className="body">
          {tab==="live"?(
            <>
              <section className="video-panel">
                <VideoFeed streamUrl={`${API}/stream`} piConnected={piConnected} aiEnabled={aiEnabled} thermalEnabled={thermalEnabled} thermalOnline={thermalOnline} isRecording={recStatus.recording}/>
              </section>
              <aside className="sidebar">
                <Controls direction={lastCmd} sendCommand={sendCommand}/>

                {/* ── Severity detection list ── */}
                {detections.length > 0 && (
                  <div style={{marginTop:8}}>
                    {detections.map((d,i) => {
                      const sev=d.severity||"MINOR";
                      const col=SEV_COLOR[sev]; const bg=SEV_BG[sev];
                      return (
                        <div key={i} style={{
                          display:"flex",alignItems:"center",gap:8,
                          padding:"5px 8px",marginBottom:3,
                          background:bg,border:`1px solid ${col}44`,borderRadius:3,
                          fontFamily:"var(--mono)",fontSize:10,
                        }}>
                          <span style={{
                            padding:"1px 6px",borderRadius:2,
                            background:col+"22",border:`1px solid ${col}`,
                            color:col,fontSize:9,letterSpacing:1,flexShrink:0,
                          }}>{sev}</span>
                          <span style={{color:"var(--t0)",flex:1}}>{d.label?.toUpperCase()}</span>
                          <span style={{color:"var(--t2)",fontSize:9}}>
                            {d.confidence!=null?`${Math.round(d.confidence*100)}%`:""}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* ── Pipe map ── */}
                <div style={{
                  marginTop:10,padding:"8px 10px",
                  background:"var(--bg2)",border:"1px solid var(--bdr2)",borderRadius:4,
                }}>
                  <PipeMap
                    detectionHistory={detHistory}
                    distanceM={distanceM}
                  />
                </div>

                <StatusBar detections={detections} gasData={gasData} piConnected={piConnected} aiConnected={aiConnected} thermalOnline={thermalOnline} thermalEnabled={thermalEnabled} aiEnabled={aiEnabled} lastCmd={lastCmd} recStatus={recStatus} piTemp={piTemp} piTempStatus={piTempStatus} thermalAvgC={thermalAvgC} thermalMinC={thermalMinC} thermalMaxC={thermalMaxC} distanceM={distanceM} speedKmh={speedKmh} isMoving={isMoving} onResetDistance={resetOdometer} isLogging={isLogging}/>
              </aside>
            </>
          ):(
            <div className="analytics-page">
              <Analytics session={loggerRef.current?{detections:loggerRef.current._detections,peakGasPpm:loggerRef.current._peakPpm,avgGasPpm:loggerRef.current._gasCount>0?loggerRef.current._totalPpm/loggerRef.current._gasCount:0}:{}} detections={detections} gasReadings={gasReadingsRef.current} distanceM={distanceM}/>
            </div>
          )}
        </div>

        {cmdError&&(
          <div style={{position:"fixed",bottom:20,left:"50%",transform:"translateX(-50%)",background:"#ff333388",color:"#fff",padding:"8px 20px",borderRadius:6,fontFamily:"var(--mono)",fontSize:12,zIndex:999}}>
            Motor error: {cmdError}
          </div>
        )}
      </div>
    );
  }

  function ConnDot({label,ok}){return(<div className="conn-dot-wrap"><span className={`conn-dot ${ok?"up":"down"}`}/><span className={`conn-label ${ok?"up":"down"}`}>{label}</span></div>);}
  function TogBtn({active,label,onClick,color}){return(<button className={`tog-btn tog-${color} ${active?"tog-on":""}`} onClick={onClick}><span className="tog-dot">{active?"●":"○"}</span>{label}</button>);}