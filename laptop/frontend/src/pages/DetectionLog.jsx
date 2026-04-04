// pages/DetectionLog.jsx — MANAGER ONLY
// Simple session history list + CSV download. No filters, no tabs.

import { useState, useEffect } from "react";
import { ref, onValue, get } from "firebase/database";
import { db } from "../firebase";
import { useAuth } from "../contexts/AuthContext";
import { useNavigate } from "react-router-dom";

const fmtDate = (ms) => !ms ? "--" : new Date(ms).toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" });
const fmtTime = (ms) => !ms ? "--" : new Date(ms).toLocaleTimeString("en-GB", { hour:"2-digit", minute:"2-digit", second:"2-digit" });
const fmtDur  = (s)  => { if (!s) return "0s"; const m = Math.floor(s/60), sec = s%60; return m>0 ? `${m}m ${sec}s` : `${sec}s`; };

function esc(v) { return `"${String(v ?? "").replace(/"/g,'""')}"`; }

function downloadCsv(rows, filename) {
  const csv  = rows.map(r => r.map(esc).join(",")).join("\n");
  const blob = new Blob([csv], { type:"text/csv;charset=utf-8;" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

const gasColor = (ppm) =>
  !ppm       ? "#527a65"
  : ppm>=5000 ? "#ff3333"
  : ppm>=1000 ? "#ffa826"
  : ppm>=50   ? "#00d4ff"
  : "#00ff88";

const gasLabel = (ppm) =>
  !ppm       ? null
  : ppm>=5000 ? ["lv-danger",  "DANGER"]
  : ppm>=1000 ? ["lv-warning", "WARN"]
  : ppm>=50   ? ["lv-low",     "LOW"]
  : ["lv-safe", "SAFE"];

export default function DetectionLog() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [sessions,    setSessions]    = useState([]);
  const [loading,     setLoading]     = useState(true);
  const [downloading, setDownloading] = useState(null);  // null | session.id
  const [expandedId,  setExpandedId]  = useState(null);

  // Load all completed sessions
  useEffect(() => {
    const q = ref(db,"sessions");
    return onValue(q, snap => {
      if (!snap.exists()) { setSessions([]); setLoading(false); return; }
      const arr = [];
      snap.forEach(c => {
        const s = c.val();
        if (s.status === "completed") arr.push({ ...s, id: c.key });
      });
      arr.sort((a,b) => b.startTime - a.startTime);
      setSessions(arr);
      setLoading(false);
    });
  }, []);

  // Download CSV for a single session
  const handleDownload = async (session) => {
    setDownloading(session.id);
    try {
      // Get all events for this session (no orderByChild to avoid index error)
      const evSnap = await get(ref(db,"detectionEvents"));

      const events = [];
      if (evSnap.exists()) {
        evSnap.forEach(c => {
          const e = c.val();
          if (e.sessionId === session.id) events.push({ ...e, id: c.key });
        });
      }
      events.sort((a,b) => (a.timestamp||0) - (b.timestamp||0));
      console.log(`[CSV] Found ${events.length} individual events for session ${session.id}`);

      // Build filename with date AND time so same-day sessions never clash
      const now      = new Date();
      const dateStr  = fmtDate(session.startTime).replace(/ /g, "-");   // 23-Mar-2026
      const timeStr  = fmtTime(session.startTime).replace(/:/g, "-");   // 10-01-05
      const safeName = `viper-session-${dateStr}_${timeStr}.csv`;

      if (events.length > 0) {
        // Full per-detection CSV
        const header = ["Timestamp","Label","Confidence_%","Distance_m","Gas_PPM","Gas_Level","Thermal_Avg_C","Operator","Session_ID"];
        const rows   = events.map(e => [
          `${fmtDate(e.timestamp)} ${fmtTime(e.timestamp)}`,
          e.label              || "",
          e.confidence         != null ? (e.confidence*100).toFixed(1)  : "",
          e.distance_m         != null ? e.distance_m.toFixed(3)        : "",
          // sessionLogger v6 writes gas_ppm, older loggers wrote gasPpm — handle both
          (e.gas_ppm ?? e.gasPpm) != null ? (e.gas_ppm ?? e.gasPpm).toFixed(1) : "",
          e.gasLevel           || "",
          // sessionLogger v6 writes thermalAvgC
          e.thermalAvgC        != null ? e.thermalAvgC.toFixed(1)       : "",
          e.controllerName     || session.controllerName                 || "",
          e.sessionId          || "",
        ]);
        downloadCsv([header,...rows], safeName);
      } else {
        // Fall back to session summary — expand each detection label into its own row
        const header = [
          "Session_ID","Date","Start_Time","End_Time","Duration_s",
          "Operator","Label","Count",
          "Peak_Gas_PPM","Avg_Gas_PPM","Peak_Distance_m","Avg_Thermal_C"
        ];

        const rows = [];
        const dets = Object.entries(session.detections || {});

        if (dets.length === 0) {
          // No detections — one row with empty label
          rows.push([
            session.id,
            fmtDate(session.startTime),
            fmtTime(session.startTime),
            fmtTime(session.endTime),
            session.duration ?? "",
            session.controllerName || "",
            "None", "0",
            session.peakGasPpm    != null ? session.peakGasPpm.toFixed(1)    : "",
            session.avgGasPpm     != null ? session.avgGasPpm.toFixed(1)      : "",
            session.peakDistanceM != null ? session.peakDistanceM.toFixed(2)  : "",
            session.avgThermalC   != null ? session.avgThermalC.toFixed(1)    : "",
          ]);
        } else {
          // One row per detection label — same session info repeated
          dets.forEach(([label, count]) => {
            rows.push([
              session.id,
              fmtDate(session.startTime),
              fmtTime(session.startTime),
              fmtTime(session.endTime),
              session.duration ?? "",
              session.controllerName || "",
              label,
              String(count),
              session.peakGasPpm    != null ? session.peakGasPpm.toFixed(1)    : "",
              session.avgGasPpm     != null ? session.avgGasPpm.toFixed(1)      : "",
              session.peakDistanceM != null ? session.peakDistanceM.toFixed(2)  : "",
              session.avgThermalC   != null ? session.avgThermalC.toFixed(1)    : "",
            ]);
          });
        }

        downloadCsv([header, ...rows], safeName);
      }
    } catch(err) {
      console.error("Download failed:", err);
      alert("Download failed — check console.");
    } finally {
      setDownloading(null);
    }
  };

  // ── Generate PDF report ──────────────────────────────────────────────────
  const generatePdf = async (session, dets) => {
    // Dynamically load jsPDF from CDN
    if (!window.jspdf) {
      await new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = "https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js";
        s.onload = resolve; s.onerror = reject;
        document.head.appendChild(s);
      });
    }
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF({ unit:"mm", format:"a4" });

    const W  = 210;   // A4 width mm
    const mx = 18;    // margin x
    let   y  = 20;

    const total = Object.values(session.detections||{}).reduce((a,v)=>a+v,0);

    // ── Header band ───────────────────────────────────────────────────────
    doc.setFillColor(10,20,10);
    doc.rect(0,0,W,28,"F");
    doc.setTextColor(0,255,136);
    doc.setFontSize(18); doc.setFont("helvetica","bold");
    doc.text("VIPER NDT",mx,12);
    doc.setFontSize(9); doc.setFont("helvetica","normal");
    doc.setTextColor(180,220,180);
    doc.text("PIPE INSPECTION REPORT",mx,19);
    doc.setTextColor(100,160,100);
    doc.text(`Generated: ${new Date().toLocaleString("en-GB")}`,W-mx,19,{align:"right"});
    y = 36;

    // ── Session meta ──────────────────────────────────────────────────────
    doc.setFont("helvetica","bold"); doc.setFontSize(11);
    doc.setTextColor(0,200,100);
    doc.text("SESSION SUMMARY",mx,y); y+=6;

    doc.setDrawColor(0,80,40);
    doc.setLineWidth(0.3); doc.line(mx,y,W-mx,y); y+=5;

    const metaRows = [
      ["Session ID",    session.id],
      ["Date",          fmtDate(session.startTime)],
      ["Start Time",    fmtTime(session.startTime)],
      ["End Time",      fmtTime(session.endTime)],
      ["Duration",      fmtDur(session.duration)],
      ["Operator",      session.controllerName||"Unknown"],
      ["Peak Distance", session.peakDistanceM!=null?`${session.peakDistanceM.toFixed(2)} m`:"—"],
    ];

    doc.setFontSize(9); doc.setFont("helvetica","normal");
    metaRows.forEach(([label,val]) => {
      doc.setTextColor(100,140,100); doc.text(label+":",mx,y);
      doc.setTextColor(30,30,30);    doc.text(String(val),mx+50,y);
      y+=6;
    });
    y+=4;

    // ── Gas summary ───────────────────────────────────────────────────────
    doc.setFont("helvetica","bold"); doc.setFontSize(11);
    doc.setTextColor(0,200,100);
    doc.text("GAS READINGS",mx,y); y+=6;
    doc.setLineWidth(0.3); doc.line(mx,y,W-mx,y); y+=5;

    doc.setFontSize(9); doc.setFont("helvetica","normal");
    const gasRows = [
      ["Peak Gas PPM",  session.peakGasPpm!=null?`${session.peakGasPpm.toFixed(1)} PPM`:"—"],
      ["Avg Gas PPM",   session.avgGasPpm !=null?`${session.avgGasPpm.toFixed(1)} PPM` :"—"],
      ["Avg Thermal",   session.avgThermalC!=null?`${session.avgThermalC.toFixed(1)} °C`:"—"],
    ];
    const gasStatus = (session.peakGasPpm||0)>=5000?"DANGER":(session.peakGasPpm||0)>=1000?"WARNING":(session.peakGasPpm||0)>=50?"LOW":"SAFE";
    gasRows.push(["Gas Status", gasStatus]);

    gasRows.forEach(([label,val]) => {
      doc.setTextColor(100,140,100); doc.text(label+":",mx,y);
      if (label==="Gas Status") {
        const gc = gasStatus==="DANGER"?[220,40,40]:gasStatus==="WARNING"?[220,140,40]:[40,180,100];
        doc.setTextColor(...gc);
      } else doc.setTextColor(30,30,30);
      doc.text(String(val),mx+50,y); y+=6;
    });
    y+=4;

    // ── Detections ────────────────────────────────────────────────────────
    doc.setFont("helvetica","bold"); doc.setFontSize(11);
    doc.setTextColor(0,200,100);
    doc.text("DEFECT DETECTIONS",mx,y); y+=6;
    doc.setLineWidth(0.3); doc.line(mx,y,W-mx,y); y+=5;

    if (dets.length===0) {
      doc.setFontSize(9); doc.setFont("helvetica","normal");
      doc.setTextColor(120,120,120);
      doc.text("No detections recorded in this session.",mx,y); y+=8;
    } else {
      // Table header
      doc.setFillColor(10,30,15);
      doc.rect(mx,y-4,W-mx*2,7,"F");
      doc.setFont("helvetica","bold"); doc.setFontSize(9);
      doc.setTextColor(0,200,100);
      doc.text("DEFECT TYPE",mx+2,y);
      doc.text("COUNT",mx+70,y);
      doc.text("% OF TOTAL",mx+100,y);
      y+=5;

      dets.sort((a,b)=>b[1]-a[1]).forEach(([label,count],i) => {
        if (y>270) { doc.addPage(); y=20; }
        doc.setFillColor(i%2===0?248:255, i%2===0?252:255, i%2===0?248:255);
        doc.rect(mx,y-4,W-mx*2,7,"F");
        doc.setFont("helvetica","normal"); doc.setTextColor(30,30,30);
        doc.text(label,mx+2,y);
        doc.text(String(count),mx+70,y);
        doc.text(`${total>0?Math.round(count/total*100):0}%`,mx+100,y);
        y+=7;
      });

      // Total
      doc.setFillColor(10,30,15);
      doc.rect(mx,y-4,W-mx*2,7,"F");
      doc.setFont("helvetica","bold"); doc.setTextColor(0,200,100);
      doc.text("TOTAL",mx+2,y);
      doc.text(String(total),mx+70,y);
      y+=10;
    }

    // ── NDT assessment ────────────────────────────────────────────────────
    if (y>240) { doc.addPage(); y=20; }
    doc.setFont("helvetica","bold"); doc.setFontSize(11);
    doc.setTextColor(0,200,100);
    doc.text("NDT ASSESSMENT",mx,y); y+=6;
    doc.setLineWidth(0.3); doc.line(mx,y,W-mx,y); y+=6;

    const hasCritical = dets.some(([l])=>l==="Crack"||l==="Hole"||l==="Buckling");
    const status = hasCritical?"REQUIRES IMMEDIATE INSPECTION":total===0?"PASS — No defects detected":"REVIEW RECOMMENDED";
    const statusColor = hasCritical?[220,40,40]:total===0?[40,180,100]:[220,140,40];

    doc.setFontSize(13); doc.setFont("helvetica","bold");
    doc.setTextColor(...statusColor);
    doc.text(status,mx,y); y+=8;

    doc.setFontSize(8); doc.setFont("helvetica","normal"); doc.setTextColor(120,120,120);
    doc.text("This report was auto-generated by VIPER NDT. Findings should be verified by a qualified NDT engineer.",mx,y,{maxWidth:W-mx*2});
    y+=10;

    // ── Footer ────────────────────────────────────────────────────────────
    doc.setFillColor(10,20,10);
    doc.rect(0,285,W,12,"F");
    doc.setFontSize(7); doc.setTextColor(80,120,80);
    doc.text("VIPER NDT — Pipe Inspection System",mx,292);
    doc.text(`Session: ${session.id?.slice(-12)}`,W-mx,292,{align:"right"});

    // Save
    const dateStr = fmtDate(session.startTime).replace(/ /g,"-");
    const timeStr = fmtTime(session.startTime).replace(/:/g,"-");
    doc.save(`viper-report-${dateStr}_${timeStr}.pdf`);
  };

  const totalDets = s => Object.values(s.detections||{}).reduce((a,v)=>a+v,0);

  return (
    <div className="dash-shell">

      {/* ── HEADER ── */}
      <header className="dash-header">
        <div className="dash-header-left">
          <div className="dash-brand" style={{cursor:"pointer"}} onClick={()=>navigate("/")}>
            <span className="dash-brand-v">VIPER</span>
            <span className="dash-brand-sub">NDT</span>
          </div>
          <div className="dash-role-badge">INSPECTION HISTORY</div>
        </div>
        <div className="dash-header-center">
          <button className="dash-tab" onClick={()=>navigate("/dashboard")}>← DASHBOARD</button>
        </div>
        <div className="dash-header-right">
          <div className="dash-user">
            <span className="dash-user-dot"/>{user?.email}
            <span className="dash-user-role">MANAGER</span>
          </div>
          <button className="dash-logout" onClick={async()=>{await logout();navigate("/login");}}>
            ⏻ LOGOUT
          </button>
        </div>
      </header>

      <div style={{padding:"16px 20px"}}>

        {/* ── TOP BAR ── */}
        <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:16}}>
          <div style={{fontFamily:"var(--mono)",fontSize:17,color:"var(--t2)",letterSpacing:2}}>
            {loading ? "LOADING..." : `${sessions.length} COMPLETED SESSION${sessions.length!==1?"S":""}`}
          </div>
        </div>

        {/* ── TABLE HEADER ── */}
        {!loading && sessions.length > 0 && (
          <div style={{
            display:"grid",
            gridTemplateColumns:"180px 1fr 80px 90px 110px 110px 70px 30px",
            gap:12,padding:"6px 16px",
            fontFamily:"var(--mono)",fontSize:17,letterSpacing:2,
            color:"var(--t2)",borderBottom:"1px solid var(--bdr2)",
            marginBottom:4,
          }}>
            <span>DATE & TIME</span>
            <span>OPERATOR</span>
            <span>DURATION</span>
            <span>DETECTIONS</span>
            <span>DISTANCE</span>
            <span>PEAK GAS</span>
            <span>LEVEL</span>
            <span></span>
          </div>
        )}

        {/* ── SESSIONS ── */}
        {loading ? (
          <div className="dash-empty">Loading...</div>
        ) : sessions.length === 0 ? (
          <div style={{textAlign:"center",padding:"80px 0"}}>
            <div style={{fontFamily:"var(--mono)",fontSize:19,color:"var(--t1)",marginBottom:10}}>
              No inspection sessions yet
            </div>
            <div style={{fontFamily:"var(--mono)",fontSize:17,color:"var(--t2)"}}>
              Control Room → START SESSION → drive rover → STOP SESSION
            </div>
          </div>
        ) : (
          <div style={{display:"flex",flexDirection:"column",gap:4}}>
            {sessions.map(s => {
              const isOpen = expandedId === s.id;
              const dets   = Object.entries(s.detections||{}).sort((a,b)=>b[1]-a[1]);
              const total  = totalDets(s);
              const gc     = gasColor(s.peakGasPpm);
              const gl     = gasLabel(s.peakGasPpm);

              return (
                <div key={s.id} style={{
                  background:"var(--bg2)",
                  border:"1px solid var(--bdr2)",
                  borderLeft: isOpen ? "2px solid #00ff88" : "2px solid transparent",
                  borderRadius:4,overflow:"hidden",transition:"border-color 0.15s",
                }}>
                  {/* ── Main row ── */}
                  <div
                    onClick={()=>setExpandedId(isOpen?null:s.id)}
                    style={{
                      display:"grid",
                      gridTemplateColumns:"180px 1fr 80px 90px 110px 110px 70px 30px",
                      alignItems:"center",gap:12,
                      padding:"11px 16px",cursor:"pointer",
                      fontFamily:"var(--mono)",fontSize:19,
                    }}
                  >
                    <div>
                      <div style={{color:"var(--t0)",fontSize:19}}>{fmtDate(s.startTime)}</div>
                      <div style={{color:"var(--t2)",fontSize:17,marginTop:2}}>{fmtTime(s.startTime)}</div>
                    </div>
                    <div style={{color:"var(--t1)",overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>
                      {s.controllerName||"—"}
                    </div>
                    <div style={{color:"#00d4ff"}}>{fmtDur(s.duration)}</div>
                    <div style={{color: total>0?"#00ff88":"var(--t2)"}}>
                      {total>0 ? `${total} det.` : "—"}
                    </div>
                    <div style={{color:"#00d4ff"}}>
                      {s.peakDistanceM!=null ? `${s.peakDistanceM.toFixed(2)} m` : <span style={{color:"var(--t2)"}}>—</span>}
                    </div>
                    <div style={{color:gc,fontWeight:s.peakGasPpm>=1000?700:400}}>
                      {s.peakGasPpm!=null ? `${Math.round(s.peakGasPpm)} PPM` : <span style={{color:"var(--t2)"}}>—</span>}
                    </div>
                    <div>
                      {gl ? <span className={`gas-hdr-badge ${gl[0]}`} style={{fontSize:17,padding:"2px 6px"}}>{gl[1]}</span>
                           : <span style={{color:"var(--t2)"}}>—</span>}
                    </div>
                    <div style={{color:"var(--t2)",textAlign:"center"}}>{isOpen?"▲":"▼"}</div>
                  </div>

                  {/* ── Expanded detail ── */}
                  {isOpen && (
                    <div style={{
                      borderTop:"1px solid var(--bdr)",
                      padding:"14px 16px 16px",
                      display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:20,
                    }}>
                      {/* Detections */}
                      <div>
                        <Label>DETECTIONS</Label>
                        {dets.length===0 ? (
                          <div style={{fontFamily:"var(--mono)",fontSize:19,color:"var(--t2)"}}>None recorded</div>
                        ) : dets.map(([lbl,cnt],i)=>(
                          <div key={lbl} style={{display:"flex",alignItems:"center",gap:8,marginBottom:6}}>
                            <div style={{flex:1,height:4,borderRadius:2,background:"var(--bg3)"}}>
                              <div style={{
                                width:`${Math.round(cnt/dets[0][1]*100)}%`,
                                height:"100%",borderRadius:2,
                                background:["#00ff88","#00d4ff","#ffa826","#ff3333","#b085ff"][i%5],
                              }}/>
                            </div>
                            <span style={{fontFamily:"var(--mono)",fontSize:19,color:"var(--t0)",minWidth:90}}>{lbl.toUpperCase()}</span>
                            <span style={{fontFamily:"var(--mono)",fontSize:19,color:"var(--t2)"}}>×{cnt}</span>
                          </div>
                        ))}
                      </div>

                      {/* Gas */}
                      <div>
                        <Label>GAS</Label>
                        <Row label="Peak"    value={s.peakGasPpm!=null?`${Math.round(s.peakGasPpm)} PPM`:"—"} color={gc}/>
                        <Row label="Average" value={s.avgGasPpm !=null?`${s.avgGasPpm.toFixed(1)} PPM` :"—"}/>
                      </div>

                      {/* Session info */}
                      <div>
                        <Label>SESSION</Label>
                        <Row label="Start"    value={fmtTime(s.startTime)}/>
                        <Row label="End"      value={fmtTime(s.endTime)}/>
                        <Row label="Duration" value={fmtDur(s.duration)}     color="#00d4ff"/>
                        <Row label="Distance" value={s.peakDistanceM!=null?`${s.peakDistanceM.toFixed(2)} m`:"—"} color="#00d4ff"/>
                        <Row label="Thermal"  value={s.avgThermalC!=null?`${s.avgThermalC.toFixed(1)} °C`:"—"}/>
                        <div style={{marginTop:10,fontFamily:"var(--mono)",fontSize:17,color:"var(--t2)"}}>
                          SESSION ID: {s.id}
                        </div>

                        {/* ── PDF report button ── */}
                        <button
                          onClick={e=>{ e.stopPropagation(); generatePdf(s, dets); }}
                          style={{
                            marginTop:8,width:"100%",
                            display:"flex",alignItems:"center",justifyContent:"center",gap:8,
                            padding:"8px 0",borderRadius:4,
                            border:"1px solid #b085ff",background:"#0d0a1a",
                            color:"#b085ff",fontFamily:"var(--mono)",fontSize:19,
                            letterSpacing:1.5,cursor:"pointer",
                          }}
                        >
                          ⬡ GENERATE PDF REPORT
                        </button>

                        {/* ── Per-session download button ── */}
                        <button
                          onClick={e=>{ e.stopPropagation(); handleDownload(s); }}
                          disabled={downloading===s.id}
                          style={{
                            marginTop:14,width:"100%",
                            display:"flex",alignItems:"center",justifyContent:"center",gap:8,
                            padding:"8px 0",borderRadius:4,
                            border:"1px solid #00ff88",background:"#0a200f",
                            color:"#00ff88",fontFamily:"var(--mono)",fontSize:19,
                            letterSpacing:1.5,cursor:"pointer",
                            opacity: downloading===s.id ? 0.6 : 1,
                          }}
                        >
                          {downloading===s.id ? "◌  PREPARING…" : "↓  DOWNLOAD THIS SESSION CSV"}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function Label({ children }) {
  return (
    <div style={{fontFamily:"var(--mono)",fontSize:17,letterSpacing:2,color:"var(--t2)",marginBottom:8}}>
      {children}
    </div>
  );
}

function Row({ label, value, color }) {
  return (
    <div style={{display:"flex",justifyContent:"space-between",marginBottom:5,fontFamily:"var(--mono)",fontSize:19}}>
      <span style={{color:"var(--t2)"}}>{label}</span>
      <span style={{color:color||"var(--t0)"}}>{value}</span>
    </div>
  );
}