// components/Controls.jsx
// On-screen D-pad motor control buttons + keyboard hint display.
//
// Layout (3x3 grid):
//   [ ]  [FWD] [ ]
//   [LT] [STP] [RT]
//   [ ]  [BWD] [ ]
//
// Each button fires sendCommand() on mousedown/touchstart and 'stop'
// on mouseup/mouseleave/touchend — matching how a real joystick works.
// Holding the button keeps the robot moving; releasing it stops.
//
// The 'active' class is applied when direction matches the button's command,
// giving visual feedback for both mouse clicks and keyboard presses.

import { useCallback } from 'react'

const ARROWS = {
  forward:  (
    <svg className="ctrl-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>
    </svg>
  ),
  backward: (
    <svg className="ctrl-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/>
    </svg>
  ),
  left: (
    <svg className="ctrl-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>
    </svg>
  ),
  right: (
    <svg className="ctrl-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>
    </svg>
  ),
  stop: (
    <svg className="ctrl-icon" viewBox="0 0 24 24" fill="currentColor">
      <rect x="6" y="6" width="12" height="12" rx="2"/>
    </svg>
  ),
}

function CtrlBtn({ command, icon, direction, sendCommand, extraClass = '' }) {
  const isActive = direction === command

  const onPress = useCallback((e) => {
    e.preventDefault()
    sendCommand(command)
  }, [command, sendCommand])

  const onRelease = useCallback((e) => {
    e.preventDefault()
    if (command !== 'stop') sendCommand('stop')
  }, [command, sendCommand])

  return (
    <button
      className={`ctrl-btn ${isActive ? 'active' : ''} ${extraClass}`}
      onMouseDown={onPress}
      onMouseUp={onRelease}
      onMouseLeave={onRelease}
      onTouchStart={onPress}
      onTouchEnd={onRelease}
      onTouchCancel={onRelease}
    >
      {icon}
    </button>
  )
}

export default function Controls({ direction, sendCommand }) {
  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-label">Motor Controls</span>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--text-muted)' }}>
          HOLD TO MOVE
        </span>
      </div>
      <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
        <div className="controls-grid">
          {/* Row 1 */}
          <div className="ctrl-btn placeholder" />
          <CtrlBtn command="forward"  icon={ARROWS.forward}  direction={direction} sendCommand={sendCommand} />
          <div className="ctrl-btn placeholder" />
          {/* Row 2 */}
          <CtrlBtn command="left"     icon={ARROWS.left}     direction={direction} sendCommand={sendCommand} />
          <CtrlBtn command="stop"     icon={ARROWS.stop}     direction={direction} sendCommand={sendCommand} extraClass="stop-btn" />
          <CtrlBtn command="right"    icon={ARROWS.right}    direction={direction} sendCommand={sendCommand} />
          {/* Row 3 */}
          <div className="ctrl-btn placeholder" />
          <CtrlBtn command="backward" icon={ARROWS.backward} direction={direction} sendCommand={sendCommand} />
          <div className="ctrl-btn placeholder" />
        </div>

        {/* Keyboard hints */}
        <div className="kbd-row">
          <kbd>W</kbd>
          <kbd>A</kbd>
          <kbd>S</kbd>
          <kbd>D</kbd>
          <kbd style={{ opacity: 0.6, fontSize: 9 }}>SPACE = stop</kbd>
        </div>
      </div>
    </div>
  )
}