// Dashboard.jsx — MANAGER ONLY
// FIXES:
//   - Clear All Data button to delete old Firebase logs
//   - Gas alerts bar chart Y-axis capped at reasonable max (not 68144)
//   - peakDistanceM shown in session detail
//   - NAVBAR FIX: 2-row header — brand/actions on row 1, tabs on row 2

import { useState, useEffect, useRef } from "react";
import { ref, onValue, query, orderByChild, remove } from "firebase/database";
import { db } from "../firebase";
import { useAuth } from "../contexts/AuthContext";
import { useNavigate } from "react-router-dom";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
  AreaChart, Area,
} from "recharts";

const PIE_COLORS = ["#00ff88","#00d4ff","#ffa826","#ff3333","#b085ff","#ff6eb4","#39e0c0","#ffe033"];
const TT = { background:"#090d14", border:"1px solid #1a3020", color:"#cce8dc", fontSize:11 };

const fmtDate = (ms) => !ms?"--":new Date(ms).toLocaleDateString("en-GB",{day:"2-digit",month:"short",year:"numeric"});
const fmtTime = (ms) => !ms?"--":new Date(ms).toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit"});
const fmtDur  = (s)  => { if(!s)return"0s"; const m=Math.floor(s/60),sec=s%60; return m>0?`${m}m ${sec}s`:`${sec}s`; };
const gasLvl  = (ppm) => {
  if(!ppm)      return{cls:"lv-offline",txt:"—",    color:"#527a65"};
  if(ppm<50)    return{cls:"lv-safe",   txt:"SAFE", color:"#00ff88"};
  if(ppm<1000)  return{cls:"lv-low",    txt:"LOW",  color:"#00d4ff"};
  if(ppm<5000)  return{cls:"lv-warning",txt:"WARN", color:"#ffa826"};
  return             {cls:"lv-danger",  txt:"DANGER",color:"#ff3333"};
};
const getWeekNum = (d) => { const s=new Date(d.getFullYear(),0,1); return Math.ceil(((d-s)/86400000+s.getDay()+1)/7); };

export default function Dashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [sessions,    setSessions]    = useState([]);
  const [loading,     setLoading]     = useState(true);
  const [selected,    setSelected]    = useState(null);
  const [filter,      setFilter]      = useState("all");
  const [activeTab,   setActiveTab]   = useState("overview");
  const [alertSort,   setAlertSort]   = useState("date");
  const [showClear,   setShowClear]   = useState(false);
  const [clearing,    setClearing]    = useState(false);

  useEffect(() => {
    const q = query(ref(db,"sessions"),orderByChild("startTime"));
    const unsub = onValue(q, snap => {
      if (!snap.exists()) { setSessions([]); setLoading(false); return; }
      const arr=[];
      snap.forEach(child=>{ const s=child.val(); if(s.status==="completed") arr.push({...s,id:child.key}); });
      arr.sort((a,b)=>b.startTime-a.startTime);
      setSessions(arr); setLoading(false);
    });
    return unsub;
  },[]);

  const clearAllData = async () => {
    setClearing(true);
    try {
      await remove(ref(db,"sessions"));
      await remove(ref(db,"detectionEvents"));
      setSessions([]); setSelected(null);
    } catch(e) {
      alert("Clear failed: " + e.message);
    } finally {
      setClearing(false); setShowClear(false);
    }
  };

  const now = Date.now();
  const filtered = sessions.filter(s=>{
    if(filter==="week")  return s.startTime>now-7*86400000;
    if(filter==="month") return s.startTime>now-30*86400000;
    return true;
  });
  const thisWeek = sessions.filter(s=>s.startTime>now-7*86400000);

  const detTotals={};
  filtered.forEach(s=>Object.entries(s.detections||{}).forEach(([k,v])=>{ detTotals[k]=(detTotals[k]||0)+v; }));
  const detPieData=Object.entries(detTotals).sort((a,b)=>b[1]-a[1]).map(([name,value])=>({name,value}));

  const weekMap={};
  filtered.forEach(s=>{ const d=new Date(s.startTime); const wk=`W${getWeekNum(d)}`; weekMap[wk]=(weekMap[wk]||0)+1; });
  const sessPerWeek=Object.entries(weekMap).sort((a,b)=>a[0]<b[0]?-1:1).slice(-12).map(([week,count])=>({week,count}));

  const gasOverTime=[...filtered].reverse().slice(-30).map(s=>({
    date:fmtDate(s.startTime).replace(/ \d{4}$/,""),
    peak:Math.round(s.peakGasPpm||0),
    avg:Math.round(s.avgGasPpm||0),
  }));

  const gasAlerts=sessions.filter(s=>(s.peakGasPpm||0)>=1000).sort((a,b)=>b.startTime-a.startTime);
  const sortedAlerts=alertSort==="ppm"?[...gasAlerts].sort((a,b)=>(b.peakGasPpm||0)-(a.peakGasPpm||0)):gasAlerts;

  const gasAlertMax = Math.min(
    Math.max(...gasAlerts.map(s=>s.peakGasPpm||0), 5000),
    10000
  );

  const lastRun=sessions[0]||null;
  const lastRunDets=lastRun?Object.values(lastRun.detections||{}).reduce((a,v)=>a+v,0):0;
  const lastRunTopDets=lastRun?Object.entries(lastRun.detections||{}).sort((a,b)=>b[1]-a[1]).slice(0,5):[];
  const lastRunGas=gasLvl(lastRun?.peakGasPpm);

  const opMap={};
  sessions.forEach(s=>{ const n=s.controllerName||"Unknown"; if(!opMap[n]) opMap[n]={name:n,sessions:0,totalDur:0,totalDets:0}; opMap[n].sessions++; opMap[n].totalDur+=s.duration||0; opMap[n].totalDets+=Object.values(s.detections||{}).reduce((a,v)=>a+v,0); });
  const operators=Object.values(opMap).sort((a,b)=>b.sessions-a.sessions);

  const totalDets=Object.values(detTotals).reduce((s,v)=>s+v,0);
  const avgDur=filtered.length?Math.round(filtered.reduce((s,x)=>s+(x.duration||0),0)/filtered.length):0;
  const maxGas=filtered.reduce((m,s)=>Math.max(m,s.peakGasPpm||0),0);
  const highAlert=filtered.filter(s=>(s.peakGasPpm||0)>=1000).length;

  return (
    <div className="dash-shell">

      {/* ═══════════════════════════════════════════════════════════════════
          HEADER — 2-row layout
          Row 1 (top)   : brand + portal badge  ·  right actions
          Row 2 (bottom): full-width tab strip
          ═══════════════════════════════════════════════════════════════════ */}
      <header className="dash-header dsh-hdr">

        {/* ── ROW 1: brand + right actions ── */}
        <div className="dsh-hdr-row1">

          {/* Left — brand */}
          <div className="dsh-hdr-left">
            <div className="dash-brand" style={{cursor:"pointer"}} onClick={()=>navigate("/")}>
              <span className="dash-brand-v">VIPER</span>
              <span className="dash-brand-sub">NDT</span>
            </div>
            <div className="dash-role-badge">MANAGER PORTAL</div>
          </div>

          {/* Right — clear data + filter + user + logout */}
          <div className="dsh-hdr-right">
            <button
              onClick={()=>setShowClear(true)}
              className="dsh-clear-btn">
              🗑 CLEAR DATA
            </button>

            <div className="dash-filter-row">
              {["all","week","month"].map(f=>(
                <button key={f} className={`dash-filter-btn ${filter===f?"active":""}`} onClick={()=>setFilter(f)}>
                  {f==="all"?"ALL TIME":f==="week"?"THIS WEEK":"THIS MONTH"}
                </button>
              ))}
            </div>

            <div className="dash-user">
              <span className="dash-user-dot"/>{user?.email}
              <span className="dash-user-role">MANAGER</span>
            </div>

            <button className="dash-logout" onClick={async()=>{await logout();navigate("/login");}}>
              ⏻ LOGOUT
            </button>
          </div>
        </div>

        {/* ── ROW 2: full-width tab strip ── */}
        <div className="dsh-hdr-tabs">
          {["overview","log","alerts","operators"].map(t=>(
            <button key={t}
              className={`dash-tab ${activeTab===t?"dash-tab-active":""}`}
              onClick={()=>{setActiveTab(t);setSelected(null);}}>
              {t==="overview"
                ? "◎ OVERVIEW"
                : t==="log"
                ? "≡ INSPECTION LOG"
                : t==="alerts"
                ? `⚠ GAS ALERTS${gasAlerts.length>0?` (${gasAlerts.length})`:""}`
                : "◈ OPERATORS"}
            </button>
          ))}
          <button className="dash-tab dash-tab-det" onClick={()=>navigate("/detection-log")}>
            ◉ DETECTION LOG →
          </button>
        </div>

      </header>

      {/* ── CLEAR DATA MODAL ── */}
      {showClear && (
        <div style={{
          position:"fixed",inset:0,background:"rgba(0,0,0,0.85)",
          display:"flex",alignItems:"center",justifyContent:"center",zIndex:1000,
        }}>
          <div style={{
            background:"#090d14",border:"1px solid #3a1010",borderRadius:8,
            padding:"32px 40px",maxWidth:440,textAlign:"center",
          }}>
            <div style={{color:"#ff4444",fontFamily:"var(--disp)",fontSize:20,marginBottom:12}}>⚠ CLEAR ALL DATA</div>
            <div style={{color:"var(--t1)",fontFamily:"var(--mono)",fontSize:11,lineHeight:1.8,marginBottom:24}}>
              This will permanently delete:<br/>
              • All inspection sessions<br/>
              • All detection events<br/>
              • All gas readings<br/><br/>
              <span style={{color:"#ff4444"}}>THIS CANNOT BE UNDONE.</span>
            </div>
            <div style={{display:"flex",gap:12,justifyContent:"center"}}>
              <button onClick={()=>setShowClear(false)} style={{
                padding:"8px 24px",border:"1px solid var(--bdr)",borderRadius:4,
                background:"transparent",color:"var(--t1)",fontFamily:"var(--mono)",
                fontSize:11,cursor:"pointer",
              }}>CANCEL</button>
              <button onClick={clearAllData} disabled={clearing} style={{
                padding:"8px 24px",border:"1px solid #ff4444",borderRadius:4,
                background:"#3a0808",color:"#ff4444",fontFamily:"var(--mono)",
                fontSize:11,cursor:"pointer",opacity:clearing?0.6:1,
              }}>{clearing?"CLEARING...":"YES, DELETE ALL"}</button>
            </div>
          </div>
        </div>
      )}

      <div className="dash-body">
        {/* ══ OVERVIEW ══ */}
        {activeTab==="overview" && (<>
          <div className="dash-kpi-row">
            <KpiCard icon="◎" label="TOTAL INSPECTIONS"  value={filtered.length}   color="green"/>
            <KpiCard icon="◈" label="TOTAL DETECTIONS"   value={totalDets}         color="cyan"/>
            <KpiCard icon="◷" label="AVG DURATION"       value={fmtDur(avgDur)}    color="amber"/>
            <KpiCard icon="◈" label="PEAK GAS (PPM)"     value={maxGas.toFixed(0)} color={maxGas>=1000?"red":"green"}/>
            <KpiCard icon="⚠" label="HIGH GAS ALERTS"   value={highAlert}         color={highAlert>0?"red":"green"}/>
          </div>

          <div className="dash-week-spotlight">
            <div className="dash-week-header">
              <div className="dash-week-title"><span className="dash-week-dot"/>LAST RUN REPORT</div>
              {lastRun&&<div className="dash-week-range">{fmtDate(lastRun.startTime)} {fmtTime(lastRun.startTime)}{lastRun.controllerName?` · ${lastRun.controllerName}`:""}</div>}
            </div>
            {!lastRun?(
              <div className="dash-empty" style={{padding:"20px 0"}}>No inspections recorded yet.</div>
            ):(
              <div className="dash-week-body">
                <div className="dash-week-kpis">
                  <WeekKpi label="DURATION"    value={fmtDur(lastRun.duration)}/>
                  <WeekKpi label="DETECTIONS"  value={lastRunDets}/>
                  <WeekKpi label="DISTANCE"    value={lastRun.peakDistanceM!=null?`${lastRun.peakDistanceM.toFixed(2)}m`:"--"}/>
                  <WeekKpi label="PEAK GAS"    value={`${(lastRun.peakGasPpm||0).toFixed(0)} PPM`} danger={(lastRun.peakGasPpm||0)>=1000}/>
                </div>
                <div className="dash-week-dets">
                  <div className="dash-week-dets-title">TOP DETECTIONS</div>
                  {lastRunTopDets.length===0?(
                    <div style={{fontFamily:"var(--mono)",fontSize:11,color:"var(--t2)",padding:"8px 0"}}>No detections this run.</div>
                  ):lastRunTopDets.map(([lbl,cnt],i)=>(
                    <div key={lbl} className="week-det-row">
                      <span className="week-det-rank">#{i+1}</span>
                      <span className="week-det-lbl">{lbl.toUpperCase()}</span>
                      <div className="week-det-bar"><div className="week-det-fill" style={{width:`${Math.round(cnt/lastRunTopDets[0][1]*100)}%`,background:PIE_COLORS[i]}}/></div>
                      <span className="week-det-cnt">×{cnt}</span>
                    </div>
                  ))}
                </div>
                <div className="dash-week-sessions">
                  <div className="dash-week-dets-title">RECENT RUNS (LAST 5)</div>
                  {sessions.slice(0,5).map(s=>{ const g=gasLvl(s.peakGasPpm); const dc=Object.values(s.detections||{}).reduce((a,v)=>a+v,0); return(
                    <div key={s.id} className="week-sess-row">
                      <span className="week-sess-date">{fmtDate(s.startTime)} {fmtTime(s.startTime)}</span>
                      <span className="week-sess-who">{s.controllerName||"—"}</span>
                      <span className="week-sess-dur">{fmtDur(s.duration)}</span>
                      <span className="week-sess-dets">{dc} det.</span>
                      <span className={`gas-hdr-badge ${g.cls}`} style={{fontSize:9,padding:"1px 7px"}}>{g.txt}</span>
                    </div>
                  );})}
                </div>
              </div>
            )}
          </div>

          <div className="dash-charts-row">
            <div className="dash-card dash-card-sm">
              <div className="dash-card-title">DETECTION TYPES</div>
              {detPieData.length===0?<div className="dash-empty">No data</div>:(
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart><Pie data={detPieData} cx="50%" cy="50%" innerRadius={55} outerRadius={85} paddingAngle={3} dataKey="value">
                    {detPieData.map((_,i)=><Cell key={i} fill={PIE_COLORS[i%8]} stroke="none"/>)}
                  </Pie><Tooltip contentStyle={TT}/><Legend wrapperStyle={{fontSize:10,color:"#527a65"}} iconType="circle" iconSize={8}/></PieChart>
                </ResponsiveContainer>
              )}
            </div>
            <div className="dash-card dash-card-md">
              <div className="dash-card-title">INSPECTIONS PER WEEK</div>
              {sessPerWeek.length===0?<div className="dash-empty">No data</div>:(
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={sessPerWeek} margin={{top:8,right:8,left:-20,bottom:0}}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#111e15"/>
                    <XAxis dataKey="week" tick={{fontSize:9,fill:"#527a65"}}/>
                    <YAxis tick={{fontSize:9,fill:"#527a65"}} allowDecimals={false}/>
                    <Tooltip contentStyle={TT}/>
                    <Bar dataKey="count" fill="#00ff88" radius={[3,3,0,0]} name="Sessions"/>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
            <div className="dash-card dash-card-md">
              <div className="dash-card-title">GAS LEVELS OVER SESSIONS</div>
              {gasOverTime.length===0?<div className="dash-empty">No gas data</div>:(
                <ResponsiveContainer width="100%" height={220}>
                  <AreaChart data={gasOverTime} margin={{top:8,right:8,left:-20,bottom:0}}>
                    <defs>
                      <linearGradient id="gp" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#ffa826" stopOpacity={0.3}/><stop offset="95%" stopColor="#ffa826" stopOpacity={0}/></linearGradient>
                      <linearGradient id="ga" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#00ff88" stopOpacity={0.2}/><stop offset="95%" stopColor="#00ff88" stopOpacity={0}/></linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#111e15"/>
                    <XAxis dataKey="date" tick={{fontSize:9,fill:"#527a65"}}/>
                    <YAxis tick={{fontSize:9,fill:"#527a65"}}/>
                    <Tooltip contentStyle={TT} formatter={v=>[`${v} PPM`]}/>
                    <Area type="monotone" dataKey="peak" stroke="#ffa826" fill="url(#gp)" strokeWidth={1.5} name="Peak PPM"/>
                    <Area type="monotone" dataKey="avg"  stroke="#00ff88" fill="url(#ga)" strokeWidth={1.5} name="Avg PPM"/>
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>
        </>)}

        {/* ══ INSPECTION LOG ══ */}
        {activeTab==="log" && (
          <div className="dash-log-layout">
            <div className="dash-card dash-card-list">
              <div className="dash-card-title">ALL INSPECTION SESSIONS<span className="dash-badge">{filtered.length}</span></div>
              {loading?<div className="dash-empty">Loading...</div>:filtered.length===0?<div className="dash-empty">No sessions recorded yet.</div>:(
                <div className="dash-session-list">
                  {filtered.map(s=>{ const g=gasLvl(s.peakGasPpm); const dc=Object.values(s.detections||{}).reduce((a,v)=>a+v,0); return(
                    <div key={s.id} className={`dash-session-row ${selected?.id===s.id?"selected":""}`} onClick={()=>setSelected(selected?.id===s.id?null:s)}>
                      <div className="dsr-date"><div className="dsr-day">{fmtDate(s.startTime)}</div><div className="dsr-time">{fmtTime(s.startTime)}</div></div>
                      <div className="dsr-who">{s.controllerName||"—"}</div>
                      <div className="dsr-dur">{fmtDur(s.duration)}</div>
                      <div className="dsr-dets">{dc} det.</div>
                      <div className={`dsr-gas gas-hdr-badge ${g.cls}`}>{g.txt}</div>
                      <div className="dsr-arrow">{selected?.id===s.id?"▲":"▼"}</div>
                    </div>
                  );})}
                </div>
              )}
            </div>
            {selected&&<SessionDetail session={selected}/>}
          </div>
        )}

        {/* ══ GAS ALERTS ══ */}
        {activeTab==="alerts" && (
          <div className="dash-alerts-layout">
            <div className="dash-alerts-header">
              <div className="dash-alerts-title">⚠ GAS ALERT LOG — PEAK GAS ≥ 1000 PPM</div>
              <div className="dash-alerts-count">{gasAlerts.length} alert{gasAlerts.length!==1?"s":""} total</div>
            </div>
            {gasAlerts.length>0&&(
              <div className="dash-alerts-sort">
                <span className="dash-alerts-sort-lbl">SORT BY:</span>
                <button className={`dash-sort-btn ${alertSort==="date"?"active":""}`} onClick={()=>setAlertSort("date")}>DATE (NEWEST FIRST)</button>
                <button className={`dash-sort-btn ${alertSort==="ppm"?"active":""}`}  onClick={()=>setAlertSort("ppm")}>HIGHEST GAS FIRST</button>
              </div>
            )}
            {gasAlerts.length===0?(
              <div className="dash-empty" style={{marginTop:40}}>No gas alerts recorded. All clear.</div>
            ):(<>
              <div className="dash-card" style={{marginBottom:14}}>
                <div className="dash-card-title">
                  PEAK GAS PPM — ALL ALERT SESSIONS
                  <span style={{fontFamily:"var(--mono)",fontSize:9,color:"var(--t2)",marginLeft:8}}>
                    (Chart capped at 10,000 PPM for readability — hover for exact value)
                  </span>
                </div>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={[...gasAlerts].reverse().map(s=>({
                    date:fmtDate(s.startTime).replace(/ \d{4}$/,""),
                    ppm:Math.round(s.peakGasPpm||0),
                    displayPpm:Math.min(Math.round(s.peakGasPpm||0),10000),
                  }))} margin={{top:8,right:8,left:-20,bottom:0}}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#111e15"/>
                    <XAxis dataKey="date" tick={{fontSize:9,fill:"#527a65"}}/>
                    <YAxis tick={{fontSize:9,fill:"#527a65"}} domain={[0,gasAlertMax]}/>
                    <Tooltip contentStyle={TT} formatter={(_,__,props)=>[`${props.payload?.ppm?.toLocaleString()} PPM`,"Peak Gas"]}/>
                    <Bar dataKey="displayPpm" name="Peak PPM" radius={[3,3,0,0]}>
                      {[...gasAlerts].reverse().map((s,i)=>(
                        <Cell key={i} fill={(s.peakGasPpm||0)>=5000?"#ff3333":"#ffa826"}/>
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="dash-card">
                <div className="dash-card-title">ALL ALERT SESSIONS<span className="dash-badge">{sortedAlerts.length}</span></div>
                <div className="dash-alert-list" style={{overflowY:"auto",maxHeight:420}}>
                  <div className="alert-list-hdr">
                    <span>DATE & TIME</span><span>OPERATOR</span><span>DURATION</span>
                    <span>PEAK GAS</span><span>LEVEL</span><span>DETECTIONS</span>
                  </div>
                  {sortedAlerts.map(s=>{ const g=gasLvl(s.peakGasPpm); const dc=Object.values(s.detections||{}).reduce((a,v)=>a+v,0); return(
                    <div key={s.id} className={`alert-list-row ${selected?.id===s.id?"selected":""}`} onClick={()=>setSelected(selected?.id===s.id?null:s)}>
                      <span>{fmtDate(s.startTime)} {fmtTime(s.startTime)}</span>
                      <span>{s.controllerName||"—"}</span>
                      <span>{fmtDur(s.duration)}</span>
                      <span style={{color:g.color,fontFamily:"var(--disp)",fontSize:14,fontWeight:700}}>
                        {(s.peakGasPpm||0).toLocaleString()} PPM
                      </span>
                      <span className={`gas-hdr-badge ${g.cls}`} style={{fontSize:10,padding:"2px 8px"}}>{g.txt}</span>
                      <span>{dc}</span>
                    </div>
                  );})}
                </div>
              </div>
            </>)}
            {selected&&<SessionDetail session={selected} style={{marginTop:14}}/>}
          </div>
        )}

        {/* ══ OPERATORS ══ */}
        {activeTab==="operators" && (<>
          <div className="dash-kpi-row">
            <KpiCard icon="◎" label="ACTIVE OPERATORS" value={operators.length} color="green"/>
            <KpiCard icon="◎" label="TOTAL SESSIONS"   value={sessions.length}  color="cyan"/>
            <KpiCard icon="◷" label="TOTAL DRIVE TIME" value={fmtDur(sessions.reduce((s,x)=>s+(x.duration||0),0))} color="amber"/>
            <KpiCard icon="◈" label="TOTAL DETECTIONS" value={sessions.reduce((s,x)=>s+Object.values(x.detections||{}).reduce((a,v)=>a+v,0),0)} color="cyan"/>
          </div>
          <div className="dash-charts-row">
            <div className="dash-card dash-card-md">
              <div className="dash-card-title">SESSIONS PER OPERATOR</div>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={operators.slice(0,8).map(o=>({name:o.name,sessions:o.sessions}))} margin={{top:8,right:8,left:-20,bottom:0}}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#111e15"/>
                  <XAxis dataKey="name" tick={{fontSize:9,fill:"#527a65"}}/>
                  <YAxis tick={{fontSize:9,fill:"#527a65"}} allowDecimals={false}/>
                  <Tooltip contentStyle={TT}/>
                  <Bar dataKey="sessions" fill="#00d4ff" radius={[3,3,0,0]} name="Sessions"/>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="dash-card dash-card-md">
              <div className="dash-card-title">DETECTIONS PER OPERATOR</div>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={operators.slice(0,8).map(o=>({name:o.name,dets:o.totalDets}))} margin={{top:8,right:8,left:-20,bottom:0}}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#111e15"/>
                  <XAxis dataKey="name" tick={{fontSize:9,fill:"#527a65"}}/>
                  <YAxis tick={{fontSize:9,fill:"#527a65"}} allowDecimals={false}/>
                  <Tooltip contentStyle={TT}/>
                  <Bar dataKey="dets" fill="#00ff88" radius={[3,3,0,0]} name="Detections"/>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="dash-card">
            <div className="dash-card-title">OPERATOR DETAILS</div>
            <div className="dash-alert-list">
              <div className="alert-list-hdr" style={{gridTemplateColumns:"2fr 1fr 1fr 1fr"}}>
                <span>OPERATOR</span><span>SESSIONS</span><span>TOTAL TIME</span><span>DETECTIONS</span>
              </div>
              {operators.map((o,i)=>(
                <div key={o.name} className="alert-list-row" style={{gridTemplateColumns:"2fr 1fr 1fr 1fr"}}>
                  <span style={{display:"flex",alignItems:"center",gap:8}}>
                    <span style={{width:20,height:20,borderRadius:"50%",background:PIE_COLORS[i%8],display:"flex",alignItems:"center",justifyContent:"center",fontFamily:"var(--disp)",fontSize:9,color:"#000",flexShrink:0}}>{i+1}</span>
                    {o.name}
                  </span>
                  <span style={{color:"var(--c)"}}>{o.sessions}</span>
                  <span>{fmtDur(o.totalDur)}</span>
                  <span style={{color:"var(--g)"}}>{o.totalDets}</span>
                </div>
              ))}
            </div>
          </div>
        </>)}
      </div>

      {/* ═══════════════════════════════════════════════════════════════════
          SCOPED HEADER STYLES — only affects this page via .dsh-hdr
          Zero font size changes anywhere.
          ═══════════════════════════════════════════════════════════════════ */}
      <style>{`
        /* Override dash-header fixed height for this page only */
        .dsh-hdr {
          height: auto !important;
          flex-direction: column !important;
          align-items: stretch !important;
          padding: 10px 22px 0 !important;
          gap: 0 !important;
        }

        /* Row 1 — brand left, actions right */
        .dsh-hdr-row1 {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 14px;
          padding-bottom: 10px;
          flex-wrap: nowrap;
        }
        .dsh-hdr-left {
          display: flex;
          align-items: center;
          gap: 14px;
          flex-shrink: 0;
        }
        .dsh-hdr-right {
          display: flex;
          align-items: center;
          gap: 10px;
          flex-wrap: nowrap;
          flex-shrink: 0;
        }

        /* Row 2 — tab strip, flush to bottom border */
        .dsh-hdr-tabs {
          display: flex;
          align-items: flex-end;
          gap: 2px;
          border-top: 1px solid var(--bdr);
          padding-top: 6px;
          padding-bottom: 0;
          overflow-x: auto;
          scrollbar-width: none;
        }
        .dsh-hdr-tabs::-webkit-scrollbar { display: none; }

        /* Tab active indicator sits flush on bottom edge of header */
        .dsh-hdr-tabs .dash-tab {
          border-radius: 3px 3px 0 0;
          border-bottom: 2px solid transparent;
          margin-bottom: -1px;          /* overlap the header bottom border */
          padding-bottom: 8px;
        }
        .dsh-hdr-tabs .dash-tab-active {
          border-bottom-color: var(--g) !important;
        }

        /* Clear data button */
        .dsh-clear-btn {
          padding: 5px 12px;
          border-radius: 4px;
          border: 1px solid #3a1010;
          background: #1a0808;
          color: #ff6666;
          font-family: var(--mono);
          font-size: 10px;
          letter-spacing: 1px;
          cursor: pointer;
          white-space: nowrap;
          flex-shrink: 0;
        }
        .dsh-clear-btn:hover {
          border-color: #ff4444;
          color: #ff4444;
          background: #2a0a0a;
        }
      `}</style>
    </div>
  );
}

function KpiCard({icon,label,value,color}){ return(<div className={`dash-kpi dash-kpi-${color}`}><div className="dash-kpi-icon">{icon}</div><div className="dash-kpi-val">{value}</div><div className="dash-kpi-label">{label}</div></div>); }
function WeekKpi({label,value,danger}){ return(<div className="week-kpi"><div className="week-kpi-val" style={{color:danger?"var(--r)":"var(--g)"}}>{value}</div><div className="week-kpi-lbl">{label}</div></div>); }
function MetaItem({label,val,cls}){ return(<div className="detail-meta-item"><div className="detail-meta-lbl">{label}</div><div className={`detail-meta-val ${cls||""}`}>{val}</div></div>); }

function SessionDetail({session:s}) {
  const dets=Object.entries(s.detections||{}).sort((a,b)=>b[1]-a[1]);
  const total=dets.reduce((sum,[,v])=>sum+v,0);
  const g=gasLvl(s.peakGasPpm);
  return(
    <div className="dash-card dash-detail" style={{marginTop:14}}>
      <div className="dash-card-title">SESSION DETAIL<span className="dash-detail-date">{`${fmtDate(s.startTime)} ${fmtTime(s.startTime)}`}</span></div>
      <div className="detail-meta-row">
        <MetaItem label="OPERATOR"   val={s.controllerName||"—"}/>
        <MetaItem label="DURATION"   val={fmtDur(s.duration)}/>
        <MetaItem label="DISTANCE"   val={s.peakDistanceM!=null?`${s.peakDistanceM.toFixed(2)} m`:"--"}/>
        <MetaItem label="PEAK GAS"   val={`${(s.peakGasPpm||0).toLocaleString()} PPM`} cls={g.cls}/>
        <MetaItem label="DETECTIONS" val={total}/>
      </div>
      {dets.length>0&&(<>
        <div className="detail-section-label">DETECTED OBJECTS</div>
        <div className="detail-dets-row">
          <ResponsiveContainer width="40%" height={140}>
            <PieChart><Pie data={dets.map(([n,v])=>({name:n,value:v}))} cx="50%" cy="50%" innerRadius={35} outerRadius={58} paddingAngle={2} dataKey="value">
              {dets.map((_,i)=><Cell key={i} fill={PIE_COLORS[i%8]} stroke="none"/>)}
            </Pie><Tooltip contentStyle={{...TT,fontSize:10}}/></PieChart>
          </ResponsiveContainer>
          <div className="detail-det-list">
            {dets.map(([lbl,cnt],i)=>(
              <div key={lbl} className="detail-det-item">
                <span className="detail-det-dot" style={{background:PIE_COLORS[i%8]}}/>
                <span className="detail-det-lbl">{lbl}</span>
                <span className="detail-det-cnt">×{cnt}</span>
                <div className="detail-det-bar"><div style={{width:`${Math.round(cnt/total*100)}%`,background:PIE_COLORS[i%8],height:"100%",borderRadius:2}}/></div>
              </div>
            ))}
          </div>
        </div>
      </>)}
    </div>
  );
}