// VideoFeed.jsx  v4
// Single <img> — thermal blending is done server-side by ai_server.py
// No CSS overlay needed. Cleaner, recorded correctly, no blend mode issues.

import { useState } from "react";

export default function VideoFeed({
  streamUrl,
  piConnected, aiEnabled, thermalEnabled, thermalOnline,
  isRecording,
}) {
  const [loaded,  setLoaded]  = useState(false);
  const [errored, setErrored] = useState(false);
  const live = piConnected && !errored;

  return (
    <div className="vid-outer">
      {/* HUD corners */}
      <span className="hud-corner tl"/><span className="hud-corner tr"/>
      <span className="hud-corner bl"/><span className="hud-corner br"/>

      {/* Status strip */}
      <div className="vid-hud-tl">
        <span className={`live-dot ${live?"live":"dead"}`}/>
        <span className="live-txt">{live ? "LIVE" : "NO SIGNAL"}</span>
        {aiEnabled     && live && <span className="hud-badge green">◈ AI</span>}
        {thermalEnabled && thermalOnline && live && <span className="hud-badge orange">⬡ THERMAL</span>}
        {thermalEnabled && !thermalOnline && <span className="hud-badge red">⬡ IR OFFLINE</span>}
      </div>

      {/* REC indicator */}
      {isRecording && (
        <div className="rec-hud-badge">
          <span className="rec-hud-dot"/>
          REC
        </div>
      )}

      {loaded && <div className="vid-res">640 × 480</div>}

      {/* Single stream — server does all compositing */}
      {!errored ? (
        <img
          key={streamUrl}
          src={streamUrl}
          alt="Stream"
          className={`vid-img ${loaded ? "shown" : ""}`}
          onLoad ={() => { setLoaded(true);  setErrored(false); }}
          onError={() => { setErrored(true); setLoaded(false); }}
        />
      ) : (
        <NoSignal url={streamUrl} onRetry={() => { setErrored(false); setLoaded(false); }}/>
      )}

      {!loaded && !errored && (
        <div className="vid-loading">
          <div className="scan-bar"/>
          <div className="scan-txt">ACQUIRING SIGNAL...</div>
        </div>
      )}
    </div>
  );
}

function NoSignal({url, onRetry}) {
  return (
    <div className="no-sig">
      <div className="no-sig-grid"/>
      <div className="no-sig-body">
        <div className="no-sig-icon">⊗</div>
        <div className="no-sig-title">NO SIGNAL</div>
        <div className="no-sig-sub">Run python ai_server.py on your laptop</div>
        <div className="no-sig-url">{url}</div>
        <button className="no-sig-btn" onClick={onRetry}>↺ RETRY</button>
      </div>
    </div>
  );
}
