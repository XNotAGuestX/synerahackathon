import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, PointerEvent as ReactPointerEvent, RefObject } from 'react'
import { createPortal } from 'react-dom'
import { copy } from '../i18n/en'
import type { FloorPlan, Point, Route } from '../domain/types'
import {
  ARRIVE_RADIUS_M,
  FIGURE_HEIGHT_M,
  FIGURE_WIDTH_M,
  WALK_SPEED_M_S,
  arcLength,
  buildWalkField,
  closestArc,
  moveWalker,
  pointAtArc,
  routeMarks,
  nearestStand,
  spawnPoint,
  standCause,
} from '../domain/walk-field'
import type { BlockCause } from '../domain/walk-field'

type Dir = 'up' | 'down' | 'left' | 'right'
type WalkMode = 'empty' | 'idle' | 'walking' | 'following' | 'blocked' | 'arrived'

type WalkPadProps = {
  svgRef: RefObject<SVGSVGElement | null>
  plan: FloorPlan
  route: Route | null
  closedIds: string[]
  stepFree: boolean
}

const DIR: Record<Dir, Point> = {
  up: [0, 1],
  down: [0, -1],
  left: [-1, 0],
  right: [1, 0],
}

const KEY_DIR: Record<string, Dir> = {
  ArrowUp: 'up',
  ArrowDown: 'down',
  ArrowLeft: 'left',
  ArrowRight: 'right',
  w: 'up',
  a: 'left',
  s: 'down',
  d: 'right',
  W: 'up',
  A: 'left',
  S: 'down',
  D: 'right',
}

const CAUSE_COPY: Record<BlockCause, string> = {
  wall: copy.walkWall,
  'closed-door': copy.walkClosedDoor,
  step: copy.walkStep,
  narrow: copy.walkNarrow,
  equipment: copy.walkEquipment,
  outside: copy.walkOutside,
}

const PAD_STORAGE_KEY = 'wayfinder-walk-pad'
const SPEED_STORAGE_KEY = 'wayfinder-walk-speed'
const SPEED_MIN_M_S = 0.4
const SPEED_MAX_M_S = 4
const VIEWPORT_MARGIN = 8

type PadPlace = { x: number; y: number; hidden: boolean }

function readPadPlace(): PadPlace | null {
  try {
    const raw = window.localStorage.getItem(PAD_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<PadPlace>
    if (typeof parsed.x !== 'number' || typeof parsed.y !== 'number' || !Number.isFinite(parsed.x) || !Number.isFinite(parsed.y)) return null
    return { x: parsed.x, y: parsed.y, hidden: Boolean(parsed.hidden) }
  } catch {
    return null
  }
}

function readWalkSpeed(): number {
  try {
    const stored = window.localStorage.getItem(SPEED_STORAGE_KEY)
    if (stored == null) return WALK_SPEED_M_S
    const raw = Number(stored)
    if (Number.isFinite(raw)) return Math.min(SPEED_MAX_M_S, Math.max(SPEED_MIN_M_S, raw))
  } catch {
    /* Use the default pace if storage cannot be read. */
  }
  return WALK_SPEED_M_S
}

function rememberPadPlace(place: PadPlace) {
  try {
    window.localStorage.setItem(PAD_STORAGE_KEY, JSON.stringify(place))
  } catch {
    /* The panel still moves if storage is unavailable. */
  }
}

function clampToViewport(x: number, y: number, width: number, height: number): { x: number; y: number } {
  const maxX = Math.max(VIEWPORT_MARGIN, window.innerWidth - width - VIEWPORT_MARGIN)
  const maxY = Math.max(VIEWPORT_MARGIN, window.innerHeight - height - VIEWPORT_MARGIN)
  return {
    x: Math.min(maxX, Math.max(VIEWPORT_MARGIN, x)),
    y: Math.min(maxY, Math.max(VIEWPORT_MARGIN, y)),
  }
}

function typingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable
}

function project(svg: SVGSVGElement, wrap: HTMLElement, point: Point): { x: number; y: number } | null {
  const matrix = svg.getScreenCTM()
  if (!matrix) return null
  const svgPoint = svg.createSVGPoint()
  svgPoint.x = point[0]
  svgPoint.y = -point[1]
  const screen = svgPoint.matrixTransform(matrix)
  const rect = wrap.getBoundingClientRect()
  return { x: screen.x - rect.left, y: screen.y - rect.top }
}

function pixelsPerMetre(svg: SVGSVGElement): number {
  const matrix = svg.getScreenCTM()
  if (!matrix) return 1
  const origin = svg.createSVGPoint()
  const oneMetre = svg.createSVGPoint()
  oneMetre.x = 1
  const start = origin.matrixTransform(matrix)
  const end = oneMetre.matrixTransform(matrix)
  return Math.hypot(end.x - start.x, end.y - start.y)
}

export function WalkPad({ svgRef, plan, route, closedIds, stepFree }: WalkPadProps) {
  const tokenRef = useRef<HTMLDivElement>(null)
  const originRef = useRef<HTMLSpanElement>(null)
  const destRef = useRef<HTMLSpanElement>(null)
  const readoutRef = useRef<HTMLSpanElement>(null)
  const pointRef = useRef<Point | null>(null)
  const headingRef = useRef(0)
  const held = useRef(new Set<Dir>())
  const followRef = useRef(false)
  const cursorRef = useRef(0)
  const stuckRef = useRef(0)
  const modeRef = useRef<WalkMode>('idle')
  const causeRef = useRef<BlockCause | null>(null)
  const [mode, setMode] = useState<WalkMode>('idle')
  const [cause, setCause] = useState<BlockCause | null>(null)
  const [pressed, setPressed] = useState<Dir[]>([])
  const [following, setFollowing] = useState(false)
  const padRef = useRef<HTMLDivElement>(null)
  const hideRef = useRef<HTMLButtonElement>(null)
  const showRef = useRef<HTMLButtonElement>(null)
  const placeReady = useRef(readPadPlace() != null)
  const hiddenChanged = useRef(false)
  const drag = useRef<{ id: number; dx: number; dy: number } | null>(null)
  const [place, setPlace] = useState<PadPlace>(() => readPadPlace() ?? { x: 24, y: 24, hidden: false })
  const [dragging, setDragging] = useState(false)
  const [speed, setSpeed] = useState(readWalkSpeed)
  const speedRef = useRef(speed)
  speedRef.current = speed

  const field = useMemo(() => buildWalkField(plan, closedIds, stepFree), [plan, closedIds, stepFree])
  const marks = useMemo(() => routeMarks(plan, route), [plan, route])
  const fieldRef = useRef(field)
  const marksRef = useRef(marks)
  fieldRef.current = field
  marksRef.current = marks

  const publish = (blocked: BlockCause | null, moving: boolean) => {
    const point = pointRef.current
    const destination = marksRef.current.destination
    const arrived = Boolean(point && destination && Math.hypot(point[0] - destination[0], point[1] - destination[1]) <= ARRIVE_RADIUS_M)
    const next: WalkMode = !point ? 'empty' : arrived ? 'arrived' : blocked ? 'blocked' : moving ? (followRef.current ? 'following' : 'walking') : 'idle'
    if (next === modeRef.current && blocked === causeRef.current) return
    modeRef.current = next
    causeRef.current = blocked
    setMode(next)
    setCause(blocked)
  }

  const paint = () => {
    const token = tokenRef.current
    const svg = svgRef.current
    const wrap = token?.parentElement
    const point = pointRef.current
    if (!token || !svg || !wrap || !point) return
    const pixel = project(svg, wrap, point)
    if (!pixel) return
    const scale = pixelsPerMetre(svg)
    const width = FIGURE_WIDTH_M * scale
    const height = FIGURE_HEIGHT_M * scale
    const facing = Math.cos(headingRef.current) >= 0 ? 1 : -1
    token.style.transform = `translate(${pixel.x}px, ${pixel.y}px)`
    token.style.setProperty('--facing', String(facing))
    token.dataset.span = width.toFixed(2)
    const body = token.querySelector<HTMLElement>('.walk-body')
    if (body) {
      body.style.width = `${width}px`
      body.style.height = `${height}px`
    }
    token.classList.toggle('blocked', modeRef.current === 'blocked')
    token.classList.toggle('moving', held.current.size > 0 || followRef.current)
    token.dataset.x = point[0].toFixed(3)
    token.dataset.y = point[1].toFixed(3)
    const place = (mark: HTMLSpanElement | null, target: Point | null) => {
      if (!mark) return
      if (!target) {
        mark.hidden = true
        return
      }
      const at = project(svg, wrap, target)
      if (!at) {
        mark.hidden = true
        return
      }
      mark.hidden = false
      mark.style.transform = `translate(${at.x}px, ${at.y - 20}px) translate(-50%, -50%)`
    }
    place(originRef.current, marksRef.current.origin)
    place(destRef.current, marksRef.current.destination)
    if (readoutRef.current) {
      const destination = marksRef.current.destination
      readoutRef.current.textContent = destination
        ? Math.hypot(destination[0] - point[0], destination[1] - point[1]).toFixed(1)
        : '—'
    }
  }

  useLayoutEffect(() => { paint() })

  useLayoutEffect(() => {
    const pad = padRef.current
    if (!pad) return
    const width = pad.offsetWidth
    const height = pad.offsetHeight
    setPlace((current) => {
      const origin = placeReady.current
        ? current
        : { ...current, x: window.innerWidth - width - 16, y: window.innerHeight - height - 16 }
      placeReady.current = true
      const next = clampToViewport(origin.x, origin.y, width, height)
      if (next.x === current.x && next.y === current.y) return current
      return { ...current, ...next }
    })
  }, [place.hidden])

  useEffect(() => {
    const onResize = () => {
      const pad = padRef.current
      if (!pad) return
      setPlace((current) => {
        const next = clampToViewport(current.x, current.y, pad.offsetWidth, pad.offsetHeight)
        if (next.x === current.x && next.y === current.y) return current
        const updated = { ...current, ...next }
        rememberPadPlace(updated)
        return updated
      })
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  useEffect(() => {
    if (!hiddenChanged.current) return
    hiddenChanged.current = false
    if (place.hidden) showRef.current?.focus()
    else hideRef.current?.focus()
  }, [place.hidden])

  useEffect(() => {
    const next = spawnPoint(plan, fieldRef.current, route)
    pointRef.current = next
    headingRef.current = 0
    followRef.current = false
    cursorRef.current = 0
    stuckRef.current = 0
    setFollowing(false)
    const nextMode: WalkMode = next ? 'idle' : 'empty'
    modeRef.current = nextMode
    causeRef.current = null
    setMode(nextMode)
    setCause(null)
    paint()
  }, [plan.floor.id, route?.id, route?.reachable])

  useEffect(() => {
    const point = pointRef.current
    if (!point || !standCause(field, point)) return
    pointRef.current = nearestStand(field, point) ?? spawnPoint(plan, fieldRef.current, route)
    paint()
  }, [field, plan, route])

  useEffect(() => {
    const wrap = tokenRef.current?.parentElement
    if (!wrap) return
    const observer = new ResizeObserver(() => paint())
    observer.observe(wrap)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const holdKey = (dir: Dir) => {
      if (held.current.has(dir)) return
      followRef.current = false
      setFollowing(false)
      held.current.add(dir)
      setPressed([...held.current])
    }
    const releaseDir = (dir: Dir) => {
      if (!held.current.has(dir)) return
      held.current.delete(dir)
      setPressed([...held.current])
      if (held.current.size === 0 && !followRef.current) publish(null, false)
      paint()
    }
    const releaseAll = () => {
      held.current.clear()
      setPressed([])
      if (!followRef.current) publish(null, false)
      paint()
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey || typingTarget(event.target)) return
      if (event.key === 'Escape' && followRef.current) {
        followRef.current = false
        setFollowing(false)
        publish(null, false)
        paint()
        return
      }
      const dir = KEY_DIR[event.key]
      if (!dir) return
      event.preventDefault()
      holdKey(dir)
    }
    const onKeyUp = (event: KeyboardEvent) => {
      const dir = KEY_DIR[event.key]
      if (!dir) return
      releaseDir(dir)
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    window.addEventListener('blur', releaseAll)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
      window.removeEventListener('blur', releaseAll)
    }
  }, [])

  useEffect(() => {
    let frame = 0
    let last = performance.now()
    const tick = (now: number) => {
      frame = requestAnimationFrame(tick)
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      if (held.current.size === 0 && !followRef.current) return
      const point = pointRef.current
      if (!point) return
      if (held.current.size > 0) {
        const combined = [...held.current].reduce<Point>((sum, dir) => [sum[0] + DIR[dir][0], sum[1] + DIR[dir][1]], [0, 0])
        const length = Math.hypot(combined[0], combined[1])
        if (length < 1e-6) return
        const dir: Point = [combined[0] / length, combined[1] / length]
        headingRef.current = Math.atan2(dir[1], dir[0])
        const pace = speedRef.current
        const next = moveWalker(fieldRef.current, point, [dir[0] * pace * dt, dir[1] * pace * dt])
        const stuck = Math.hypot(next.point[0] - point[0], next.point[1] - point[1]) < 0.002
        pointRef.current = next.point
        publish(stuck ? next.cause : null, true)
        paint()
        return
      }
      const leg = marksRef.current.leg
      if (leg.length < 2) {
        followRef.current = false
        setFollowing(false)
        publish(null, false)
        return
      }
      const pace = speedRef.current
      cursorRef.current = Math.min(arcLength(leg), cursorRef.current + pace * dt)
      const target = pointAtArc(leg, cursorRef.current)
      const dx = target[0] - point[0]
      const dy = target[1] - point[1]
      const distance = Math.hypot(dx, dy)
      if (distance > 1e-4) headingRef.current = Math.atan2(dy, dx)
      const step = Math.min(distance, pace * dt)
      const delta: Point = distance < 1e-6 ? [0, 0] : [(dx / distance) * step, (dy / distance) * step]
      const next = moveWalker(fieldRef.current, point, delta)
      const moved = Math.hypot(next.point[0] - point[0], next.point[1] - point[1])
      pointRef.current = next.point
      stuckRef.current = moved < 0.002 ? stuckRef.current + dt : 0
      if (stuckRef.current > 0.35) {
        followRef.current = false
        setFollowing(false)
        stuckRef.current = 0
        publish(next.cause ?? 'wall', false)
        paint()
        return
      }
      if (cursorRef.current >= arcLength(leg) - 0.05) {
        followRef.current = false
        setFollowing(false)
      }
      publish(null, followRef.current)
      paint()
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [])

  const hold = (dir: Dir, event: ReactPointerEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    followRef.current = false
    setFollowing(false)
    held.current.add(dir)
    setPressed([...held.current])
  }
  const release = (dir: Dir) => {
    held.current.delete(dir)
    setPressed([...held.current])
    if (held.current.size === 0 && !followRef.current) publish(null, false)
    paint()
  }
  const nudge = (dir: Dir) => {
    const point = pointRef.current
    if (!point) return
    const vector = DIR[dir]
    headingRef.current = Math.atan2(vector[1], vector[0])
    const step = Math.max(0.15, speedRef.current * 0.35)
    const next = moveWalker(fieldRef.current, point, [vector[0] * step, vector[1] * step])
    const stuck = Math.hypot(next.point[0] - point[0], next.point[1] - point[1]) < 0.002
    pointRef.current = next.point
    publish(stuck ? next.cause : null, false)
    paint()
  }
  const onSpeed = (event: ChangeEvent<HTMLInputElement>) => {
    const next = Math.min(SPEED_MAX_M_S, Math.max(SPEED_MIN_M_S, Number(event.target.value)))
    setSpeed(next)
    try {
      window.localStorage.setItem(SPEED_STORAGE_KEY, String(next))
    } catch {
      /* The slider still applies for this visit. */
    }
  }
  const reset = () => {
    pointRef.current = marksRef.current.origin ?? spawnPoint(plan, fieldRef.current, route)
    headingRef.current = 0
    followRef.current = false
    cursorRef.current = 0
    stuckRef.current = 0
    setFollowing(false)
    publish(null, false)
    paint()
  }
  const setHidden = (hidden: boolean) => {
    hiddenChanged.current = true
    setPlace((current) => {
      const next = { ...current, hidden }
      rememberPadPlace(next)
      return next
    })
  }
  const onDragDown = (event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0) return
    const pad = padRef.current
    if (!pad) return
    event.preventDefault()
    event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    const rect = pad.getBoundingClientRect()
    drag.current = { id: event.pointerId, dx: event.clientX - rect.left, dy: event.clientY - rect.top }
    setDragging(true)
  }
  const onDragMove = (event: ReactPointerEvent<HTMLElement>) => {
    const active = drag.current
    const pad = padRef.current
    if (!active || active.id !== event.pointerId || !pad) return
    const next = clampToViewport(event.clientX - active.dx, event.clientY - active.dy, pad.offsetWidth, pad.offsetHeight)
    setPlace((current) => (current.x === next.x && current.y === next.y ? current : { ...current, ...next }))
  }
  const onDragEnd = (event: ReactPointerEvent<HTMLElement>) => {
    if (drag.current?.id !== event.pointerId) return
    drag.current = null
    setDragging(false)
    setPlace((current) => {
      rememberPadPlace(current)
      return current
    })
  }
  const toggleFollow = () => {
    if (followRef.current) {
      followRef.current = false
      setFollowing(false)
      publish(null, false)
      paint()
      return
    }
    const point = pointRef.current
    const leg = marksRef.current.leg
    if (!point || leg.length < 2) return
    cursorRef.current = closestArc(leg, point)
    stuckRef.current = 0
    followRef.current = true
    setFollowing(true)
    publish(null, true)
  }

  const hasDestination = Boolean(marks.destination)
  const status = mode === 'empty'
    ? copy.walkEmpty
    : mode === 'arrived'
      ? copy.walkArrived
      : mode === 'blocked' && cause
        ? CAUSE_COPY[cause]
        : mode === 'following'
          ? copy.walkFollowing
          : mode === 'walking'
            ? (hasDestination ? copy.walkTowardB : copy.walkIdle)
            : hasDestination
              ? copy.walkIdle
              : marks.origin
                ? copy.walkOtherFloor
                : copy.walkNoDestination

  return (
    <>
      <div ref={tokenRef} className="walk-token" aria-hidden="true" data-walk-token="">
        <div className="walk-body">
          <svg className="stick-figure" viewBox="0 0 48 64" preserveAspectRatio="xMidYMid meet">
            <g fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round">
              <circle className="stick-head" cx="24" cy="10" r="7" />
              <path d="M24 17 V34" />
              <path className="stick-arm front" d="M24 22 L13 31" />
              <path className="stick-arm back" d="M24 22 L35 31" />
              <path className="stick-leg front" d="M24 34 L15 54" />
              <path className="stick-leg back" d="M24 34 L33 54" />
            </g>
          </svg>
        </div>
      </div>
      <span ref={originRef} className="walk-mark walk-mark-a" hidden>A</span>
      <span ref={destRef} className="walk-mark walk-mark-b" hidden>B</span>
      {createPortal(
        <div
          ref={padRef}
          className={['walk-pad', place.hidden ? 'is-hidden' : '', dragging ? 'is-dragging' : ''].filter(Boolean).join(' ')}
          role="group"
          aria-label={copy.walk}
          aria-expanded={!place.hidden}
          data-has-destination={hasDestination ? 'true' : 'false'}
          data-walk-hidden={place.hidden ? 'true' : 'false'}
          style={{ transform: `translate(${place.x}px, ${place.y}px)` }}
        >
          <div
            className="walk-pad-bar"
            onPointerDown={onDragDown}
            onPointerMove={onDragMove}
            onPointerUp={onDragEnd}
            onPointerCancel={onDragEnd}
          >
            <span className="walk-grip" aria-hidden="true" />
            <span className="walk-pad-title">{copy.walk}</span>
            {place.hidden
              ? <button ref={showRef} type="button" className="walk-toggle" aria-label={copy.walkShowLabel} onPointerDown={(event) => event.stopPropagation()} onClick={() => setHidden(false)}>{copy.walkShow}</button>
              : <button ref={hideRef} type="button" className="walk-toggle" aria-label={copy.walkHideLabel} onPointerDown={(event) => event.stopPropagation()} onClick={() => setHidden(true)}>{copy.walkHide}</button>}
          </div>
          {place.hidden
            ? <p className="sr-only" role="status" data-walk-status={mode}>{status}</p>
            : (
              <>
                <div className="walk-cross">
                  {(['up', 'left', 'right', 'down'] as const).map((dir) => (
                    <button
                      key={dir}
                      type="button"
                      className={`walk-${dir}`}
                      aria-label={dir === 'up' ? copy.moveUp : dir === 'down' ? copy.moveDown : dir === 'left' ? copy.moveLeft : copy.moveRight}
                      aria-pressed={pressed.includes(dir)}
                      disabled={mode === 'empty'}
                      onPointerDown={(event) => hold(dir, event)}
                      onPointerUp={() => release(dir)}
                      onPointerCancel={() => release(dir)}
                      onClick={(event) => { if (event.detail === 0) nudge(dir) }}
                    >
                      {dir === 'up' ? '↑' : dir === 'down' ? '↓' : dir === 'left' ? '←' : '→'}
                    </button>
                  ))}
                  <div className="walk-mid" aria-hidden="true">
                    <span ref={readoutRef}>—</span>
                    <small>{copy.walkMetres}</small>
                  </div>
                </div>
                <label className="walk-speed">
                  <span id="walk-speed-label">{copy.walkSpeed}</span>
                  <input
                    type="range"
                    min={SPEED_MIN_M_S}
                    max={SPEED_MAX_M_S}
                    step={0.05}
                    value={speed}
                    aria-labelledby="walk-speed-label"
                    aria-valuetext={`${speed.toFixed(2)} ${copy.walkMetresPerSecond}`}
                    onChange={onSpeed}
                    onPointerDown={(event) => event.stopPropagation()}
                  />
                  <span className="walk-speed-value" aria-hidden="true">{speed.toFixed(2)}</span>
                </label>
                <div className="walk-actions">
                  <button type="button" onClick={toggleFollow} disabled={marks.leg.length < 2} aria-pressed={following}>{following ? copy.stopFollowing : copy.followRoute}</button>
                  <button type="button" onClick={reset} disabled={mode === 'empty'}>{marks.origin ? copy.returnToA : copy.resetPosition}</button>
                </div>
                <p className="walk-status" role="status" data-walk-status={mode}>{status}</p>
              </>
            )}
        </div>,
        document.body,
      )}
    </>
  )
}
