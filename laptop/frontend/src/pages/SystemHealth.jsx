// pages/SystemHealth.jsx — CONTROLLER ONLY
// FIXED: template literal with ?? operator inside JSX attr (Babel parse error)
// NAVBAR FIX: header restructured into 2 rows so large fonts don't overflow

import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext.jsx";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

function tempMeta(c) {
  if (c == null) return { color: "var(--t2)", label: "NO DATA",  cls: "temp-none" };
  if (c > 70)    return { color: "var(--r)",  label: "CRITICAL", cls: "temp-crit" };
  if (c >= 55)   return { color: "var(--y)",  label: "WARNING",  cls: "temp-warn" };
  return               { color: "var(--g)",  label: "OPTIMAL",  cls: "temp-ok"   };
}
function pingMeta(ms) {
  if (ms == null) return { color: "var(--t2)", label: "OFFLINE"  };
  if (ms > 200)   return { color: "var(--r)",  label: "HIGH"     };
  if (ms > 80)    return { color: "var(--y)",  label: "MODERATE" };
  return                { color: "var(--g)",  label: "GOOD"     };
}

// Battery voltage → % for 7.4V 2S LiPo (8.4V full, 6.4V empty)
function batteryPct(voltage) {
  if (voltage == null) return null;
  return Math.max(0, Math.min(100, Math.round(((voltage - 6.4) / (8.4 - 6.4)) * 100)));
}
function batteryColor(pct) {
  if (pct == null) return "var(--t2)";
  if (pct <= 20)   return "var(--r)";
  if (pct <= 40)   return "var(--y)";
  return "var(--g)";
}

// ── Sparkline ─────────────────────────────────────────────────────────────────
function Sparkline({ values, color, width = 180, height = 40, min, max }) {
  if (!values || values.length < 2) return (
    <svg width={width} height={height} style={{ opacity: 0.3 }}>
      <line x1={0} y1={height/2} x2={width} y2={height/2} stroke={color} strokeWidth={1} strokeDasharray="4 4"/>
    </svg>
  );
  const lo  = min ?? Math.min(...values);
  const hi  = max ?? Math.max(...values);
  const rng = hi - lo || 1;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * width;
    const y = height - ((v - lo) / rng) * (height - 4) - 2;
    return `${x},${y}`;
  }).join(" ");
  const last  = values[values.length - 1];
  const lastX = width;
  const lastY = height - ((last - lo) / rng) * (height - 4) - 2;
  return (
    <svg width={width} height={height} style={{ overflow: "visible" }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round"/>
      <circle cx={lastX} cy={lastY} r={3} fill={color} style={{ filter: `drop-shadow(0 0 4px ${color})` }}/>
    </svg>
  );
}

// ── Temp gauge ────────────────────────────────────────────────────────────────
function TempGauge({ celsius, size = 140 }) {
  const meta   = tempMeta(celsius);
  const cx     = size / 2;
  const cy     = size / 2 + 10;
  const r      = size * 0.38;
  const stroke = size * 0.07;
  const startA = 210;
  const span   = 240;
  const pct    = celsius != null ? Math.min(1, Math.max(0, celsius / 90)) : 0;
  const fillA  = startA + span * pct;

  const toXY = (deg, radius) => {
    const rad = (deg - 90) * Math.PI / 180;
    return { x: cx + radius * Math.cos(rad), y: cy + radius * Math.sin(rad) };
  };
  const arcPath = (from, to, rad) => {
    const s  = toXY(from, rad);
    const e  = toXY(to, rad);
    const lg = (to - from) > 180 ? 1 : 0;
    return `M ${s.x} ${s.y} A ${rad} ${rad} 0 ${lg} 1 ${e.x} ${e.y}`;
  };

  return (
    <svg width={size} height={size * 0.8} viewBox={`0 0 ${size} ${size * 0.8}`}>
      <path d={arcPath(startA, startA + span, r)} fill="none" stroke="var(--bg3)" strokeWidth={stroke} strokeLinecap="round"/>
      {celsius != null && (
        <path d={arcPath(startA, fillA, r)} fill="none" stroke={meta.color} strokeWidth={stroke} strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 6px ${meta.color})` }}/>
      )}
      {[55, 70].map(t => {
        const a  = startA + (t / 90) * span;
        const p1 = toXY(a, r - stroke * 0.6);
        const p2 = toXY(a, r + stroke * 0.6);
        return <line key={t} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke="var(--bg4)" strokeWidth={1.5}/>;
      })}
      <text x={cx} y={cy - 2} textAnchor="middle" dominantBaseline="middle"
        style={{ fontFamily: "var(--disp)", fontSize: size * 0.18, fill: meta.color,
          filter: celsius != null ? `drop-shadow(0 0 8px ${meta.color})` : "none" }}>
        {celsius != null ? celsius.toFixed(1) : "--"}
      </text>
      <text x={cx} y={cy + size * 0.14} textAnchor="middle"
        style={{ fontFamily: "var(--mono)", fontSize: size * 0.07, fill: "var(--t2)", letterSpacing: 2 }}>
        {"°C  ·  CPU"}
      </text>
      <text x={cx} y={cy + size * 0.24} textAnchor="middle"
        style={{ fontFamily: "var(--disp)", fontSize: size * 0.075, fill: meta.color, letterSpacing: 3 }}>
        {meta.label}
      </text>
    </svg>
  );
}

// ── MetricBox ─────────────────────────────────────────────────────────────────
function MetricBox({ icon, label, value, unit, color, sublabel, alert, children }) {
  return (
    <div className="sh-metric" style={{ "--mc": color || "var(--g)" }}>
      <div className="sh-metric-icon">{icon}</div>
      <div className="sh-metric-body">
        <div className="sh-metric-label">{label}</div>
        <div className="sh-metric-val" style={{ color: color || "var(--g)",
          textShadow: color ? `0 0 12px ${color}66` : undefined }}>
          {value ?? "--"}{unit && <span className="sh-metric-unit">{unit}</span>}
        </div>
        {sublabel && <div className="sh-metric-sub">{sublabel}</div>}
        {alert && (
          <div className="sh-alert-pill">
            <span className="sh-alert-dot"/>
            {alert}
          </div>
        )}
      </div>
      {children}
    </div>
  );
}

// ── SensorRow ─────────────────────────────────────────────────────────────────
function SensorRow({ label, online, detail }) {
  return (
    <div className="sh-sensor-row">
      <span className={`sh-sensor-dot ${online ? "up" : "down"}`}/>
      <span className="sh-sensor-label">{label}</span>
      {detail && <span className="sh-sensor-detail">{detail}</span>}
      <span className={`sh-sensor-status ${online ? "up" : "down"}`}>
        {online ? "ONLINE" : "OFFLINE"}
      </span>
    </div>
  );
}

// ── BatteryBar ────────────────────────────────────────────────────────────────
function BatteryBar({ pct, voltage, available }) {
  const color = batteryColor(pct);
  const isLow = pct != null && pct <= 20;
  const fillW = pct != null ? Math.round(36 * (pct / 100)) : 0;
  const statusText = pct == null ? "NO SENSOR"
    : pct <= 20 ? "LOW — CHARGE NOW"
    : pct <= 40 ? "MODERATE"
    : pct <= 70 ? "GOOD"
    : "FULL";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        {/* SVG battery icon */}
        <svg width={52} height={26} viewBox="0 0 52 26">
          <rect x={1} y={3} width={43} height={20} rx={3} fill="none" stroke={color} strokeWidth={1.5}/>
          <rect x={44} y={9} width={6} height={8} rx={1} fill={color}/>
          {pct != null && (
            <rect x={3} y={5} width={fillW} height={16} rx={2} fill={color}
              style={{ filter: `drop-shadow(0 0 4px ${color})` }}/>
          )}
        </svg>
        <div style={{ fontFamily: "var(--disp)", fontSize: 30, fontWeight: 700, color, lineHeight: 1,
          filter: `drop-shadow(0 0 8px ${color})` }}>
          {pct != null ? `${pct}%` : "--"}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--t1)" }}>
            {voltage != null ? `${voltage.toFixed(2)} V` : "-- V"}
          </div>
          <div style={{ fontFamily: "var(--mono)", fontSize: 9, color, letterSpacing: 1 }}>
            {statusText}
          </div>
        </div>
      </div>

      {isLow && (
        <div className="sh-alert-pill" style={{ width: "fit-content" }}>
          <span className="sh-alert-dot"/>
          BATTERY LOW — RETURN TO BASE
        </div>
      )}

      {!available && (
        <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--t2)", lineHeight: 1.8 }}>
          No battery sensor detected. Connect INA219 to Pi I2C and add <span style={{ color: "var(--g)" }}>/battery</span> endpoint returning voltage_v.
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
export default function SystemHealth() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [health,     setHealth]     = useState(null);
  const [connected,  setConnected]  = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [battery,    setBattery]    = useState({ voltage: null, pct: null, available: false });

  const HIST = 60;
  const tempHistRef = useRef([]);
  const pingHistRef = useRef([]);
  const [tempHist, setTempHist] = useState([]);
  const [pingHist, setPingHist] = useState([]);

  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/health`, { signal: AbortSignal.timeout(2000) });
        if (r.ok) {
          const h = await r.json();
          setHealth(h);
          setConnected(true);
          setLastUpdate(new Date());

          if (h.pi_temp != null) {
            tempHistRef.current = [...tempHistRef.current.slice(-(HIST - 1)), h.pi_temp];
            setTempHist([...tempHistRef.current]);
          }
          if (h.ping_ms != null) {
            pingHistRef.current = [...pingHistRef.current.slice(-(HIST - 1)), h.ping_ms];
            setPingHist([...pingHistRef.current]);
          }
          // Battery from Pi health endpoint
          if (h.battery_voltage != null) {
            const pct = batteryPct(h.battery_voltage);
            setBattery({ voltage: h.battery_voltage, pct, available: true });
          }
        } else {
          setConnected(false);
        }
      } catch {
        setConnected(false);
      }
    };
    poll();
    const id = setInterval(poll, 1000);
    return () => clearInterval(id);
  }, []);

  const piTemp     = health?.pi_temp     ?? null;
  const pingMs     = health?.ping_ms     ?? null;
  const tMeta      = tempMeta(piTemp);
  const pMeta      = pingMeta(pingMs);
  const isCrit     = piTemp != null && piTemp > 70;
  const isWarn     = piTemp != null && piTemp >= 55 && piTemp <= 70;
  const thermalAvg = health?.thermal_avg_c ?? null;
  const thermalMin = health?.thermal_min_c ?? null;
  const thermalMax = health?.thermal_max_c ?? null;
  const gasPpm     = health?.gas?.ppm   ?? null;
  const gasLevel   = health?.gas?.level ?? "OFFLINE";
  const speedKmh   = health?.speed_kmh  ?? null;

  // ── FIX: extract ping detail string outside JSX to avoid ?? in template ───
  const pingDetail = pingMs != null ? `ping ${pingMs.toFixed(0)} ms` : "not reachable";
  const piLinkDetail = health?.pi_connected ? pingDetail : "not reachable";

  return (
    <div className="dash-shell">

      {/* ── HEADER — 2-row layout so large fonts never overflow ─────────────
           Row 1 (top)   : brand + page badge  ·  action buttons
           Row 2 (bottom): live status dot + timestamp  ·  optional speed badge
      ──────────────────────────────────────────────────────────────────────── */}
      <header className="dash-header sh-hdr">

        {/* ── ROW 1 ── */}
        <div className="sh-hdr-row1">

          {/* Left — brand + page label */}
          <div className="sh-hdr-brand-group">
            <div className="dash-brand">
              <span className="dash-brand-v">VIPER</span>
              <span className="dash-brand-sub">NDT</span>
            </div>
            <div className="dash-role-badge sh-page-badge">SYSTEM HEALTH</div>
          </div>

          {/* Right — nav buttons */}
          <div className="sh-hdr-actions">
            <button className="dash-tab" onClick={() => navigate("/control")}>
              {"← CONTROL ROOM"}
            </button>
            <button
              className="dash-logout"
              onClick={async () => { await logout(); navigate("/login"); }}
            >
              {"⏻ LOGOUT"}
            </button>
          </div>

        </div>

        {/* ── ROW 2 — live status + optional speed ── */}
        <div className="sh-hdr-row2">
          <div className="sh-live-row">
            <span className={`sh-live-dot ${connected ? "up" : "down"}`}/>
            <span className="sh-live-label">
              {connected
                ? `LIVE · ${lastUpdate?.toLocaleTimeString("en-GB") ?? ""}`
                : "NO SERVER CONNECTION"}
            </span>
          </div>

          {speedKmh != null && (
            <div className="sh-speed-badge">
              {"⟷"} {speedKmh.toFixed(2)} km/h
            </div>
          )}
        </div>

      </header>

      {/* Banners */}
      {isCrit && (
        <div className="sh-crit-banner">
          <span className="sh-crit-icon">{"⚠"}</span>
          {`THROTTLING RISK — CPU TEMPERATURE ${piTemp?.toFixed(1)}°C EXCEEDS 70°C`}
          <span className="sh-crit-icon">{"⚠"}</span>
        </div>
      )}
      {isWarn && !isCrit && (
        <div className="sh-warn-banner">
          <span>{"◈"}</span>
          {`TEMPERATURE WARNING — ${piTemp?.toFixed(1)}°C · Monitor CPU load`}
        </div>
      )}

      {/* BODY */}
      <div className="dash-body sh-body">

        {/* Row 1 — CPU + ping + thermal + gas */}
        <div className="sh-top-row">

          <div className="dash-card sh-gauge-card">
            <div className="dash-card-title">{"⬡ CPU TEMPERATURE"}</div>
            <div className="sh-gauge-wrap">
              <TempGauge celsius={piTemp} size={160}/>
            </div>
            <div className="sh-thresh-row">
              {[
                { c: "var(--g)", l: "<55°C",  t: "OPTIMAL"  },
                { c: "var(--y)", l: "55–70°C", t: "WARNING" },
                { c: "var(--r)", l: ">70°C",  t: "CRITICAL" },
              ].map(x => (
                <div key={x.t} className="sh-thresh">
                  <span className="sh-thresh-dot" style={{ background: x.c }}/>
                  <span className="sh-thresh-lbl">{x.l}</span>
                  <span className="sh-thresh-tag" style={{ color: x.c }}>{x.t}</span>
                </div>
              ))}
            </div>
            <div className="sh-sparkline-wrap">
              <div className="sh-spark-label">60s HISTORY</div>
              <Sparkline values={tempHist} color={tMeta.color} width={220} height={44} min={30} max={90}/>
            </div>
          </div>

          <div className="dash-card sh-side-col">
            <MetricBox
              icon="◌"
              label="NETWORK PING  (PI → LAPTOP)"
              value={pingMs != null ? pingMs.toFixed(1) : null}
              unit=" ms"
              color={pMeta.color}
              sublabel={pMeta.label}
              alert={pingMs != null && pingMs > 200 ? "HIGH LATENCY — CONTROL LAG POSSIBLE" : null}
            >
              <div className="sh-sparkline-wrap" style={{ marginTop: 6 }}>
                <div className="sh-spark-label">60s HISTORY</div>
                <Sparkline values={pingHist} color={pMeta.color} width={220} height={36} min={0}/>
              </div>
            </MetricBox>

            <div className="sh-divider"/>
            <div className="dash-card-title" style={{ marginTop: 2 }}>{"◈ THERMAL SCENE"}</div>
            <div className="sh-thermal-row">
              <MetricBox icon="↓" label="MIN" value={thermalMin?.toFixed(1)} unit="°C" color="var(--c)"/>
              <MetricBox icon="◎" label="AVG" value={thermalAvg?.toFixed(1)} unit="°C" color="var(--g)"/>
              <MetricBox icon="↑" label="MAX" value={thermalMax?.toFixed(1)} unit="°C" color="var(--o)"/>
            </div>

            <div className="sh-divider"/>
            <MetricBox
              icon="◈"
              label="GAS SENSOR  (MQ4 · CH4)"
              value={gasPpm != null ? Math.round(gasPpm) : null}
              unit=" PPM"
              color={gasLevel === "DANGER" ? "var(--r)" : gasLevel === "WARNING" ? "var(--o)" : "var(--g)"}
              sublabel={gasLevel}
              alert={gasLevel === "DANGER" ? "DANGEROUS GAS LEVEL DETECTED" : null}
            />
          </div>
        </div>

        {/* Battery row */}
        <div className="dash-card">
          <div className="dash-card-title">
            {"⚡ BATTERY STATUS"}
            <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--t2)", marginLeft: 8 }}>
              {battery.available ? "INA219 sensor" : "No sensor — connect INA219 for live readings"}
            </span>
          </div>
          <BatteryBar pct={battery.pct} voltage={battery.voltage} available={battery.available}/>
        </div>

        {/* Hardware status */}
        <div className="dash-card sh-sensors-card">
          <div className="dash-card-title">{"◎ HARDWARE STATUS"}</div>
          <div className="sh-sensors-grid">
            <SensorRow label="Pi → Laptop Link"   online={health?.pi_connected}     detail={piLinkDetail}/>
            <SensorRow label="USB Camera"          online={health?.pi_camera_open}   detail="640 × 480  ·  /dev/video0"/>
            <SensorRow label="MLX90640 Thermal"   online={health?.pi_thermal_sensor} detail="32×24 · 2 Hz · I2C 0x33"/>
            <SensorRow label="MQ4 Gas Sensor"     online={health?.pi_gas_sensor}     detail="ADS1115 · I2C 0x48 · A0"/>
            <SensorRow label="AI Server (YOLO)"   online={health?.ai_enabled}        detail="viper_pipe_v1 · conf=0.10"/>
            <SensorRow label="Thermal Blend"      online={health?.thermal_enabled}   detail={health?.thermal_enabled ? "INFERNO colormap" : "disabled"}/>
            <SensorRow label="NDT Crack Analysis" online={health?.crack_enabled}     detail="OpenCV · CLAHE → Canny"/>
            <SensorRow label="Video Recording"    online={health?.recording?.recording}
              detail={health?.recording?.recording
                ? `${health.recording.filename ?? ""} · ${health.recording.duration_s?.toFixed(0) ?? 0}s`
                : "idle"}/>
            <SensorRow label="Battery Sensor"     online={battery.available}
              detail={battery.available ? `INA219 · ${battery.voltage?.toFixed(2)}V` : "Not connected"}/>
          </div>
        </div>

        {/* NDT defect */}
        {health?.defect && (
          <div className="dash-card sh-defect-card">
            <div className="dash-card-title">
              {"⬡ ACTIVE NDT DEFECT STATUS"}
              {health.defect.worst_severity !== "NONE" && (
                <span className="sh-sev-badge" data-sev={health.defect.worst_severity}>
                  {health.defect.worst_severity}
                </span>
              )}
            </div>
            <div className="sh-defect-row">
              <MetricBox icon="⬡" label="TOTAL CRACKS"  value={health.defect.crack_count}    color="var(--c)"/>
              <MetricBox icon="▲" label="CRITICAL"       value={health.defect.critical_count}
                color={health.defect.critical_count > 0 ? "var(--r)" : "var(--t2)"}/>
              <MetricBox icon="◈" label="MAX WIDTH"      value={health.defect.max_width_mm?.toFixed(1)}  unit=" mm" color="var(--o)"/>
              <MetricBox icon="◌" label="MAX LENGTH"     value={health.defect.max_length_mm?.toFixed(1)} unit=" mm" color="var(--y)"/>
            </div>
          </div>
        )}

      </div>

      <style>{`
        /* ── NAVBAR 2-ROW OVERRIDE ─────────────────────────────────────────────
           Overrides .dash-header's fixed 64px height only on this page.
           Row 1: brand group + action buttons (space-between)
           Row 2: live dot + timestamp + optional speed badge
        ──────────────────────────────────────────────────────────────────────── */
        .sh-hdr {
          height: auto !important;
          flex-direction: column !important;
          align-items: stretch !important;
          padding: 10px 22px !important;
          gap: 0 !important;
        }

        /* Row 1 ── brand ↔ buttons */
        .sh-hdr-row1 {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 14px;
          flex-wrap: nowrap;
        }
        .sh-hdr-brand-group {
          display: flex;
          align-items: center;
          gap: 14px;
          flex-shrink: 0;
        }
        .sh-hdr-actions {
          display: flex;
          align-items: center;
          gap: 10px;
          flex-shrink: 0;
        }

        /* Row 2 ── live status strip */
        .sh-hdr-row2 {
          display: flex;
          align-items: center;
          gap: 14px;
          margin-top: 8px;
          padding-top: 8px;
          border-top: 1px solid var(--bdr);
          flex-wrap: wrap;
        }

        /* Speed badge (was inline style, now a proper class) */
        .sh-speed-badge {
          font-family: var(--mono);
          font-size: 11px;
          color: #00d4ff;
          letter-spacing: 2px;
          padding: 4px 10px;
          border: 1px solid #0a2a3a;
          border-radius: 4px;
          background: #080d14;
        }

        /* ── rest of SystemHealth styles (unchanged) ────────────────────── */
        .sh-page-badge{background:rgba(0,212,255,0.08);border-color:var(--cd);color:var(--c);}
        .sh-live-row{display:flex;align-items:center;gap:7px;}
        .sh-live-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;}
        .sh-live-dot.up{background:var(--g);box-shadow:var(--sg);animation:pulse 2s ease-in-out infinite;}
        .sh-live-dot.down{background:var(--r);}
        .sh-live-label{font-family:var(--mono);font-size:10px;letter-spacing:2px;color:var(--t1);}
        .sh-crit-banner{display:flex;align-items:center;justify-content:center;gap:12px;padding:9px 20px;background:rgba(255,51,51,0.12);border-bottom:2px solid var(--r);font-family:var(--mono);font-size:11px;letter-spacing:1.5px;color:var(--r);animation:pulse .8s ease-in-out infinite;}
        .sh-warn-banner{display:flex;align-items:center;justify-content:center;gap:10px;padding:7px 20px;background:rgba(255,224,51,0.07);border-bottom:1px solid var(--yd);font-family:var(--mono);font-size:10px;letter-spacing:1.5px;color:var(--y);}
        .sh-crit-icon{font-size:14px;}
        .sh-body{display:flex;flex-direction:column;gap:12px;padding:14px 16px;}
        .sh-top-row{display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap;}
        .sh-gauge-card{min-width:240px;flex:0 0 auto;align-items:center;}
        .sh-side-col{flex:1;min-width:280px;gap:10px;}
        .sh-thermal-row{display:flex;gap:8px;}
        .sh-gauge-wrap{display:flex;justify-content:center;padding:4px 0;}
        .sh-thresh-row{display:flex;gap:12px;justify-content:center;flex-wrap:wrap;}
        .sh-thresh{display:flex;align-items:center;gap:5px;}
        .sh-thresh-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;}
        .sh-thresh-lbl{font-family:var(--mono);font-size:9px;color:var(--t2);}
        .sh-thresh-tag{font-family:var(--mono);font-size:9px;letter-spacing:1px;}
        .sh-sparkline-wrap{display:flex;flex-direction:column;gap:4px;}
        .sh-spark-label{font-family:var(--mono);font-size:8px;letter-spacing:2px;color:var(--t2);}
        .sh-metric{display:flex;align-items:flex-start;gap:10px;padding:10px 12px;background:var(--bg2);border:1px solid var(--bdr2);border-radius:3px;border-left:2px solid var(--mc);}
        .sh-metric-icon{font-size:16px;color:var(--mc);margin-top:2px;flex-shrink:0;}
        .sh-metric-body{flex:1;display:flex;flex-direction:column;gap:3px;}
        .sh-metric-label{font-family:var(--mono);font-size:8px;letter-spacing:2px;color:var(--t2);}
        .sh-metric-val{font-family:var(--disp);font-size:22px;font-weight:700;line-height:1;}
        .sh-metric-unit{font-family:var(--mono);font-size:11px;margin-left:3px;}
        .sh-metric-sub{font-family:var(--mono);font-size:9px;color:var(--t1);letter-spacing:2px;}
        .sh-alert-pill{display:inline-flex;align-items:center;gap:5px;margin-top:4px;padding:3px 8px;border-radius:2px;background:rgba(255,51,51,0.1);border:1px solid var(--rd);font-family:var(--mono);font-size:9px;color:var(--r);letter-spacing:1px;animation:pulse .8s ease-in-out infinite;}
        .sh-alert-dot{width:5px;height:5px;border-radius:50%;background:var(--r);flex-shrink:0;}
        .sh-divider{height:1px;background:var(--bdr);margin:4px 0;}
        .sh-sensors-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:6px;}
        .sh-sensor-row{display:flex;align-items:center;gap:8px;padding:7px 10px;background:var(--bg2);border:1px solid var(--bdr);border-radius:3px;font-family:var(--mono);font-size:10px;}
        .sh-sensor-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;}
        .sh-sensor-dot.up{background:var(--g);box-shadow:var(--sg);animation:pulse 2s ease-in-out infinite;}
        .sh-sensor-dot.down{background:var(--rd);}
        .sh-sensor-label{flex:1;color:var(--t0);}
        .sh-sensor-detail{color:var(--t2);font-size:9px;}
        .sh-sensor-status{font-size:9px;letter-spacing:1.5px;padding:1px 5px;border-radius:2px;border:1px solid;flex-shrink:0;}
        .sh-sensor-status.up{color:var(--g);border-color:var(--gd);background:var(--gg);}
        .sh-sensor-status.down{color:var(--t2);border-color:var(--bdr);background:transparent;}
        .sh-defect-card{}
        .sh-defect-row{display:flex;gap:8px;flex-wrap:wrap;}
        .sh-defect-row .sh-metric{flex:1;min-width:120px;}
        .sh-sev-badge{font-family:var(--mono);font-size:9px;letter-spacing:2px;padding:2px 8px;border-radius:2px;border:1px solid;}
        .sh-sev-badge[data-sev="CRITICAL"]{color:var(--r);border-color:var(--rd);background:var(--rg);animation:pulse .8s ease-in-out infinite;}
        .sh-sev-badge[data-sev="MODERATE"]{color:var(--o);border-color:var(--od);background:var(--og);}
        .sh-sev-badge[data-sev="MINOR"]{color:var(--g);border-color:var(--gd);background:var(--gg);}
      `}</style>
    </div>
  );
}