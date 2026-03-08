// hooks/useRobotAPI.js
// Central API hook — all communication with laptop backend goes through here.
// Why a custom hook?
//   - Centralises the backend URL so changing it (e.g., when deploying to a
//     different machine) requires editing one constant.
//   - Exposes a clean sendCommand(dir) function that the Controls component
//     and keyboard hook both call.
//   - Manages connection status by polling /health every 3s.
//   - Manages AI enabled state and provides toggleAI().

import { useState, useEffect, useCallback, useRef } from 'react'

// Change this to your laptop's IP if accessing from another device on the network.
// In Vite dev mode, /api is proxied to localhost:8000 automatically.
const API_BASE = '/api'

export function useRobotAPI() {
  const [connected, setConnected]       = useState('connecting') // 'connecting' | 'connected' | 'disconnected'
  const [piConnected, setPiConnected]   = useState(false)
  const [aiEnabled, setAiEnabled]       = useState(true)
  const [direction, setDirection]       = useState('stop')
  const [fps, setFps]                   = useState(0)
  const lastCommandRef                  = useRef(null)
  const frameCountRef                   = useRef(0)
  const fpsTimerRef                     = useRef(null)

  // ── Health polling ──────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false

    const poll = async () => {
      try {
        const r = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(2500) })
        if (cancelled) return
        if (r.ok) {
          const data = await r.json()
          setConnected('connected')
          setPiConnected(data.pi_connected ?? false)
          setAiEnabled(data.ai_enabled ?? true)
        } else {
          setConnected('disconnected')
        }
      } catch {
        if (!cancelled) setConnected('disconnected')
      }
    }

    poll()
    const interval = setInterval(poll, 3000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [])

  // ── Motor commands ──────────────────────────────────────────────────────────
  const sendCommand = useCallback(async (dir) => {
    if (lastCommandRef.current === dir) return   // debounce same-command spam
    lastCommandRef.current = dir
    setDirection(dir)

    try {
      await fetch(`${API_BASE}/move/${dir}`, {
        method: 'POST',
        signal: AbortSignal.timeout(1500),
      })
    } catch (err) {
      // Non-fatal — command may still arrive if network is briefly slow
      console.warn(`Motor command '${dir}' failed:`, err.message)
    }
  }, [])

  // ── AI toggle ───────────────────────────────────────────────────────────────
  const toggleAI = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/ai/toggle`, { method: 'POST' })
      if (r.ok) {
        const data = await r.json()
        setAiEnabled(data.ai_enabled)
      }
    } catch (err) {
      console.warn('AI toggle failed:', err.message)
    }
  }, [])

  return {
    connected,
    piConnected,
    aiEnabled,
    direction,
    fps,
    sendCommand,
    toggleAI,
    API_BASE,
  }
}