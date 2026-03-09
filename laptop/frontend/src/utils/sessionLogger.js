// utils/sessionLogger.js  v3
//
// Firebase schema written:
//
//   sessions/{id}:
//     id, startTime, endTime, duration, controllerUid, controllerName,
//     detections: { label: count },
//     peakGasPpm, avgGasPpm, gasReadings: [{t, ppm}],
//     avgThermalC,                          ← NEW v3: scene avg temp °C
//     status: "active" | "completed", notes
//
//   detectionEvents/{id}:
//     sessionId, timestamp (epoch ms), label, confidence,
//     gasPpm, gasLevel, controllerName,
//     thermalAvgC                           ← NEW v3: thermal reading at event time

import { ref, set, update, push } from "firebase/database";
import { db } from "../firebase";

export class SessionLogger {
  constructor(user) {
    this.user       = user;
    this.sessionRef = null;
    this.sessionId  = null;
    this.startMs    = null;

    this._detections  = {};
    this._gasReadings = [];
    this._totalPpm    = 0;
    this._gasCount    = 0;
    this._peakPpm     = 0;
    this._lastGasPpm  = null;
    this._lastGasLvl  = "OFFLINE";
    this._flushTimer  = null;

    // Thermal scene temperature tracking (from Pi MLX90640 via /health)
    this._lastThermalC  = null;   // most recent scene avg °C
    this._totalThermalC = 0;
    this._thermalCount  = 0;

    // Dedup — don't log same label more than once per second
    this._lastDetTime  = {};
    this._DET_COOLDOWN = 2000; // ms between logging same label
  }

  async start() {
    this.startMs      = Date.now();
    const sessRef     = push(ref(db, "sessions"));
    this.sessionRef   = sessRef;
    this.sessionId    = sessRef.key;

    await set(sessRef, {
      id:             this.sessionId,
      startTime:      this.startMs,
      endTime:        null,
      duration:       0,
      controllerUid:  this.user?.uid  || "unknown",
      controllerName: this.user?.displayName || this.user?.email?.split("@")[0] || "Operator",
      detections:     {},
      peakGasPpm:     0,
      avgGasPpm:      0,
      gasReadings:    [],
      status:         "active",
    });

    this._flushTimer = setInterval(() => this._flush(), 15_000);
    return this.sessionId;
  }

  addDetections(detectionArray) {
    if (!detectionArray?.length || !this.sessionId) return;
    const now = Date.now();

    for (const d of detectionArray) {
      const lbl = d.label || "unknown";
      this._detections[lbl] = (this._detections[lbl] || 0) + 1;

      // Write individual detection event — cooldown to avoid spam
      const lastT = this._lastDetTime[lbl] || 0;
      if (now - lastT > this._DET_COOLDOWN) {
        this._lastDetTime[lbl] = now;
        const evRef = push(ref(db, "detectionEvents"));
        set(evRef, {
          sessionId:  this.sessionId,
          timestamp:  now,
          label:      lbl,
          confidence: Math.round((d.confidence || 0) * 100) / 100,
          gasPpm:     this._lastGasPpm,
          gasLevel:   this._lastGasLvl,
          thermalAvgC: this._lastThermalC,                // ← NEW v3
          controllerName: this.user?.displayName || this.user?.email?.split("@")[0] || "Operator",
        }).catch(() => {});
      }
    }
  }

  addThermalReading(avgC) {
    // Called by ControlRoom whenever a new /health response includes thermal_avg_c
    if (avgC == null || typeof avgC !== "number") return;
    this._lastThermalC   = avgC;
    this._totalThermalC += avgC;
    this._thermalCount  += 1;
  }

  addGasReading(ppm, level) {
    if (ppm == null || ppm < 0) return;
    const t = Date.now() - this.startMs;
    this._gasReadings.push({ t, ppm });
    this._totalPpm  += ppm;
    this._gasCount  += 1;
    this._lastGasPpm = ppm;
    this._lastGasLvl = level || "OFFLINE";
    if (ppm > this._peakPpm) this._peakPpm = ppm;
    if (this._gasReadings.length > 500) this._gasReadings.shift();
  }

  async _flush() {
    if (!this.sessionRef) return;
    const duration = Math.round((Date.now() - this.startMs) / 1000);
    const avgGas     = this._gasCount > 0
      ? Math.round(this._totalPpm / this._gasCount * 10) / 10 : 0;
    const avgThermal = this._thermalCount > 0
      ? Math.round(this._totalThermalC / this._thermalCount * 10) / 10 : null;
    await update(this.sessionRef, {
      duration,
      detections:   this._detections,
      peakGasPpm:   Math.round(this._peakPpm * 10) / 10,
      avgGasPpm:    avgGas,
      avgThermalC:  avgThermal,
      gasReadings:  this._gasReadings,
    }).catch(() => {});
  }

  async finish(notes = "") {
    clearInterval(this._flushTimer);
    if (!this.sessionRef) return;
    await this._flush();
    const duration = Math.round((Date.now() - this.startMs) / 1000);
    await update(this.sessionRef, {
      endTime:  Date.now(),
      duration,
      status:   "completed",
      notes,
    }).catch(() => {});
    this.sessionRef = null;
  }
}
