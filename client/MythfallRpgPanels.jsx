import { useState } from 'react'
import { Button, FieldGroup, InlineState, Select, TextField } from '@pocketrealms/ui'
import { useMythfallSession } from './MythfallContext'
import { Portrait } from './Portrait'

const readable = (value) => String(value ?? '').replaceAll('_', ' ')

function durationLabel(ticks) {
  if (!Number.isInteger(ticks) || ticks <= 0) return ''
  const seconds = ticks * 6
  const [value, unit] = seconds % 3600 === 0 ? [seconds / 3600, 'hour']
    : seconds % 60 === 0 ? [seconds / 60, 'minute'] : [seconds, 'second']
  return `${value} ${unit}${value === 1 ? '' : 's'}`
}

export function CharacterSelector() {
  const { world, characterId, setCharacterId } = useMythfallSession()
  if (!world?.characters) return null
  return <Select label="Character" value={characterId} onChange={setCharacterId}
    options={Object.values(world?.characters ?? {}).map((actor) => ({ value: actor.id, label: actor.name }))} />
}

function EarlierRealm() {
  return <InlineState>This realm is running an earlier Mythfall version. Start a new Mythfall realm to use classes, abilities and party encounters.</InlineState>
}

export function Resources({ actor }) {
  return <div className="mythfall-resources">{Object.entries(actor.rpg?.resources ?? {}).map(([key, value]) =>
    <div key={key}><span>{readable(key)}</span><strong>{value.current} / {value.max}</strong><small>{readable(value.recovery)} recovery</small></div>)}</div>
}

export function CompanionRelationship({ actor }) {
  if (!Number.isFinite(actor.relationship)) return null
  return <p className="mythfall-note">Relationship with you: <strong>{actor.relationship > 0 ? '+' : ''}{actor.relationship}</strong> (−10 to +10)</p>
}

export function Progression({ actor }) {
  const { world, player, act, canAct } = useMythfallSession()
  const [choice, setChoice] = useState('fighter')
  const classes = actor.rpg?.classes ?? []
  const playerOwns = actor.id === player.id
  return <>
    <FieldGroup title={`Level ${classes.length || '—'} · ${actor.rpg?.xp ?? 0} XP`}>
      <p>{classes.length ? Object.entries(classes.reduce((counts, name) => ({ ...counts, [name]: (counts[name] ?? 0) + 1 }), {}))
        .map(([name, level]) => `${world.classes?.[name]?.name ?? name} ${level}`).join(' / ') : 'Choose your first class to receive its features and equipment.'}</p>
      <p className="mythfall-note">{Object.values(actor.rpg?.subclasses ?? {}).map(readable).join(' · ')}
        {actor.next_level_xp != null && ` · Next level: ${actor.next_level_xp} XP`}</p>
      {actor.can_level && <div className="mythfall-form"><Select label={classes.length ? 'Next class level' : 'Starting class'} value={choice} onChange={setChoice}
        options={Object.entries(world.classes ?? {}).map(([id, cls]) => ({ value: id, label: `${cls.name} · ${readable(cls.subclass)}` }))} />
        <Button disabled={!canAct} onClick={() => act(playerOwns ? { kind: 'choose_class', class: choice }
          : { kind: 'ask', text: `Discuss ${actor.name} taking their next earned level in ${choice}.` })}>{classes.length ? 'Take earned level' : 'Begin this class'}</Button>
        <p className="mythfall-note">Uses the class's starting choices. Describe specific skills, spells or a fighting style in Game chat to customize them.</p></div>}
    </FieldGroup>
    <FieldGroup title="Skills & features"><p>{(actor.rpg?.skills ?? []).map((key) => `${readable(key)}${actor.rpg?.expertise?.includes(key) ? ' (expertise)' : ''}`).join(' · ') || 'No class skills yet'}</p>
      <p className="mythfall-note">{actor.rpg?.features?.map(readable).join(' · ')}</p></FieldGroup>
    <FieldGroup title="Resources"><Resources actor={actor} /></FieldGroup>
  </>
}

export function MythfallAbilitiesPanel({ pinSlot = null }) {
  const { world, player, character, pins, pinAbility, canAct, act, error } = useMythfallSession()
  const [abilityId, setAbilityId] = useState('')
  const [targets, setTargets] = useState([])
  const [pointX, setPointX] = useState('')
  const [pointY, setPointY] = useState('')
  const [slot, setSlot] = useState('1')
  const [option, setOption] = useState('halt')
  const actor = pinSlot == null ? character : world?.characters?.[pins[pinSlot]]
  if (!world) return <InlineState>Your abilities appear after character creation.</InlineState>
  if (!world.characters) return <EarlierRealm />
  if (!actor) return <section className="mythfall-panel mythfall-scroll mythfall-padding"><CharacterSelector /><InlineState>This pinned character is no longer in the party. Choose a character in Abilities and pin their panel.</InlineState></section>
  const abilities = actor.abilities ?? []
  const ability = abilities.find((entry) => entry.id === abilityId) ?? abilities[0]
  const self = actor.id === player.id
  const pointTarget = ability && ['point', 'cone', 'cube'].includes(ability.target)
  const needsTarget = ability && ['creature', 'object'].includes(ability.target)
  const targetLimit = (ability?.max_targets ?? 1) + (['ability.bless@1', 'ability.command@1'].includes(ability?.id) ? Math.max(0, Number(slot) - ability.level) : 0)
  const options = ability?.target === 'object' ? [...world.items, ...Object.values(world.fixtures ?? {})] : world.actors
  const eligible = targets.filter((id) => options?.some((entry) => entry.id === id))
  function activate() {
    if (!ability) return
    if (!self) {
      void act({ kind: 'order', target: actor.id, text: `Please use ${ability.name}${eligible.length ? ` on ${eligible.map((id) => options.find((entry) => entry.id === id)?.name).join(', ')}` : ''}.` })
      return
    }
    const intent = { kind: ability.economy === 'reaction' ? 'reaction' : 'ability', ability: ability.id }
    if (needsTarget) { intent.targets = eligible; intent.target = eligible[0] }
    if (pointTarget) intent.position = [Number(pointX), Number(pointY)]
    if (ability.level) intent.slot = Math.max(ability.level, Number(slot))
    if (ability.mechanic === 'command') intent.command = option
    if (ability.mechanic === 'restoration') intent.condition = ['blinded', 'deafened', 'paralyzed', 'poisoned'].includes(option) ? option : 'poisoned'
    void act(intent)
  }
  return <section className="mythfall-panel mythfall-scroll" aria-label="Character abilities">
    <div className="mythfall-padding mythfall-form">{pinSlot == null && <CharacterSelector />}
      <div className="mythfall-buttons"><h3>{actor.name}</h3><Button onClick={() => pinAbility(actor.id)}>Pin abilities</Button></div>
      {!self && <p className="mythfall-note">Companions decide their own actions. An ability request becomes an order in Game chat.</p>}
    </div>
    {error && <InlineState kind="error">{error}</InlineState>}
    <FieldGroup title="Resources"><Resources actor={actor} /></FieldGroup>
    <FieldGroup title="Features & spells">
      {!abilities.length ? <InlineState>Choose a class to gain features. Passive features are shown on the character sheet.</InlineState> : <div className="mythfall-form">
        <Select label="Ability" value={ability.id} onChange={(id) => { setAbilityId(id); setTargets([]) }} options={abilities.map((entry) => ({ value: entry.id, label: entry.name }))} />
        <p>{ability.description}</p>
        {durationLabel(ability.duration) && <p className="mythfall-note mythfall-ability-duration">Duration {durationLabel(ability.duration)}</p>}
        <p className="mythfall-note">{readable(ability.economy)} · Range {ability.range * 5} ft{ability.level ? ` · Level ${ability.level} spell` : ''}{ability.concentration ? ' · Concentration' : ''}</p>
        {ability.level > 0 && <Select label="Spell slot" value={String(Math.max(ability.level, Number(slot)))} onChange={setSlot}
          options={[1, 2].filter((level) => level >= ability.level && actor.rpg.resources[`slot_${level}`]).map((level) => ({ value: String(level), label: `Level ${level} (${actor.rpg.resources[`slot_${level}`].current} left)` }))} />}
        {needsTarget && <div className="mythfall-targets" aria-label="Ability targets">{options.map((entry) => <Button key={entry.id} aria-pressed={eligible.includes(entry.id)}
          onClick={() => setTargets((selected) => selected.includes(entry.id) ? selected.filter((id) => id !== entry.id) : targetLimit === 1 ? [entry.id] : [...selected, entry.id].slice(-targetLimit))}>{entry.name}</Button>)}</div>}
        {pointTarget && <div className="mythfall-buttons"><TextField label="Map X" type="number" value={pointX} onChange={setPointX} /><TextField label="Map Y" type="number" value={pointY} onChange={setPointY} /></div>}
        {ability.mechanic === 'command' && <Select label="Command" value={option} onChange={setOption} options={['approach', 'drop', 'flee', 'grovel', 'halt'].map((value) => ({ value, label: readable(value) }))} />}
        {ability.mechanic === 'restoration' && <Select label="Remove condition" value={option === 'halt' ? 'poisoned' : option} onChange={setOption} options={['blinded', 'deafened', 'paralyzed', 'poisoned'].map((value) => ({ value, label: readable(value) }))} />}
        <Button disabled={!canAct || (self && Boolean(ability.unavailable)) || (needsTarget && !eligible.length) || (pointTarget && (pointX === '' || pointY === ''))} onClick={activate}>{self ? 'Use ability' : 'Request ability'}</Button>
        {ability.unavailable && <p className="mythfall-note" role="status">{ability.unavailable}</p>}
      </div>}
    </FieldGroup>
    <FieldGroup title="Active effects">{actor.effects?.length ? actor.effects.map((effect) => <p key={effect.id}>{readable(effect.label)} · {effect.remaining_ticks * 6}s remaining</p>) : <p className="mythfall-note">No active effects</p>}</FieldGroup>
    {self && Object.keys(actor.prepare_options ?? {}).length > 0 && <SpellPreparation actor={actor} />}
  </section>
}

function SpellPreparation({ actor }) {
  const { world, canAct, act } = useMythfallSession()
  const [choice, setChoice] = useState(Object.keys(actor.prepare_options)[0])
  const [prepared, setPrepared] = useState(null)
  const selected = prepared ?? actor.rpg.prepared_by_class?.[choice] ?? []
  return <FieldGroup title="Prepare spells after a long rest"><div className="mythfall-form">
    <Select label="Spellcasting class" value={choice} onChange={(name) => { setChoice(name); setPrepared(null) }} options={Object.keys(actor.prepare_options).map((name) => ({ value: name, label: readable(name) }))} />
    <div className="mythfall-targets">{(actor.prepare_options[choice] ?? []).map((id) => <Button key={id} aria-pressed={selected.includes(id)} onClick={() => setPrepared(selected.includes(id) ? selected.filter((value) => value !== id) : [...selected, id])}>{world.ability_names[id] ?? id}</Button>)}</div>
    <Button disabled={!canAct || world.combat} onClick={() => act({ kind: 'prepare', class: choice, abilities: selected })}>Prepare selected spells</Button>
  </div></FieldGroup>
}

export function MythfallPartyPanel() {
  const { world, player, canAct, act, workspaceClient, setCharacterId, openPanel, pinAbility, error } = useMythfallSession()
  if (!world) return <InlineState>Your party appears when the adventure begins.</InlineState>
  if (!world.characters) return <EarlierRealm />
  const combat = world.combat
  return <section className="mythfall-panel mythfall-scroll" aria-label="Party and initiative">
    {error && <InlineState kind="error">{error}</InlineState>}
    <FieldGroup title={`Party · ${world.party?.members.length ?? 1} / ${world.party?.limit ?? 4}`}>
      {Object.values(world.characters ?? {}).map((actor) => <div className="mythfall-party-member" key={actor.id}>
        <Portrait actor={actor} workspaceClient={workspaceClient} /><div><strong>{actor.name}</strong><p>{actor.hp}/{actor.max_hp} HP · AC {actor.armor_class} · Mood {actor.mood}</p>
          <CompanionRelationship actor={actor} />
          <div className="mythfall-buttons"><Button onClick={() => { setCharacterId(actor.id); openPanel('mythfall.character') }}>Sheet</Button><Button onClick={() => pinAbility(actor.id)}>Abilities</Button>
            {actor.id !== player.id && <Button disabled={!canAct} onClick={() => act({ kind: 'dismiss', target: actor.id })}>Dismiss</Button>}</div></div>
      </div>)}
      <p className="mythfall-note">Speak to nearby characters to ask whether they will join.</p>
    </FieldGroup>
    <FieldGroup title={combat ? `Initiative · Round ${combat.round}` : 'No active encounter'}>
      {combat && <>
        <ol className="mythfall-initiative">{combat.participants.map((entry) => <li key={entry.id} aria-current={combat.awaiting === entry.id ? 'step' : undefined}>
          <strong>{world.actors.find((actor) => actor.id === entry.id)?.name ?? 'Unseen participant'}</strong><span>{entry.initiative} · {entry.side}</span></li>)}</ol>
        <p>{combat.needs_npc ? 'The next participant has a decision.' : 'Your decision.'}</p>
        {combat.economy && <p className="mythfall-note">Action {combat.economy.action} · Bonus {combat.economy.bonus} · Reaction {combat.economy.reaction} · Movement {combat.economy.movement * 5} ft</p>}
        <div className="mythfall-buttons">{combat.needs_npc ? <Button disabled={!canAct} onClick={() => act({ kind: 'continue_combat' })}>Continue NPC turn</Button>
          : combat.reaction ? <><Button disabled={!canAct} onClick={() => act({ kind: 'reaction', ability: combat.reaction.options[0] })}>{({ protection: 'Protect ally', spell_protection: 'Protect ally', opportunity: 'Opportunity attack' })[combat.reaction.kind] ?? 'Cast Shield'}</Button><Button disabled={!canAct} onClick={() => act({ kind: 'reaction' })}>Pass reaction</Button></>
            : <>{['dodge', 'dash', 'disengage', 'end_turn', 'retreat', 'offer_truce'].map((kind) => <Button key={kind} disabled={!canAct} onClick={() => act({ kind })}>{readable(kind)}</Button>)}</>}</div>
      </>}
    </FieldGroup>
  </section>
}
