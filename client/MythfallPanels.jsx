import { useEffect, useRef } from 'react'
import { AtlasCanvas } from '@squareroundcurly/atlas'
import { Backpack, BookOpen, Clock3, LocateFixed, MessageSquare, Pause, Sparkles, Swords, UserRound, Users } from 'lucide-react'
import { Button, FieldGroup, IconButton, InlineState, Select, TextArea, TextField, Toolbar } from '@pocketrealms/ui'
import { Portrait } from './Portrait'
import { useMythfallSession } from './MythfallContext'
import { mythfallMapPoint, mythfallProjection } from './mythfallProjection'
import { useMythfallMapGesture } from './useMythfallMapGesture'
import { MythfallChatPanel } from './MythfallChatPanel'
import { CharacterSelector, CompanionRelationship, Progression, MythfallAbilitiesPanel, MythfallPartyPanel } from './MythfallRpgPanels'
import './mythfall.css'

const REASONS = {
  action_complete: 'Your move', combat_decision: 'Choose your combat action',
  condition_reached: 'Something you were watching for happened', duration_elapsed: 'Time has passed',
  timeout: 'The watch ended without a sighting', cancelled: 'Time paused', yielded: 'Time is passing…',
  arrived: 'You have arrived', interrupted: 'Something needs your attention', blocked: 'The way is blocked',
  unconscious: 'Your character has fallen', plan_accepted: 'A new intention',
  conversation_complete: 'The conversation pauses', answer: 'The world remains paused',
}
const ICONS = { sword: '⚔', weapon: '⚒', lantern: '☼', food: '◒', book: '▤', trinket: '✧' }
const PANEL_SHORTCUTS = [
  ['chat', 'Game chat', MessageSquare],
  ['character', 'Character', UserRound], ['inventory', 'Inventory', Backpack],
  ['conversation', 'Conversation', MessageSquare], ['actions', 'Actions & time', Clock3],
  ['journal', 'Journal', BookOpen],
  ['abilities', 'Abilities', Sparkles], ['party', 'Party & initiative', Users],
]

export function MythfallWorldPanel() {
  const { world, player, packet, busy, canAct, act, cancel, selectEntity, openPanel, viewport: mapSize, setViewport,
    mapCenter, cameraCenter, setCameraCenter } = useMythfallSession()
  const mapRef = useRef(null)
  const gestures = useMythfallMapGesture({ mapRef, center: mapCenter, viewport: mapSize, world, setCameraCenter })
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width > 0 && height > 0) setViewport((current) => current.width === width && current.height === height ? current : { width, height })
    })
    observer.observe(mapRef.current)
    return () => observer.disconnect()
  }, [setViewport])
  const { mapWidth, mapHeight } = mythfallProjection(mapSize)
  function labelPosition(position) {
    return { left: `${50 + 100 * (position[0] - mapCenter[0]) / mapWidth}%`,
      top: `${50 + 100 * (position[1] - mapCenter[1]) / mapHeight}%` }
  }
  const labelBoxes = []
  const labelOffsets = new Map((world?.actors ?? []).map((actor) => {
    const x = actor.position[0] * mapSize.width / mapWidth
    const baseY = actor.position[1] * mapSize.height / mapHeight
    const width = Math.max(60, actor.name.length * 6 + 16)
    let y = baseY
    while (labelBoxes.some((box) => Math.abs(box.x - x) < (box.width + width) / 2 && Math.abs(box.y - y) < 29)) y += 29
    labelBoxes.push({ x, y, width })
    return [actor.id, y - baseY]
  }))
  function walk(event) {
    if (!canAct || event.target.closest('button')) return
    const rect = mapRef.current.getBoundingClientRect()
    const [x, y] = mythfallMapPoint(mapCenter, mapSize, (event.clientX - rect.left) / rect.width,
      (event.clientY - rect.top) / rect.height).map(Math.round)
    if (x >= 0 && x < world.width && y >= 0 && y < world.height) void act({ kind: world.combat ? 'move' : 'travel', position: [x, y] })
  }
  function onKeyDown(event) {
    const offsets = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] }
    if (!player || event.target.matches('input,textarea,select') || !offsets[event.code]) return
    event.preventDefault()
    if (canAct && !event.repeat) {
      const [dx, dy] = offsets[event.code]
      void act({ kind: 'move', position: [player.position[0] + dx, player.position[1] + dy] })
    }
  }
  return <section className="mythfall-panel mythfall-world" aria-label="Mythfall world" onKeyDownCapture={onKeyDown}>
    <Toolbar label="World panels" className="mythfall-map-toolbar">
      <div className="mythfall-location"><strong>Emberwick</strong><span>LOWMERE</span></div>
      <div className="mythfall-clock"><strong>{world?.time ?? '08:00'}</strong><span>Day {world?.day ?? 1} · {busy ? 'Resolving' : 'Paused'}</span></div>
      {busy && <IconButton icon={Pause} label="Pause time" onClick={cancel} />}
      <IconButton icon={LocateFixed} label="Recenter on character" disabled={!world} aria-pressed={!cameraCenter} onClick={() => setCameraCenter(null)} />
      {PANEL_SHORTCUTS.map(([id, label, icon]) => <IconButton key={id} icon={icon} label={`Open ${label}`} onClick={() => openPanel(`mythfall.${id}`)} />)}
    </Toolbar>
    <div className="mythfall-map" ref={mapRef} {...gestures} onClick={walk} role="application" aria-label="Emberwick map">
      <AtlasCanvas canvasId="atlas-canvas-1" />
      {world?.actors.map((actor) => <button className={`mythfall-map-label ${actor.id === player.id ? 'player' : ''}`} key={actor.id}
        style={{ ...labelPosition(actor.position), marginTop: labelOffsets.get(actor.id) }} onClick={(event) => { event.stopPropagation(); selectEntity(actor.id) }} aria-label={`Select ${actor.name}`}>
        {actor.name}<span>{actor.activity}</span>
      </button>)}
      {world?.items.filter((item) => item.place.ground).map((item) => <button className="mythfall-item-target" key={item.id}
        style={labelPosition([item.place.ground[0] + .7, item.place.ground[1] + .6])}
        aria-label={`Select ground ${item.name}`} title={item.name} onClick={(event) => { event.stopPropagation(); selectEntity(item.id) }} />)}
      <div className="mythfall-map-hint">Tap to walk · Drag to look around · Arrow keys to step</div>
      {!world && <div className="mythfall-welcome"><h3>Your story begins here</h3><p>{packet?.message ?? 'Opening Emberwick…'}</p>
        <Button onClick={() => openPanel('builtin.chat')}>Open character creation chat</Button></div>}
    </div>
  </section>
}

function CharacterCard({ actor }) {
  const { workspaceClient } = useMythfallSession()
  return <div className="mythfall-character"><Portrait actor={actor} workspaceClient={workspaceClient} />
    <div><h3>{actor.name}</h3><span>{actor.hp} / {actor.max_hp} health</span><span>{actor.activity}</span></div></div>
}

export function MythfallCharacterPanel() {
  const { player: original, character } = useMythfallSession()
  const player = character ?? original
  if (!player) return <InlineState>Your character will appear here after character creation.</InlineState>
  return <section className="mythfall-panel mythfall-scroll" aria-label="Character sheet">
    <div className="mythfall-padding"><CharacterSelector /></div>
    <CharacterCard actor={player} />
    <div className="mythfall-padding mythfall-note">AC {player.armor_class ?? '—'} · Speed {(player.speed ?? 6) * 5} ft · Mood {player.mood ?? 0}</div>
    {player.relationship != null && <div className="mythfall-padding"><CompanionRelationship actor={player} /></div>}
    {player.rpg && <Progression actor={player} />}
    <FieldGroup title="Character sheet"><dl className="mythfall-stats">
      {Object.entries(player.stats).map(([stat, value]) => <div key={stat}><dt>{stat.toUpperCase()}</dt><dd>{value}</dd></div>)}
    </dl></FieldGroup>
    <FieldGroup title="Needs"><div className="mythfall-needs">
      <label>Hunger <meter min="0" max="10000" value={player.hunger} /></label>
      <label>Fatigue <meter min="0" max="10000" value={player.fatigue} /></label>
    </div><p className="mythfall-note">Eat from your pack and rest using Actions & time.</p></FieldGroup>
  </section>
}

export function MythfallInventoryPanel() {
  const { player, world, item, inventory, canAct, act, selectEntity, error } = useMythfallSession()
  if (!world) return <InlineState>Your pack is not ready yet.</InlineState>
  const ground = world.items.filter((entry) => entry.place.ground || entry.place.container ||
    (entry.place.carrier !== player.id && world.actors.some((actor) => actor.id === entry.place.carrier && actor.hp === 0)))
  const carried = item?.place.carrier === player.id
  return <section className="mythfall-panel mythfall-scroll" aria-label="Inventory">
    {error && <InlineState kind="error">{error}</InlineState>}
    <FieldGroup title={`Your pack · ${inventory.length}`}><div className="mythfall-inventory">
      {inventory.map((entry) => <Button key={entry.id} aria-pressed={item?.id === entry.id} onClick={() => selectEntity(entry.id)} aria-label={`Select inventory ${entry.name}`}>
        <span className="mythfall-item-icon">{ICONS[entry.kind] ?? '◇'}</span><span>{entry.name}</span>
        <small>{player.equipped === entry.id ? 'Equipped' : `${entry.weight} wt`}</small>
      </Button>)}
      {!inventory.length && <p className="mythfall-note">Your pack is empty.</p>}
    </div></FieldGroup>
    {item && <FieldGroup title={item.name}>
      <p className="mythfall-note">{carried ? 'In your pack' : item.place.container ? 'Inside an open container' : item.place.ground ? 'Lying on the ground' : 'Carried by another character'} · Weight {item.weight}{item.magical_aura ? ' · Magical aura' : ''}</p>
      <div className="mythfall-buttons">{!carried ? <>
        <Button disabled={!canAct} onClick={() => act(item.place.carrier ? { kind: 'loot', target: item.place.carrier, item: item.id } : { kind: 'take', target: item.id })}>Pick up</Button>
        {item.place.ground && <Button disabled={!canAct} onClick={() => act({ kind: 'wait', ticks: 300, until: { kind: 'item_taken', target: item.id } })}>Watch for pickup</Button>}
      </> : <>
        <Button disabled={!canAct} onClick={() => act({ kind: 'drop', target: item.id })}>Drop</Button>
        {(item.damage > 0 || ['armor', 'shield'].includes(item.kind)) && <Button disabled={!canAct} onClick={() => act({ kind: 'equip', target: item.id })}>Equip</Button>}
        {['food', 'lantern', 'potion', 'wand', 'kit', 'container'].includes(item.kind) && <Button disabled={!canAct} onClick={() => act({ kind: 'use', target: item.id })}>{item.kind === 'food' ? 'Eat' : item.kind === 'container' ? 'Open / close' : 'Use'}</Button>}
        {item.message && <Button disabled={!canAct} onClick={() => act({ kind: 'read', target: item.id, open: true })}>{item.message.sealed ? 'Open & read' : 'Read'}</Button>}
      </>}</div>
      {carried && item.kind !== 'container' && <Select label="Put into" value="" disabled={!canAct} onChange={(recipient) => { if (recipient) void act({ kind: 'put', target: item.id, recipient }) }}
        options={[{ value: '', label: 'Choose an open container' }, ...Object.values(world.fixtures ?? {}).filter((fixture) => fixture.open && fixture.capacity).map((fixture) => ({ value: fixture.id, label: fixture.name }))]} />}
    </FieldGroup>}
    <FieldGroup title="Equipment"><div className="mythfall-buttons">{['weapon', 'shield', 'offhand', 'armor'].map((slot) =>
      <Button key={slot} disabled={!canAct} onClick={() => act({ kind: 'unequip', slot })}>Stow {slot}</Button>)}</div></FieldGroup>
    {ground.length > 0 && <FieldGroup title="Nearby items"><div className="mythfall-buttons">
      {ground.map((entry) => <Button key={entry.id} onClick={() => selectEntity(entry.id)} aria-label={`Inspect ${entry.place.ground ? 'ground' : 'nearby'} ${entry.name}`}>{entry.name}</Button>)}
    </div></FieldGroup>}
  </section>
}

export function MythfallConversationPanel() {
  const { world, actor, inventory, canAct, act, selectEntity, speech, setSpeech, openPanel, error } = useMythfallSession()
  return <section className="mythfall-panel mythfall-scroll" aria-label="Conversation">
    {error && <InlineState kind="error">{error}</InlineState>}
    {!world ? <div className="mythfall-padding"><InlineState>Create your character in Chat to enter Emberwick.</InlineState><Button onClick={() => openPanel('builtin.chat')}>Open Chat</Button></div> : <>
      <div className="mythfall-padding"><Select label="Person in view" value={actor?.id ?? ''} onChange={(id) => { if (id) selectEntity(id) }} options={[
        { value: '', label: 'Choose someone nearby' }, ...world.actors.filter((a) => a.id !== world.self.id).map((a) => ({ value: a.id, label: a.name })),
      ]} /></div>
      {actor ? <>
        <CharacterCard actor={actor} />
        <FieldGroup title="Conversation"><form className="mythfall-form" onSubmit={(event) => {
          event.preventDefault()
          if (canAct && speech.trim()) { void act({ kind: 'talk', target: actor.id, text: speech.trim() }); setSpeech('') }
        }}>
          <TextArea label={`Speak to ${actor.name}`} value={speech} onChange={setSpeech} placeholder="What would you like to say?" maxLength={1200} />
          <Button disabled={!canAct || !speech.trim()} type="submit" icon={MessageSquare}>Speak</Button>
        </form></FieldGroup>
        <FieldGroup title="Interact"><div className="mythfall-buttons">
          <Button disabled={!canAct} onClick={() => act({ kind: 'check', skill: 'insight', target: actor.id })}>Read intentions</Button>
          {actor.can_recruit && <Button disabled={!canAct} onClick={() => act({ kind: 'recruit', target: actor.id })}>Recruit</Button>}
          <Button disabled={!canAct} variant="danger" icon={Swords} onClick={() => act({ kind: 'attack', target: actor.id })}>Attack</Button>
        </div><Select label="Give an item" value="" disabled={!canAct} onChange={(id) => { if (id) void act({ kind: 'give', target: id, recipient: actor.id }) }} options={[
          { value: '', label: 'Choose from your pack' }, ...inventory.map((item) => ({ value: item.id, label: item.name })),
        ]} /></FieldGroup>
      </> : <InlineState>Select a person on the map to speak or interact. Only people currently in view are shown.</InlineState>}
      <EventLog speechOnly />
      <div className="mythfall-padding"><Button onClick={() => openPanel('mythfall.chat')}>View in Game chat</Button></div>
    </>}
  </section>
}

export function MythfallActionsPanel() {
  const { world, player, packet, error, busy, pauseRequested, canAct, act, cancel, intentText, setIntentText } = useMythfallSession()
  if (!world) return <InlineState>Time controls become available when your character enters the world.</InlineState>
  return <section className="mythfall-panel mythfall-scroll" aria-label="Actions and time">
    <div className="mythfall-padding mythfall-form">
      <form className="mythfall-intent" onSubmit={(event) => {
        event.preventDefault()
        if (canAct && intentText.trim()) { void act({ kind: 'ask', text: intentText.trim() }); setIntentText('') }
      }}><TextField label="Your action" value={intentText} onChange={setIntentText} maxLength={4000} placeholder="Wait here until someone takes the sword…" />
        <Button type="submit" disabled={!canAct || !intentText.trim()}>Act</Button></form>
      <div className="mythfall-buttons" role="group" aria-label="Pass time">
        <Button disabled={!canAct} onClick={() => act({ kind: 'wait', ticks: 1 })}>One turn</Button>
        <Button disabled={!canAct} onClick={() => act({ kind: 'wait', ticks: 10 })}>1 minute</Button>
        <Button disabled={!canAct} onClick={() => act({ kind: 'wait', ticks: 150 })}>15 minutes</Button>
        {player.rpg && <><Button disabled={!canAct || Boolean(world.combat)} onClick={() => act({ kind: 'short_rest', hit_dice: player.hp < player.max_hp ? player.rpg?.classes?.slice(0, 1) ?? [] : [] })}>Short rest · 1 hour</Button>
          <Button disabled={!canAct || Boolean(world.combat)} onClick={() => act({ kind: 'long_rest' })}>Long rest · 8 hours</Button></>}
        <Button disabled={!canAct} onClick={() => act({ kind: 'wait', until_hour: 6, activity: 'rest' })}>Until dawn</Button>
        {busy && <Button onClick={cancel} disabled={pauseRequested} icon={Pause}>{pauseRequested ? 'Pausing after current action…' : 'Pause'}</Button>}
        {!busy && world.pending_consequences > 0 && <Button onClick={() => act({ kind: 'resolve_events' })}>Resolve pending events</Button>}
        {!busy && world.pending?.status === 'running' && <><Button onClick={() => act({ kind: 'resume', wait_id: world.pending.id })}>Continue activity</Button><Button onClick={() => act({ kind: 'cancel', wait_id: world.pending.id })}>Cancel saved activity</Button></>}
      </div>
      <output className="mythfall-status" aria-live="polite">{REASONS[packet.result?.reason] || 'The world awaits your next action.'}</output>
    </div>
    {error && <InlineState kind="error">{error}</InlineState>}
    {packet.reply && <p className="mythfall-reply">{packet.reply}</p>}
    <FieldGroup title="Travel & watch">
      <Select label="Travel to" value="" disabled={!canAct} onChange={(id) => { if (id) void act({ kind: 'travel', target: id }) }} options={[
        { value: '', label: 'Choose a destination' }, ...Object.values(world.places).map((place) => ({ value: place.id, label: place.name })),
      ]} />
      <Select label="Watch for a person" value="" disabled={!canAct} onChange={(value) => {
        if (value) { const [kind, target] = value.split(':'); void act({ kind: 'wait', ticks: 600, until: { kind, target } }) }
      }} options={[{ value: '', label: 'Watch here for up to an hour' }, ...Object.entries(player.known).filter(([id]) => id.startsWith('char.')).flatMap(([id, known]) => [
        { value: `actor_arrived:${id}`, label: `${known.name} arrives` }, { value: `actor_departed:${id}`, label: `${known.name} leaves` },
      ])]} />
    </FieldGroup>
    <div className="mythfall-buttons mythfall-padding">{Object.values(world.doors).filter((door) => Math.abs(door.position[0] - player.position[0]) + Math.abs(door.position[1] - player.position[1]) <= 1).map((door) =>
      <Button key={door.id} disabled={!canAct} onClick={() => act({ kind: 'use', target: door.id })}>{door.open ? 'Close' : 'Open'} {door.name}</Button>)}</div>
  </section>
}

function EventLog({ speechOnly = false }) {
  const { world } = useMythfallSession()
  const recent = world?.events.filter((event) => speechOnly ? event.kind === 'speech' : !['move', 'inspect'].includes(event.kind)).slice(speechOnly ? -12 : -40) ?? []
  return <div className="mythfall-journal" aria-label={speechOnly ? 'Conversation history' : 'World journal'}>{recent.map((event) => <p key={event.sequence}>
    <time>{Math.floor(event.tick * 6 / 3600) % 24}:{String(Math.floor(event.tick * 6 / 60) % 60).padStart(2, '0')}</time>
    <span>{event.kind === 'speech' ? `${world.actors.find((actor) => actor.id === event.actor)?.name ?? world.self.known[event.actor]?.name ?? 'Someone'}: ` : ''}{event.text}
      {event.kind === 'check' && ` ${event.die} ${event.modifier >= 0 ? '+' : '−'} ${Math.abs(event.modifier)} against ${event.difficulty}: ${event.success ? 'success' : 'failure'}.`}</span>
  </p>)}</div>
}

export function MythfallJournalPanel() {
  const { packet, world, error } = useMythfallSession()
  return <section className="mythfall-panel mythfall-scroll" aria-label="Journal">
    {error && <InlineState kind="error">{error}</InlineState>}
    {packet?.reply && <p className="mythfall-reply">{packet.reply}</p>}
    {world?.quests?.map((quest) => <FieldGroup key={quest.id} title={quest.name}><p>{quest.description}</p><p>{quest.objective}</p><p className="mythfall-note">{quest.status}</p></FieldGroup>)}
    <EventLog />
  </section>
}

export function MythfallGamePanel({ panelId }) {
  if (panelId.startsWith('mythfall.abilities-')) return <MythfallAbilitiesPanel pinSlot={Number(panelId.split('-').at(-1)) - 1} />
  const Component = {
    'builtin.atlas': MythfallWorldPanel, 'mythfall.character': MythfallCharacterPanel,
    'mythfall.inventory': MythfallInventoryPanel, 'mythfall.conversation': MythfallConversationPanel,
    'mythfall.actions': MythfallActionsPanel, 'mythfall.journal': MythfallJournalPanel,
    'mythfall.chat': MythfallChatPanel,
    'mythfall.abilities': MythfallAbilitiesPanel, 'mythfall.party': MythfallPartyPanel,
  }[panelId]
  return Component ? <Component /> : <InlineState kind="error">Game panel is unavailable.</InlineState>
}
