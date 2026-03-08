// StatusBar.jsx v4 — fixed prop names: aiEnabled / thermalEnabled (was aiOverlay/thermalOverlay)

function fmt(s) {
  if (s == null) return "00:00";
  const m   = Math.floor(s / 60).toString().padStart(2,"0");
  const sec = Math.floor(s % 60).toString().padStart(2,"0");
  return `${m}:${sec}`;
}

export default function StatusBar({
  detections, gasData,
  piConnected, aiConnected, thermalOnline,
  thermalEnabled, aiEnabled,   // ← fixed: was aiOverlay / thermalOverlay
  lastCmd, recStatus,
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
