import { useEffect, useState } from 'react'
import { MythfallContext } from './MythfallContext'
import { useMythfallWorld } from './useMythfallWorld'

const EMPTY_EVENTS = []

// Own the resolver loop for the session, above all dock tabs. Closing, moving,
// or hiding a panel must not start a second loop or lose a pending activity.
export function MythfallSession({ children, workspaceClient, openPanel, sessionId = 'default', realtimeEvents = EMPTY_EVENTS, ...props }) {
  const [viewport, setViewport] = useState({ width: 800, height: 600 })
  const [cameraCenter, setCameraCenter] = useState(null)
  const runtime = useMythfallWorld({ ...props, realtimeEvents, viewport, cameraCenter })
  const [actorId, setActorId] = useState(null)
  const [itemId, setItemId] = useState(null)
  const [speech, setSpeech] = useState('')
  const [intentText, setIntentText] = useState('')
  const [characterId, setCharacterId] = useState('char.player')
  const pinKey = `mythfall.ability-pins:${sessionId}`
  const [pins, setPins] = useState(() => {
    try { const saved = JSON.parse(localStorage.getItem(pinKey)); return Array.isArray(saved) ? saved.slice(0, 4) : [] } catch { return [] }
  })
  useEffect(() => { try { localStorage.setItem(pinKey, JSON.stringify(pins)) } catch { /* Panels work when storage is unavailable. */ } }, [pinKey, pins])
  const world = runtime.packet?.world
  function selectEntity(id) {
    if (world?.actors.some((actor) => actor.id === id)) {
      if (actorId !== id) setSpeech('')
      setActorId(id)
      openPanel(id === world.self.id ? 'mythfall.character' : 'mythfall.conversation')
    } else {
      setItemId(id)
      openPanel('mythfall.inventory')
    }
  }
  const value = {
    ...runtime, world, player: world?.self, workspaceClient, openPanel, selectEntity,
    canAct: props.connected && !runtime.busy && Boolean(world),
    actor: world?.actors.find((actor) => actor.id === actorId && actor.id !== world.self.id),
    item: world?.items.find((item) => item.id === itemId),
    inventory: world?.items.filter((item) => item.place.carrier === world.self.id) ?? [],
    speech, setSpeech, intentText, setIntentText, viewport, setViewport,
    cameraCenter, setCameraCenter,
    characterId, setCharacterId, character: world?.characters?.[characterId] ?? world?.characters?.['char.player'], pins,
    pinAbility(id) {
      const existing = pins.indexOf(id)
      const slot = existing >= 0 ? existing : pins.length < 4 ? pins.length : 0
      setPins((current) => { const next = [...current]; next[slot] = id; return next })
      openPanel(`mythfall.abilities-${slot + 1}`)
    },
    mapCenter: cameraCenter ?? (world ? [world.self.position[0] + 3, world.self.position[1]] : [27, 24]),
  }
  return <MythfallContext.Provider value={value}>{children}</MythfallContext.Provider>
}
