// pages/DetectionLog.jsx — MANAGER ONLY
// Shows every individual detection event ever logged to Firebase.
// Each row: date, time, label, confidence, gas PPM, gas level, operator, session ID.
// Features: search/filter by label, date range, CSV download.

import { useState, useEffect, useMemo, useCallback } from "react";
import { ref, onValue, get, query, orderByChild, limitToLast } from "firebase/database";
import { db } from "../firebase";
import { useAuth } from "../contexts/AuthContext";
import { useNavigate } from "react-router-dom";

const fmtDate = (ms) => !ms ? "--" :
  new Date(ms).toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" });
const fmtTime = (ms) => !ms ? "--" :
  new Date(ms).toLocaleTimeString("en-GB", { hour:"2-digit", minute:"2-digit", second:"2-digit" });
const fmtDateTime = (ms) => !ms ? "--" : `${fmtDate(ms)} ${fmtTime(ms)}`;

const gasColor = (lvl) => ({
  SAFE:"#00ff88", LOW:"#00d4ff", WARNING:"#ffa826", DANGER:"#ff3333", OFFLINE:"#527a65",
}[lvl] || "#527a65");

const confColor = (c) => c >= 0.8 ? "#00ff88" : c >= 0.6 ? "#ffe033" : "#ff6b35";

// ── CSV helpers ──────────────────────────────────────────────────────────────
function escapeCsv(v) { return `"${String(v ?? "").replace(/"/g, '""')}"`; }
function buildCsvString(header, rows) {
  return [header, ...rows].map(r => r.map(escapeCsv).join(",")).join("\n");
}
function triggerDownload(csvStr, filename) {
  const blob = new Blob([csvStr], { type: "text/csv;charset=utf-8;" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

export default function DetectionLog() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [events,      setEvents]      = useState([]);
  const [loading,     setLoading]     = useState(true);
  const [search,      setSearch]      = useState("");
  const [gasFilter,   setGasFilter]   = useState("all");
  const [dateFrom,    setDateFrom]    = useState("");
  const [dateTo,      setDateTo]      = useState("");
  const [page,        setPage]        = useState(1);
  const [histLoading, setHistLoading] = useState(false);
  const PAGE_SIZE = 50;

  useEffect(() => {
    const q = query(ref(db, "detectionEvents"), orderByChild("timestamp"), limitToLast(2000));
    const unsub = onValue(q, snap => {
      if (!snap.exists()) { setEvents([]); setLoading(false); return; }
      const arr = [];
      snap.forEach(child => arr.push({ ...child.val(), id: child.key }));
      arr.sort((a, b) => b.timestamp - a.timestamp);
      setEvents(arr);
      setLoading(false);
    });
    return unsub;
  }, []);

  // ── Filtering ────────────────────────────────────────────────────────────
  const filtered = useMemo(() => {
    let out = events;
    if (search.trim()) {
      const s = search.trim().toLowerCase();
      out = out.filter(e =>
        (e.label||"").toLowerCase().includes(s) ||
        (e.controllerName||"").toLowerCase().includes(s) ||
        (e.sessionId||"").includes(s)
      );
    }
    if (gasFilter !== "all") {
      out = out.filter(e => (e.gasLevel||"OFFLINE").toLowerCase() === gasFilter);
    }
    if (dateFrom) {
      const from = new Date(dateFrom).getTime();
      out = out.filter(e => e.timestamp >= from);
    }
    if (dateTo) {
      const to = new Date(dateTo).getTime() + 86400000;
      out = out.filter(e => e.timestamp <= to);
    }
    return out;
  }, [events, search, gasFilter, dateFrom, dateTo]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const pageData   = filtered.slice((page-1)*PAGE_SIZE, page*PAGE_SIZE);
  useEffect(() => setPage(1), [search, gasFilter, dateFrom, dateTo]);

  // ── Live-view CSV (filtered events, columns per spec) ─────────────────────
  const downloadFilteredCSV = useCallback(() => {
    const header = [
      "Timestamp","Session_ID","Defect_Type","Confidence",
      "Avg_Temp","Gas_PPM","Gas_Level","Operator",
    ];
    const rows = filtered.map(e => [
      fmtDateTime(e.timestamp),
      e.sessionId   || "",
      e.label       || "",
      e.confidence  != null ? (e.confidence * 100).toFixed(1) + "%" : "",
      e.thermalAvgC != null ? e.thermalAvgC.toFixed(1) : "",
      e.gasPpm      != null ? e.gasPpm.toFixed(1)      : "",
      e.gasLevel    || "",
      e.controllerName || "",
    ]);
    triggerDownload(
      buildCsvString(header, rows),
      `viper-detections-${new Date().toISOString().slice(0,10)}.csv`,
    );
  }, [filtered]);

  // ── Full Mission History CSV ──────────────────────────────────────────────
  // Fetches ALL sessions + ALL detectionEvents from Firebase (no 2000-row cap).
  // Joins detectionEvents → sessions by sessionId to enrich each row with
  // session-level avgThermalC when the event-level reading is missing.
  //
  // Required columns:  Timestamp | Session_ID | Defect_Type | Confidence
  //                    Avg_Temp  | Gas_PPM
  //
  // Avg_Temp priority:
  //   1. event.thermalAvgC    (written by sessionLogger v3 at detection time)
  //   2. session.avgThermalC  (session average — flush every 15 s)
  //   3. ""                   (no thermal sensor data)
  const downloadMissionHistory = useCallback(async () => {
    setHistLoading(true);
    try {
      const [sessSnap, evSnap] = await Promise.all([
        get(ref(db, "sessions")),
        get(query(ref(db, "detectionEvents"), orderByChild("timestamp"))),
      ]);

      // Build sessions lookup
      const sessMap = {};
      if (sessSnap.exists()) {
        sessSnap.forEach(child => { sessMap[child.key] = { ...child.val(), id: child.key }; });
      }

      const allEvents = [];
      if (evSnap.exists()) {
        evSnap.forEach(child => allEvents.push({ ...child.val(), id: child.key }));
      }
      allEvents.sort((a, b) => (a.timestamp||0) - (b.timestamp||0));

      if (allEvents.length === 0 && Object.keys(sessMap).length > 0) {
        // No individual events recorded — fall back to session summary export
        const hdr = [
          "Session_ID","Start_Time","End_Time","Duration_s",
          "Operator","Total_Detections","Peak_Gas_PPM","Avg_Gas_PPM",
          "Avg_Temp","Status",
        ];
        const rows = Object.values(sessMap)
          .sort((a,b) => (a.startTime||0) - (b.startTime||0))
          .map(s => [
            s.id || "",
            fmtDateTime(s.startTime),
            fmtDateTime(s.endTime),
            s.duration ?? "",
            s.controllerName || "",
            Object.values(s.detections||{}).reduce((t,c)=>t+c, 0),
            s.peakGasPpm  != null ? s.peakGasPpm.toFixed(1)  : "",
            s.avgGasPpm   != null ? s.avgGasPpm.toFixed(1)   : "",
            s.avgThermalC != null ? s.avgThermalC.toFixed(1) : "",
            s.status || "",
          ]);
        triggerDownload(buildCsvString(hdr, rows),
          `viper-mission-history-${new Date().toISOString().slice(0,10)}.csv`);
        return;
      }

      // Full join: one row per detection event enriched with session data
      const header = [
        "Timestamp",
        "Session_ID",
        "Defect_Type",
        "Confidence",
        "Avg_Temp",
        "Gas_PPM",
        // Enrichment columns
        "Gas_Level",
        "Operator",
        "Session_Peak_Gas_PPM",
        "Session_Avg_Gas_PPM",
        "Session_Duration_s",
      ];
      const rows = allEvents.map(e => {
        const sess    = sessMap[e.sessionId] || {};
        const avgTemp = e.thermalAvgC    != null ? e.thermalAvgC.toFixed(1)
                      : sess.avgThermalC != null ? sess.avgThermalC.toFixed(1)
                      : "";
        return [
          fmtDateTime(e.timestamp),
          e.sessionId      || "",
          e.label          || "",
          e.confidence     != null ? (e.confidence * 100).toFixed(1) + "%" : "",
          avgTemp,
          e.gasPpm         != null ? e.gasPpm.toFixed(1) : "",
          e.gasLevel       || "",
          sess.controllerName || e.controllerName || "",
          sess.peakGasPpm  != null ? sess.peakGasPpm.toFixed(1) : "",
          sess.avgGasPpm   != null ? sess.avgGasPpm.toFixed(1)  : "",
          sess.duration    != null ? sess.duration               : "",
        ];
      });
      triggerDownload(buildCsvString(header, rows),
        `viper-mission-history-${new Date().toISOString().slice(0,10)}.csv`);
    } catch (err) {
      console.error("Mission history export failed:", err);
      alert("Export failed — check console for details.");
    } finally {
      setHistLoading(false);
    }
  }, []);

  // ── Label summary (top 8 across filtered events) ──────────────────────────
  const labelCounts = useMemo(() => {
    const m = {};
    filtered.forEach(e => { m[e.label||"?"] = (m[e.label||"?"]||0)+1; });
    return Object.entries(m).sort((a,b)=>b[1]-a[1]).slice(0,8);
  }, [filtered]);

  const PIE = ["#00ff88","#00d4ff","#ffa826","#ff3333","#b085ff","#ff6eb4","#39e0c0","#ffe033"];

  return (
    <div className="dash-shell">

      {/* ── HEADER ── */}
      <header className="dash-header">
        <div className="dash-header-left">
          <div className="dash-brand">
            <span className="dash-brand-v">VIPER</span>
            <span className="dash-brand-sub">NDT</span>
          </div>
          <div className="dash-role-badge">DETECTION LOG</div>
        </div>

        <div className="dash-header-center">
          <button className="dash-tab" onClick={() => navigate("/dashboard")}>
            ← DASHBOARD
          </button>
        </div>

        <div className="dash-header-right">
          <div className="dash-user">
            <span className="dash-user-dot"/>
            {user?.email}
            <span className="dash-user-role">MANAGER</span>
          </div>
          <button className="dash-logout"
            onClick={async () => { await logout(); navigate("/login"); }}>
            ⏻ LOGOUT
          </button>
        </div>
      </header>

      <div className="dash-body">

        {/* ── Label summary chips ── */}
        {labelCounts.length > 0 && (
          <div className="dl-label-row">
            {labelCounts.map(([lbl, cnt], i) => (
              <button key={lbl}
                className={`dl-label-chip ${search===lbl?"active":""}`}
                style={{ "--chip-color": PIE[i%8] }}
                onClick={() => setSearch(search===lbl?"":lbl)}
              >
                <span className="dl-chip-dot" style={{ background: PIE[i%8] }}/>
                {lbl.toUpperCase()}
                <span className="dl-chip-cnt">×{cnt}</span>
              </button>
            ))}
          </div>
        )}

        {/* ── Filter bar ── */}
        <div className="dl-filter-bar">
          <div className="dl-filter-left">
            <div className="dl-search-wrap">
              <span className="dl-search-icon">⌕</span>
              <input
                className="dl-search"
                type="text"
                placeholder="Search label, operator, session..."
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
              {search && (
                <button className="dl-search-clear" onClick={() => setSearch("")}>✕</button>
              )}
            </div>

            <div className="dl-gas-filter">
              {["all","safe","low","warning","danger"].map(f => (
                <button key={f}
                  className={`dl-gas-btn ${gasFilter===f?"active":""}`}
                  style={gasFilter===f ? { "--gc": gasColor(f.toUpperCase()) } : {}}
                  onClick={() => setGasFilter(f)}
                >
                  {f.toUpperCase()}
                </button>
              ))}
            </div>

            <div className="dl-date-range">
              <input type="date" className="dl-date-input" value={dateFrom}
                onChange={e => setDateFrom(e.target.value)} title="From date"/>
              <span className="dl-date-sep">→</span>
              <input type="date" className="dl-date-input" value={dateTo}
                onChange={e => setDateTo(e.target.value)} title="To date"/>
              {(dateFrom||dateTo) && (
                <button className="dl-search-clear"
                  onClick={() => { setDateFrom(""); setDateTo(""); }}>✕</button>
              )}
            </div>
          </div>

          <div className="dl-filter-right">
            <span className="dl-result-count">
              {filtered.length.toLocaleString()} event{filtered.length!==1?"s":""}
              {filtered.length < events.length ? ` of ${events.length.toLocaleString()}` : ""}
            </span>
            {/* Filtered view CSV — quick export of current results */}
            <button className="dl-csv-btn" onClick={downloadFilteredCSV} disabled={filtered.length===0}>
              ↓ EXPORT FILTERED
            </button>
            {/* Full history CSV — fetches ALL sessions + ALL events from Firebase */}
            <button
              className="dl-csv-btn dl-hist-btn"
              onClick={downloadMissionHistory}
              disabled={histLoading}
              title="Download complete mission history — joins all sessions with all detection events"
            >
              {histLoading
                ? <><span className="dl-spin">◌</span> FETCHING…</>
                : "⬡ DOWNLOAD MISSION HISTORY"
              }
            </button>
          </div>
        </div>

        {/* ── Table ── */}
        <div className="dash-card" style={{ padding:0, overflow:"hidden" }}>
          <div className="dl-table-header">
            <div className="dash-card-title" style={{ padding:"12px 16px" }}>
              ALL DETECTION EVENTS
              <span className="dash-badge">{filtered.length.toLocaleString()}</span>
            </div>
          </div>

          {loading ? (
            <div className="dash-empty">Loading detection events...</div>
          ) : filtered.length === 0 ? (
            <div className="dash-empty">
              {events.length === 0
                ? "No detection events recorded yet. Run the rover with AI Vision enabled."
                : "No events match your current filters."}
            </div>
          ) : (
            <>
              <div className="dl-table">
                {/* Head */}
                <div className="dl-row dl-head">
                  <span>DATE & TIME</span>
                  <span>LABEL</span>
                  <span>CONFIDENCE</span>
                  <span>GAS PPM</span>
                  <span>GAS LEVEL</span>
                  <span>AVG TEMP</span>
                  <span>OPERATOR</span>
                  <span>SESSION</span>
                </div>

                {/* Rows */}
                {pageData.map(e => {
                  const gc = gasColor(e.gasLevel||"OFFLINE");
                  const cc = confColor(e.confidence||0);
                  return (
                    <div key={e.id} className="dl-row">
                      <span className="dl-ts">
                        <span className="dl-date">{fmtDate(e.timestamp)}</span>
                        <span className="dl-time">{fmtTime(e.timestamp)}</span>
                      </span>
                      <span className="dl-label-cell">
                        <span className="dl-label-tag">{(e.label||"?").toUpperCase()}</span>
                      </span>
                      <span>
                        <span className="dl-conf" style={{ color:cc }}>
                          {e.confidence != null ? `${Math.round(e.confidence*100)}%` : "--"}
                        </span>
                      </span>
                      <span className="dl-ppm">
                        {e.gasPpm != null ? e.gasPpm.toFixed(1) : "--"}
                      </span>
                      <span>
                        <span className="dl-gas-lvl" style={{ color:gc, borderColor:gc, background:gc+"18" }}>
                          {e.gasLevel||"—"}
                        </span>
                      </span>
                      <span className="dl-temp">
                        {e.thermalAvgC != null ? `${e.thermalAvgC.toFixed(1)}°C` : "--"}
                      </span>
                      <span className="dl-op">{e.controllerName||"—"}</span>
                      <span className="dl-sess" title={e.sessionId}>
                        {e.sessionId?.slice(-6)||"—"}
                      </span>
                    </div>
                  );
                })}
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="dl-pagination">
                  <button className="dl-pg-btn" disabled={page<=1} onClick={()=>setPage(p=>p-1)}>
                    ← PREV
                  </button>
                  <span className="dl-pg-info">
                    Page {page} / {totalPages}
                    <span className="dl-pg-sub">
                      &nbsp;({((page-1)*PAGE_SIZE+1).toLocaleString()}–{Math.min(page*PAGE_SIZE,filtered.length).toLocaleString()} of {filtered.length.toLocaleString()})
                    </span>
                  </span>
                  <button className="dl-pg-btn" disabled={page>=totalPages} onClick={()=>setPage(p=>p+1)}>
                    NEXT →
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
