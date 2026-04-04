// utils/sessionLogger.js — v6
// =============================================================================
// HOW DETECTION LOGGING WORKS:
//
//   Each time YOLO detects something, it gets logged as a SEPARATE ROW in
//   Firebase "detectionEvents" with:
//     - sessionId    → same for all detections in one session
//     - timestamp    → exact time this detection happened
//     - label        → "Crack", "Hole", etc.
//     - confidence   → model confidence %
//     - gas_ppm      → gas PPM AT THAT EXACT MOMENT
//     - distance_m   → distance rover has travelled AT THAT MOMENT
//     - thermalAvgC  → thermal reading AT THAT MOMENT
//
//   Example — one session, 3 cracks at different times:
//     sessionId: abc  label: Crack  time: 10:01:05  ppm: 12   dist: 0.45m
//     sessionId: abc  label: Crack  time: 10:01:38  ppm: 15   dist: 1.20m
//     sessionId: abc  label: Crack  time: 10:02:11  ppm: 18   dist: 2.05m
//
// DEDUPLICATION:
//   Only skips if the EXACT SAME crack at EXACT SAME position was logged
//   in the last 3 seconds. This prevents logging the same crack 30×/sec
//   while the rover is stationary. Once the rover moves, bbox changes
//   → treated as a new detection and logged again.
//
// =============================================================================

import { ref, push, set } from "firebase/database";
import { db } from "../firebase";

const SAME_BBOX_COOLDOWN_MS = 3000;

// Round bbox to nearest 10px — small jitter = same crack
function _bboxKey(d) {
  if (!d.bbox) return "no-bbox";
  return d.bbox.map(v => Math.round(v / 10) * 10).join(",");
}

function _fingerprint(d) {
  return `${d.label || "?"} | ${_bboxKey(d)}`;
}

export class SessionLogger {
  constructor(user) {
    this._user       = user;
    this._sessionRef = null;
    this._sessionId  = null;
    this.startMs     = null;
    this.isLogging   = false;

    this._lastLogged    = {};   // { fingerprint: timestamp } — bbox dedup
    this._lastPrune     = 0;

    // Session aggregates
    this._detections    = {};   // { label: count }
    this._peakPpm       = 0;
    this._totalPpm      = 0;
    this._gasCount      = 0;
    this._totalThermal  = 0;
    this._thermalCount  = 0;
    this._peakDistanceM = 0;
    this._lastFlush     = 0;
  }

  // ── Session control ──────────────────────────────────────────────────────

  async start() {
    if (this.isLogging) return;

    this.startMs     = Date.now();
    this.isLogging   = true;
    this._sessionRef = push(ref(db, "sessions"));
    this._sessionId  = this._sessionRef.key;

    // Reset all state
    this._lastLogged    = {};
    this._lastPrune     = 0;
    this._detections    = {};
    this._peakPpm       = 0;
    this._totalPpm      = 0;
    this._gasCount      = 0;
    this._totalThermal  = 0;
    this._thermalCount  = 0;
    this._peakDistanceM = 0;
    this._lastFlush     = 0;

    await set(this._sessionRef, {
      startTime:      this.startMs,
      controllerName: this._user?.displayName || this._user?.email || "Unknown",
      controllerUid:  this._user?.uid || null,
      status:         "active",
      detections:     {},
      peakGasPpm:     0,
      avgGasPpm:      0,
      avgThermalC:    null,
      peakDistanceM:  0,
      duration:       0,
    });

    console.log("[SessionLogger] Session started:", this._sessionId);
  }

  async stop() {
    if (!this.isLogging || !this._sessionRef) return;
    this.isLogging = false;
    await this.finish();
  }

  // ── Detection logging ────────────────────────────────────────────────────

  addDetections(dets, distanceM = 0) {
    if (!dets?.length || !this._sessionRef || !this.isLogging) return;

    const now    = Date.now();
    let newFound = false;

    dets.forEach(d => {
      const label       = d.label || "Unknown";
      const fingerprint = _fingerprint(d);
      const lastTime    = this._lastLogged[fingerprint] || 0;

      // Skip if same crack at same position logged within 3s
      if (now - lastTime < SAME_BBOX_COOLDOWN_MS) return;

      // ── New unique detection — log as individual row ──────────────────
      newFound = true;
      this._lastLogged[fingerprint] = now;

      // Update session aggregate count
      this._detections[label] = (this._detections[label] || 0) + 1;
      if (distanceM > this._peakDistanceM) this._peakDistanceM = distanceM;

      // Write individual event to Firebase
      const eventRef = push(ref(db, "detectionEvents"));
      set(eventRef, {
        sessionId:      this._sessionId,
        controllerName: this._user?.displayName || this._user?.email || "Unknown",
        timestamp:      now,
        label,
        confidence:     d.confidence     ?? null,
        distance_m:     d.distance_m     ?? distanceM,
        gas_ppm:        d.gas_ppm        ?? null,
        gasLevel:       d.gas_level      ?? "OFFLINE",
        thermalAvgC:    d.thermal_avg_c  ?? null,
        bbox:           d.bbox           ?? null,
      })
      .then(() => {
        const t   = new Date(now).toLocaleTimeString("en-GB");
        const ppm = d.gas_ppm != null ? `${d.gas_ppm.toFixed(1)} PPM` : "no gas";
        console.log(`[SessionLogger] ✓ ${label} | ${distanceM.toFixed(2)}m | ${ppm} | ${t}`);
      })
      .catch(e => console.error("[SessionLogger] Write failed:", e));
    });

    // Prune stale fingerprints every 60s
    if (now - this._lastPrune > 60000) {
      this._lastPrune = now;
      for (const [fp, t] of Object.entries(this._lastLogged)) {
        if (now - t > SAME_BBOX_COOLDOWN_MS * 3) delete this._lastLogged[fp];
      }
    }

    if (newFound) this._flushSession();
  }

  // ── Gas + thermal ────────────────────────────────────────────────────────

  addGasReading(ppm, level) {
    if (ppm == null || !this.isLogging) return;
    if (ppm > this._peakPpm) this._peakPpm = ppm;
    this._totalPpm += ppm;
    this._gasCount++;
    this._flushSession();
  }

  addThermalReading(avgC) {
    if (avgC == null || !this.isLogging) return;
    this._totalThermal += avgC;
    this._thermalCount++;
  }

  // ── Session summary flush (max once per 5s) ──────────────────────────────

  _flushSession() {
    const now = Date.now();
    if (now - this._lastFlush < 5000) return;
    this._lastFlush = now;
    if (!this._sessionRef || !this.isLogging) return;

    set(this._sessionRef, {
      startTime:      this.startMs,
      controllerName: this._user?.displayName || this._user?.email || "Unknown",
      controllerUid:  this._user?.uid || null,
      status:         "active",
      detections:     { ...this._detections },
      peakGasPpm:     this._peakPpm,
      avgGasPpm:      this._gasCount > 0
                        ? Math.round(this._totalPpm / this._gasCount * 10) / 10
                        : 0,
      avgThermalC:    this._thermalCount > 0
                        ? Math.round(this._totalThermal / this._thermalCount * 10) / 10
                        : null,
      peakDistanceM:  this._peakDistanceM,
      duration:       Math.round((Date.now() - this.startMs) / 1000),
    }).catch(e => console.error("[SessionLogger] Flush failed:", e));
  }

  // ── Finish session ───────────────────────────────────────────────────────

  async finish() {
    if (!this._sessionRef) return;
    const sessionRef = this._sessionRef;
    this._sessionRef = null;
    this.isLogging   = false;

    const duration = Math.round((Date.now() - this.startMs) / 1000);

    await set(sessionRef, {
      startTime:      this.startMs,
      endTime:        Date.now(),
      controllerName: this._user?.displayName || this._user?.email || "Unknown",
      controllerUid:  this._user?.uid || null,
      status:         "completed",
      duration,
      detections:     { ...this._detections },
      peakGasPpm:     this._peakPpm,
      avgGasPpm:      this._gasCount > 0
                        ? Math.round(this._totalPpm / this._gasCount * 10) / 10
                        : 0,
      avgThermalC:    this._thermalCount > 0
                        ? Math.round(this._totalThermal / this._thermalCount * 10) / 10
                        : null,
      peakDistanceM:  this._peakDistanceM,
    }).catch(e => console.error("[SessionLogger] Finish failed:", e));

    console.log("[SessionLogger] Session finished:", {
      id:         sessionRef.key,
      duration:   `${duration}s`,
      detections: this._detections,
      peakGas:    `${this._peakPpm} PPM`,
    });
  }
}