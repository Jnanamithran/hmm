// components/Analytics.jsx — in-session analytics tab for controller
// Shows: detection breakdown pie, gas PPM timeline, top detections list

import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
  LineChart, Line, XAxis, YAxis, CartesianGrid,
} from "recharts";

const PIE_COLORS = [
  "#00ff88", "#00d4ff", "#ffa826", "#ff3333",
  "#b085ff", "#ff6eb4", "#39e0c0", "#ffe033",
];

function msToMin(ms) {
  return (ms / 60000).toFixed(1);
}

export default function Analytics({ session, detections, gasReadings }) {
  // Build pie data from lifetime detection counts
  const detEntries = Object.entries(session?.detections || {});
  const pieData = detEntries.map(([label, count]) => ({ name: label, value: count }));

  // Build gas line data (sample last 60 readings for display)
  const gasLine = (gasReadings || []).slice(-60).map(r => ({
    t:   msToMin(r.t),
    ppm: Math.round(r.ppm),
  }));

  // Top current detections (live from YOLO)
  const topDets = Object.values(
    (detections || []).reduce((acc, d) => {
      if (!acc[d.label] || d.confidence > acc[d.label].confidence) acc[d.label] = d;
      return acc;
    }, {})
  ).sort((a, b) => b.confidence - a.confidence).slice(0, 8);

  const totalDets = detEntries.reduce((s, [, c]) => s + c, 0);

  return (
    <div className="analytics-panel">

      {/* ── Session summary ── */}
      <div className="an-section">
        <div className="an-title">SESSION SUMMARY</div>
        <div className="an-stats-row">
          <div className="an-stat">
            <div className="an-stat-val">{totalDets}</div>
            <div className="an-stat-lbl">TOTAL DETECTIONS</div>
          </div>
          <div className="an-stat">
            <div className="an-stat-val">{detEntries.length}</div>
            <div className="an-stat-lbl">OBJECT TYPES</div>
          </div>
          <div className="an-stat">
            <div className="an-stat-val an-stat-gas">
              {session?.peakGasPpm != null ? `${session.peakGasPpm.toFixed(0)}` : "--"}
            </div>
            <div className="an-stat-lbl">PEAK GAS PPM</div>
          </div>
          <div className="an-stat">
            <div className="an-stat-val">
              {session?.avgGasPpm != null ? `${session.avgGasPpm.toFixed(0)}` : "--"}
            </div>
            <div className="an-stat-lbl">AVG GAS PPM</div>
          </div>
        </div>
      </div>

      {/* ── Detection pie ── */}
      {pieData.length > 0 && (
        <div className="an-section">
          <div className="an-title">DETECTION BREAKDOWN</div>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie
                data={pieData}
                cx="50%" cy="50%"
                innerRadius={50} outerRadius={80}
                paddingAngle={3}
                dataKey="value"
              >
                {pieData.map((_, i) => (
                  <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} stroke="none"/>
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ background: "#090d14", border: "1px solid #1a3020", color: "#cce8dc", fontSize: 11 }}
                formatter={(v, n) => [v, n]}
              />
              <Legend
                wrapperStyle={{ fontSize: 10, color: "#527a65" }}
                iconType="circle" iconSize={8}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Gas timeline ── */}
      {gasLine.length > 1 && (
        <div className="an-section">
          <div className="an-title">GAS LEVEL TIMELINE (PPM)</div>
          <ResponsiveContainer width="100%" height={140}>
            <LineChart data={gasLine} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#111e15" />
              <XAxis dataKey="t" tick={{ fontSize: 9, fill: "#527a65" }} label={{ value: "min", position: "insideRight", fill: "#527a65", fontSize: 9 }} />
              <YAxis tick={{ fontSize: 9, fill: "#527a65" }} />
              <Tooltip
                contentStyle={{ background: "#090d14", border: "1px solid #1a3020", color: "#cce8dc", fontSize: 11 }}
                formatter={(v) => [`${v} PPM`, "Gas"]}
              />
              <Line type="monotone" dataKey="ppm" stroke="#ffa826" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Live detections list ── */}
      <div className="an-section">
        <div className="an-title">
          LIVE DETECTIONS
          {topDets.length > 0 && (
            <span className="det-count-badge">{topDets.length}</span>
          )}
        </div>
        {topDets.length === 0 ? (
          <div className="sb-empty">NO OBJECTS IN FRAME</div>
        ) : (
          topDets.map((d, i) => (
            <div key={i} className="det-row">
              <div className="det-hdr">
                <span className="det-lbl">{d.label?.toUpperCase()}</span>
                <span className="det-pct">{Math.round((d.confidence || 0) * 100)}%</span>
              </div>
              <div className="det-track">
                <div className="det-fill" style={{
                  width: `${Math.round((d.confidence||0)*100)}%`,
                  background: PIE_COLORS[i % PIE_COLORS.length],
                }}/>
              </div>
            </div>
          ))
        )}
      </div>

      {/* ── All-time detection counts ── */}
      {detEntries.length > 0 && (
        <div className="an-section">
          <div className="an-title">SESSION TOTALS</div>
          {detEntries.sort((a, b) => b[1] - a[1]).map(([lbl, cnt], i) => (
            <div key={lbl} className="det-row">
              <div className="det-hdr">
                <span className="det-lbl">{lbl.toUpperCase()}</span>
                <span className="det-pct">×{cnt}</span>
              </div>
              <div className="det-track">
                <div className="det-fill" style={{
                  width: `${Math.round(cnt / Math.max(...detEntries.map(e=>e[1])) * 100)}%`,
                  background: PIE_COLORS[i % PIE_COLORS.length],
                }}/>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
