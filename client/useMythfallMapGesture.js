import { useEffect, useRef } from 'react'
import { mythfallMapPoint } from './mythfallProjection'

// The pointer sequence owns click suppression. No timers or simulation actions
// are involved; cancellation and a second finger end the gesture safely.
export function useMythfallMapGesture({ mapRef, center, viewport, world, setCameraCenter }) {
  const gesture = useRef(null)
  const pointers = useRef(new Set())
  const suppressClick = useRef(false)
  useEffect(() => {
    const node = mapRef.current
    const preventNativeDrag = (event) => {
      if (gesture.current?.dragged || gesture.current?.cancelled) event.preventDefault()
    }
    // A handled drag must also cancel the legacy touch gesture. Otherwise a
    // browser can consume the following tap as a stop for its own gesture.
    node.addEventListener('touchmove', preventNativeDrag, { passive: false })
    return () => node.removeEventListener('touchmove', preventNativeDrag)
  }, [mapRef])
  function move(event) {
    const current = gesture.current
    if (!current || current.id !== event.pointerId || current.cancelled) return
    const dx = event.clientX - current.x
    const dy = event.clientY - current.y
    if (!current.dragged && Math.hypot(dx, dy) < 8) return
    current.dragged = true
    suppressClick.current = true
    event.currentTarget.setPointerCapture(event.pointerId)
    const position = mythfallMapPoint(current.center, current.viewport,
      .5 - dx / current.viewport.width, .5 - dy / current.viewport.height)
    setCameraCenter([Math.max(0, Math.min(world.width - 1, position[0])), Math.max(0, Math.min(world.height - 1, position[1]))])
  }
  function finish(event, cancelled) {
    if (!cancelled) move(event)
    pointers.current.delete(event.pointerId)
    if (gesture.current?.id === event.pointerId) {
      if (cancelled) suppressClick.current = true
      gesture.current = null
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }
  return {
    onPointerDown(event) {
      if (!world || event.button !== 0) return
      // Capture on the original target so a tap on a label still selects it,
      // while a pointer released outside the map always cleans up its state.
      event.target.setPointerCapture(event.pointerId)
      pointers.current.add(event.pointerId)
      if (pointers.current.size > 1) {
        if (gesture.current) gesture.current.cancelled = true
        suppressClick.current = true
        return
      }
      suppressClick.current = false
      gesture.current = { id: event.pointerId, x: event.clientX, y: event.clientY, center: [...center], viewport: { ...viewport } }
    },
    onPointerMove: move,
    onPointerUp: (event) => finish(event, false),
    onPointerCancel: (event) => finish(event, true),
    onLostPointerCapture(event) {
      // Dragging transfers capture from a child label/canvas to the map. Its
      // bubbling lost-capture event is not a cancelled map gesture.
      if (event.target === event.currentTarget && gesture.current?.id === event.pointerId) finish(event, true)
    },
    onClickCapture(event) {
      if (event.detail !== 0 && suppressClick.current) {
        event.preventDefault()
        event.stopPropagation()
        suppressClick.current = false
      }
    },
  }
}
