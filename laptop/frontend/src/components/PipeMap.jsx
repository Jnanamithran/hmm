// components/PipeMap.jsx
// 1D pipe map — horizontal line showing distance travelled.
// Each detected defect is marked at its distance position with severity colour.

import { useMemo } from "react";

const SEV_COLOR = {
  CRITICAL: "#ff3333",
  MODERATE: "#ffa826",
  MINOR:    "#00ff88",
};

const LABEL_COLOR = {
  Crack:              "#ff3333",
  Buckling:           "#ffa826",
  Debris:             "#00d4ff",
  Hole:               "#ff6eb4",
  "Joint Offset":     "#b085ff",
  Obstacle:           "#ffe033",
  "Utility Intrusion":"#39e0c0",
};

export default function PipeMap({ detectionHistory, distanceM, maxDistM = null }) {
  // detectionHistory: [{label, severity, distance_m, timestamp}]

  const maxD = useMemo(() => {
    if (maxDistM) return maxDistM;
    const dists = detectionHistory.map(d => d.distance_m || 0);
    return Math.max(distanceM || 0, ...dists, 1.0);
  }, [detectionHistory, distanceM, maxDistM]);

  const W = 100;   // percentage width

  const roverPct = Math.min(100, ((distanceM || 0) / maxD) * 100);

  // Group overlapping markers (within 2% of each other)
  const markers = useMemo(() => {
    return detectionHistory.map(d => ({
      ...d,
      pct: Math.min(99, ((d.distance_m || 0) / maxD) * 100),
    }));
  }, [detectionHistory, maxD]);

  return (
    <div style={{ padding:"10px 0 4px" }}>
      <div style={{
        fontFamily:"var(--mono)",fontSize:9,letterSpacing:2,
        color:"var(--t2)",marginBottom:6,
      }}>
        PIPE MAP — {detectionHistory.length} DETECTION{detectionHistory.length!==1?"S":""}
        <span style={{float:"right"}}>{distanceM?.toFixed(2)}m / {maxD.toFixed(2)}m</span>
      </div>

      {/* Pipe tube */}
      <div style={{
        position:"relative",height:28,
        background:"#0a0f0a",
        border:"1px solid var(--bdr2)",borderRadius:14,
        overflow:"visible",
      }}>
        {/* Pipe fill (progress) */}
        <div style={{
          position:"absolute",top:0,left:0,
          width:`${roverPct}%`,height:"100%",
          background:"linear-gradient(90deg,#0a2010,#112a14)",
          borderRadius:14,transition:"width 0.3s",
        }}/>

        {/* Distance ticks */}
        {[0.25,0.5,0.75].map(t => (
          <div key={t} style={{
            position:"absolute",
            left:`${t*100}%`,top:0,
            width:1,height:"100%",
            background:"var(--bdr)",opacity:0.4,
          }}/>
        ))}

        {/* Detection markers */}
        {markers.map((m,i) => {
          const color = SEV_COLOR[m.severity] || LABEL_COLOR[m.label] || "#00ff88";
          return (
            <div key={i} title={`${m.label} (${m.severity}) @ ${(m.distance_m||0).toFixed(2)}m`}
              style={{
                position:"absolute",
                left:`${m.pct}%`,
                top:"50%",transform:"translate(-50%,-50%)",
                width:10,height:10,borderRadius:"50%",
                background:color,
                border:`2px solid ${color}`,
                boxShadow:`0 0 6px ${color}`,
                zIndex:2,cursor:"pointer",
                flexShrink:0,
              }}
            />
          );
        })}

        {/* Rover marker */}
        <div style={{
          position:"absolute",
          left:`${roverPct}%`,top:"50%",
          transform:"translate(-50%,-50%)",
          width:14,height:14,borderRadius:3,
          background:"#00ff88",
          border:"2px solid #00ff88",
          boxShadow:"0 0 8px #00ff88",
          zIndex:3,
          transition:"left 0.3s",
        }}/>
      </div>

      {/* Distance labels */}
      <div style={{display:"flex",justifyContent:"space-between",marginTop:3}}>
        <span style={{fontFamily:"var(--mono)",fontSize:8,color:"var(--t2)"}}>0m</span>
        <span style={{fontFamily:"var(--mono)",fontSize:8,color:"var(--t2)"}}>{(maxD/2).toFixed(1)}m</span>
        <span style={{fontFamily:"var(--mono)",fontSize:8,color:"var(--t2)"}}>{maxD.toFixed(1)}m</span>
      </div>

      {/* Legend */}
      {detectionHistory.length > 0 && (
        <div style={{
          display:"flex",flexWrap:"wrap",gap:"8px 14px",
          marginTop:8,
        }}>
          {["CRITICAL","MODERATE","MINOR"].map(sev => {
            const count = detectionHistory.filter(d=>d.severity===sev).length;
            if (!count) return null;
            return (
              <div key={sev} style={{display:"flex",alignItems:"center",gap:4}}>
                <div style={{
                  width:8,height:8,borderRadius:"50%",
                  background:SEV_COLOR[sev],flexShrink:0,
                }}/>
                <span style={{fontFamily:"var(--mono)",fontSize:9,color:"var(--t2)"}}>
                  {sev} ×{count}
                </span>
              </div>
            );
          })}
          <div style={{display:"flex",alignItems:"center",gap:4,marginLeft:"auto"}}>
            <div style={{width:10,height:10,borderRadius:2,background:"#00ff88",flexShrink:0}}/>
            <span style={{fontFamily:"var(--mono)",fontSize:9,color:"#00ff88"}}>ROVER</span>
          </div>
        </div>
      )}
    </div>
  );
}