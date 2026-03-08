// hooks/useKeyboard.js
// Keyboard control hook — maps W/A/S/D to motor commands
// Attaches keydown/keyup listeners to window on mount, cleans up on unmount.
// Uses a Set to track held keys so brief taps still register full commands.

import { useEffect, useRef } from 'react'

const KEY_MAP = {
  'w': 'forward',
  'ArrowUp': 'forward',
  's': 'backward',
  'ArrowDown': 'backward',
  'a': 'left',
  'ArrowLeft': 'left',
  'd': 'right',
  'ArrowRight': 'right',
  ' ': 'stop',
}

export function useKeyboard(onCommand, active = true) {
  const heldRef = useRef(new Set())

  useEffect(() => {
    if (!active) return

    const handleDown = (e) => {
      // Ignore if user is typing in an input
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return

      const cmd = KEY_MAP[e.key]
      if (!cmd) return
      e.preventDefault()

      if (!heldRef.current.has(e.key)) {
        heldRef.current.add(e.key)
        onCommand(cmd)
      }
    }

    const handleUp = (e) => {
      const cmd = KEY_MAP[e.key]
      if (!cmd) return
      heldRef.current.delete(e.key)
      // Only stop if no other movement keys are held
      const anyMovement = [...heldRef.current].some(k => KEY_MAP[k] && KEY_MAP[k] !== 'stop')
      if (!anyMovement) {
        onCommand('stop')
      }
    }

    const handleBlur = () => {
      heldRef.current.clear()
      onCommand('stop')
    }

    window.addEventListener('keydown', handleDown)
    window.addEventListener('keyup',   handleUp)
    window.addEventListener('blur',    handleBlur)

    return () => {
      window.removeEventListener('keydown', handleDown)
      window.removeEventListener('keyup',   handleUp)
      window.removeEventListener('blur',    handleBlur)
    }
  }, [onCommand, active])
}