// StatusBar.jsx v5 — Pi CPU temperature meter + hardware stress integration
//
// Props:
//   piTemp        number|null  — Pi CPU temp in °C (null = server unreachable)
//   piTempStatus  string|null  — "ok" | "warning" | "critical"
//                                Forwarded by ai_server.py from Pi /health every 2 s.
//                                Falls back to local tempStatus() calc if absent.

function fmt(s) {
  if (s == null) return "00:00";
  const m   = Math.floor(s / 60).toString().padStart(2,"0");
  const sec = Math.floor(s % 60).toString().padStart(2,"0");
  return `${m}:${sec}`;
}

// ── CPU temperature colour thresholds ────────────────────────────────────────
// Green  < 55°C  (OPTIMAL)
// Yellow 55–70°C (WARNING — check ventilation, reduce load)
// Red    > 70°C  (CRITICAL — Pi throttling likely, inference FPS will drop)
function tempColor(c) {
  if (c == null)  return "#527a65";   // offline grey
  if (c > 70)     return "#ff3333";   // critical red
  if (c >= 55)    return "#ffe033";   // warning yellow
  return "#00ff88";                   // optimal green
}
function tempStatus(c) {
  if (c == null)  return "OFFLINE";
  if (c > 70)     return "CRITICAL";
  if (c >= 55)    return "WARNING";
  return "OPTIMAL";
}

export default function StatusBar({
  detections, gasData,
  piConnected, aiConnected, thermalOnline,
  thermalEnabled, aiEnabled,
  lastCmd, recStatus,
  piTemp,          // Pi CPU temperature in °C (null = not available)
  piTempStatus,    // "ok" | "warning" | "critical" — from Pi /health via ai_server
}) {
  const topDets = Object.values(
    (detections || []).reduce((acc, d) => {
      if (!acc[d.label] || d.confidence > acc[d.label].confidence) acc[d.label] = d;
      return acc;
    }, {})
  ).sort((a, b) => b.confidence - a.confidence).slice(0, 7);

  return (
    <div className="sb-panel">

      {/* ── System ── */}
      <div className="sb-section">
        <div className="sb-title">SYSTEM</div>
        <SBRow label="Pi Camera"  val={piConnected    ? "ONLINE"  : "OFFLINE"} ok={piConnected} />
        <SBRow label="AI Server"  val={aiConnected    ? "ONLINE"  : "OFFLINE"} ok={aiConnected} />
        <SBRow label="Thermal IR" val={thermalOnline  ? "ONLINE"  : "OFFLINE"} ok={thermalOnline} />
        <SBRow label="AI Vision"  val={aiEnabled      ? "ON"      : "OFF"}     ok={aiEnabled}     neutral={!aiEnabled} />
        <SBRow label="Thermal"    val={thermalEnabled ? "ON"      : "OFF"}     ok={thermalEnabled} neutral={!thermalEnabled} />
        <SBRow label="Drive"      val={lastCmd.toUpperCase()}                  ok={lastCmd !== "stop"} neutral={lastCmd === "stop"} />
      </div>

      {/* ── Pi CPU temperature ── */}
      <div className="sb-divider"/>
      <div className="sb-section">
        <div className="sb-title">PI HARDWARE HEALTH</div>
        {/* piTempStatus comes from Pi /health (computed on-device).
            Fall back to the local tempStatus() calculation for backward
            compatibility when talking to an older Pi firmware. */}
        <CpuTempMeter celsius={piTemp} serverStatus={piTempStatus} />
      </div>

      {/* ── Recording status ── */}
      {recStatus?.recording && (
        <>
          <div className="sb-divider"/>
          <div className="sb-section">
            <div className="sb-title">RECORDING</div>
            <div className="sb-rec-row">
              <span className="sb-rec-dot"/>
              <div className="sb-rec-info">
                <span className="sb-rec-time">
                  {fmt(recStatus.duration_s)} &nbsp;•&nbsp; {recStatus.frames?.toLocaleString()} frames
                </span>
                <span className="sb-rec-file">{recStatus.filename || "—"}</span>
              </div>
            </div>
          </div>
        </>
      )}

      <div className="sb-divider"/>

      {/* ── Gas ── */}
      <div className="sb-section">
        <div className="sb-title">GAS — MQ4 (CH₄)</div>
        <GasMeter gasData={gasData} />
      </div>

      <div className="sb-divider"/>

      {/* ── Detections ── */}
      <div className="sb-section">
        <div className="sb-title">
          DETECTIONS
          {topDets.length > 0 && (
            <span className="det-count-badge">{detections.length}</span>
          )}
        </div>
        {!aiConnected && <div className="sb-empty">AI server offline</div>}
        {aiConnected && !aiEnabled && <div className="sb-empty">AI Vision is OFF</div>}
        {aiConnected && aiEnabled && topDets.length === 0 && <div className="sb-empty">No objects detected</div>}
        {aiConnected && aiEnabled && topDets.map((d, i) => <DetRow key={i} d={d} />)}
      </div>

    </div>
  );
}

// ── CPU Temperature Meter ─────────────────────────────────────────────────────
// serverStatus: "ok"|"warning"|"critical"|null|undefined
//   When provided (from Pi /health via ai_server), it is used directly so the
//   Pi's own thresholds govern the display — the laptop and Pi always agree.
//   When absent (older firmware, offline), falls back to local tempStatus().
function CpuTempMeter({ celsius, serverStatus }) {
  const offline = celsius == null;
  const col     = tempColor(celsius);

  // Prefer server-computed status; derive locally as fallback
  const status  = serverStatus
    ? serverStatus.toUpperCase()
    : tempStatus(celsius);

  const isCrit  = status === "CRITICAL";
  const isWarn  = status === "WARNING";

  // Bar fills 0→90°C range, capped at 100%
  const barPct  = offline ? 0 : Math.min(100, (celsius / 90) * 100);

  return (
    <div className="cpu-temp-meter">
      {/* Value row */}
      <div className="cpu-temp-val-row">
        <span className="cpu-temp-val" style={{ color: offline ? "#2a3e35" : col }}>
          {offline ? "---" : celsius.toFixed(1)}
        </span>
        <span className="cpu-temp-unit">°C</span>
        <span className="cpu-temp-tag"
          style={{ color: col, borderColor: col, background: col + "1a",
                   animation: isCrit ? "pulse .7s ease-in-out infinite" : "none" }}>
          {status}
        </span>
      </div>

      {/* Bar */}
      <div className="cpu-temp-track">
        <div className="cpu-temp-fill" style={{
          width: `${barPct}%`,
          background: `linear-gradient(90deg, ${col}88, ${col})`,
          boxShadow:  offline ? "none" : `0 0 6px ${col}66`,
          transition: "width .6s ease, background .6s",
        }}/>
        {/* Threshold tick marks at 55° and 70° */}
        <div className="cpu-temp-tick" style={{ left: `${(55/90)*100}%` }} title="55°C — Warning"/>
        <div className="cpu-temp-tick" style={{ left: `${(70/90)*100}%` }} title="70°C — Critical"/>
      </div>

      {/* Axis labels */}
      <div className="cpu-temp-labels">
        <span>0°</span>
        <span style={{ color: "#ffe03388" }}>55°⚠</span>
        <span style={{ color: "#ff333388" }}>70°⛔</span>
        <span>90°C</span>
      </div>

      {/* Alert text when throttling risk */}
      {isCrit && (
        <div className="cpu-temp-alert" style={{ borderColor: col, color: col }}>
          ⚠ THROTTLING RISK — INFERENCE FPS MAY DROP
        </div>
      )}
      {isWarn && (
        <div className="cpu-temp-warn" style={{ color: col }}>
          ◈ Monitor temp — consider reducing motor load
        </div>
      )}
    </div>
  );
}

function GasMeter({ gasData }) {
  const { ppm, level, voltage, available } = gasData;
  const offline = !available || ppm === null;
  const col = {
    SAFE:"#00ff88", LOW:"#ffe033", WARNING:"#ff8c00", DANGER:"#ff2222", OFFLINE:"#2a3e35",
  }[level] || "#2a3e35";
  const barPct = offline ? 0 : Math.min(100, (ppm / 10000) * 100);
  return (
    <div className="gas-meter">
      <div className="gas-ppm-row">
        <span className="gas-ppm" style={{ color: offline ? "#2a3e35" : col }}>
          {offline ? "---" : Math.round(ppm).toLocaleString()}
        </span>
        <span className="gas-unit">PPM</span>
        <span className="gas-lv-tag" style={{ color:col, borderColor:col, background:col+"1a" }}>{level}</span>
      </div>
      <div className="gas-bar-track">
        <div className="gas-bar-fill" style={{
          width:`${barPct}%`,
          background:`linear-gradient(90deg,${col}88,${col})`,
          boxShadow: offline ? "none" : `0 0 8px ${col}66`,
        }}/>
        <div className="gas-mark" style={{ left:"10%" }}/>
        <div className="gas-mark" style={{ left:"50%" }}/>
      </div>
      <div className="gas-bar-labels">
        <span>0</span>
        <span style={{color:"#ffe03388"}}>1k⚠</span>
        <span style={{color:"#ff220088"}}>5k⛔</span>
        <span>10k</span>
      </div>
      <div className="gas-stats">
        <GasStat label="VOLTAGE" val={voltage !== null ? `${Number(voltage).toFixed(3)} V` : "---"} />
        <GasStat label="SENSOR"  val={`MQ4 ${available ? "✓" : "✗"}`} color={available?"#00ff88":"#ff4444"} />
      </div>
      {(level === "WARNING" || level === "DANGER") && (
        <div className="gas-alert" style={{ borderColor:col, color:col }}>
          ⚠ {level === "DANGER" ? "HIGH GAS — VENTILATE AREA" : "ELEVATED GAS LEVEL"}
        </div>
      )}
    </div>
  );
}

function GasStat({ label, val, color }) {
  return (
    <div className="gas-stat">
      <div className="gas-stat-lbl">{label}</div>
      <div className="gas-stat-val" style={color?{color}:{}}>{val}</div>
    </div>
  );
}
function SBRow({ label, val, ok, neutral }) {
  const cls = neutral ? "sb-neutral" : ok ? "sb-good" : "sb-bad";
  return (
    <div className="sb-row">
      <span className="sb-row-lbl">{label}</span>
      <span className={`sb-row-val ${cls}`}>{val}</span>
    </div>
  );
}
function DetRow({ d }) {
  const pct = Math.round(d.confidence * 100);
  const col = pct >= 80 ? "#00ff88" : pct >= 60 ? "#ffe033" : "#ff6b35";
  return (
    <div className="det-row">
      <div className="det-hdr">
        <span className="det-lbl">{d.label.toUpperCase()}</span>
        <span className="det-pct">{pct}%</span>
      </div>
      <div className="det-track">
        <div className="det-fill" style={{ width:`${pct}%`, background:col }}/>
      </div>
    </div>
  );
}
