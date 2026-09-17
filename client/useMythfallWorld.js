import { useCallback, useEffect, useRef, useState } from 'react'
import { mythfallCamera } from './mythfallProjection'

export function useMythfallWorld({ request, connected, refreshVersion, realtimeEvents, editorBridge, projectGeneration, viewport, cameraCenter }) {
  const [packet, setPacket] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [pauseRequested, setPauseRequested] = useState(false)
  const [submission, setSubmission] = useState(null)
  const current = useRef(null)
  const active = useRef(false)
  const stop = useRef(false)
  const mounted = useRef(true)
  const rendered = useRef({ bridge: null, generation: null, entities: new Map() })

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; stop.current = true }
  }, [])

  const accept = useCallback((value, force = false) => {
    if (!mounted.current) return
    if (!force && value.world && current.current?.world && value.world.revision < current.current.world.revision) return
    if (!force && value.world?.revision === current.current?.world?.revision &&
      (value.chat?.revision ?? 0) < (current.current?.chat?.revision ?? 0)) return
    current.current = value
    setPacket(value)
  }, [])

  useEffect(() => {
    if (!connected) return
    let cancelled = false
    request('realm.observe', {}).then((response) => {
      if (!cancelled) accept(response.payload, true)
    }).catch((failure) => { if (!cancelled) setError(failure.message) })
    return () => { cancelled = true }
  }, [request, connected, refreshVersion, accept])

  useEffect(() => {
    for (let n = realtimeEvents.length - 1; n >= 0; n -= 1) {
      const message = realtimeEvents[n].payload
      if (message?.type === 'realm.world.changed') {
        accept(message.payload)
        break
      }
    }
  }, [realtimeEvents, accept])

  useEffect(() => {
    if (!editorBridge || !packet?.render || !projectGeneration) return
    const frame = requestAnimationFrame(() => {
      try {
        if (rendered.current.bridge !== editorBridge || rendered.current.generation !== projectGeneration) {
          rendered.current = { bridge: editorBridge, generation: projectGeneration, entities: new Map() }
        }
        const center = cameraCenter ?? [packet.world.self.position[0] + 3, packet.world.self.position[1]]
        const entities = packet.render.map((entity) => entity.camera ? mythfallCamera(center, viewport, entity) : entity)
        const changed = entities.filter((entity) => rendered.current.entities.get(entity.id) !== JSON.stringify(entity))
        if (changed.length) editorBridge.previewEntities(changed)
        for (const entity of changed) rendered.current.entities.set(entity.id, JSON.stringify(entity))
      } catch (failure) {
        setError(failure.message)
      }
    })
    return () => cancelAnimationFrame(frame)
  }, [editorBridge, packet, projectGeneration, viewport, cameraCenter])

  const act = useCallback(async (intent) => {
    if (active.current || !connected || !current.current?.world) return
    active.current = true
    stop.current = false
    setPauseRequested(false)
    setBusy(true)
    setError('')
    let operationId = crypto.randomUUID()
    setSubmission({ intent, operationId })
    let next = intent
    let npcDecisions = 0
    let consequenceChunks = 0
    try {
      while (mounted.current) {
        if (stop.current && ['continue_combat', 'resolve_events'].includes(next.kind)) break
        const response = await request('realm.action', {
          operation_id: operationId, expected_revision: current.current.world.revision, intent: next,
        })
        accept(response.payload)
        if (response.payload.result?.reason === 'rejected') setError(response.payload.result.message)
        if (response.payload.result?.reason !== 'rejected' && response.payload.world?.pending_consequences > 0 && !stop.current && consequenceChunks < 8) {
          consequenceChunks += 1
          next = { kind: 'resolve_events' }
          operationId = crypto.randomUUID()
          await new Promise((resolve) => setTimeout(resolve, 0))
          continue
        }
        if (response.payload.result?.reason !== 'rejected' && response.payload.world?.combat?.needs_npc && !stop.current && mounted.current && npcDecisions < 8) {
          npcDecisions += 1
          next = { kind: 'continue_combat' }
          operationId = crypto.randomUUID()
          await new Promise((resolve) => setTimeout(resolve, 0))
          continue
        }
        if (response.payload.result?.reason !== 'yielded' || !mounted.current) break
        await new Promise((resolve) => setTimeout(resolve, 60))
        next = { kind: stop.current ? 'cancel' : 'resume', wait_id: response.payload.result.wait_id }
        operationId = crypto.randomUUID()
      }
    } catch (failure) {
      if (mounted.current) setError(failure.message)
      // Observe after a failure; never replay a possibly committed mutation.
      try { accept((await request('realm.observe', {})).payload, true) } catch { /* Keep the original failure visible. */ }
    } finally {
      active.current = false
      if (mounted.current) { setBusy(false); setSubmission(null) }
    }
  }, [request, accept, connected])

  return { packet, error, busy, pauseRequested, submission, act, cancel: () => { stop.current = true; setPauseRequested(true) } }
}
