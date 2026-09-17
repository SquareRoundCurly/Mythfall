import { useEffect, useRef, useState } from 'react'
import { ArrowDown, Pause, Send } from 'lucide-react'
import { Button, InlineState, TextArea } from '@pocketrealms/ui'
import { useMythfallSession } from './MythfallContext'

function timestamp(tick) {
  const minutes = Math.floor(tick / 10)
  return `Day ${Math.floor(minutes / 1440) + 1} · ${String(Math.floor(minutes / 60) % 24).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
}

export function MythfallChatPanel() {
  const { packet, world, player, busy, submission, error, canAct, act, cancel, intentText, setIntentText, openPanel } = useMythfallSession()
  const history = useRef(null)
  const follow = useRef(true)
  const [showLatest, setShowLatest] = useState(false)
  const turns = packet?.chat?.turns ?? []
  const available = Boolean(packet?.chat)
  useEffect(() => {
    if (follow.current && history.current) history.current.scrollTop = history.current.scrollHeight
  }, [packet?.chat?.revision, busy])
  useEffect(() => {
    const node = history.current
    const observer = new ResizeObserver(() => {
      if (follow.current && node.clientHeight) node.scrollTop = node.scrollHeight
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  function submit(event) {
    event.preventDefault()
    if (!canAct || !available || !intentText.trim()) return
    follow.current = true
    setShowLatest(false)
    void act({ kind: 'ask', text: intentText.trim() })
    setIntentText('')
  }
  const unacknowledged = submission && !turns.some((turn) => turn.id === submission.operationId)
  return <section className="mythfall-panel mythfall-game-chat" aria-label="Game chat">
    <div className="mythfall-chat-history" ref={history} role="log" aria-label="Game history" aria-live="polite" aria-relevant="additions text"
      onScroll={() => {
        const node = history.current
        follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 48
        setShowLatest(!follow.current)
      }}>
      {world && !available && <InlineState>Start a new Mythfall session to use saved Game chat now. Existing sessions gain it after their game server restarts.</InlineState>}
      {!turns.length && (!world || available) && <div className="mythfall-chat-welcome"><h3>What do you do?</h3>
        <p>Describe an action, ask about the world, or say something to a nearby person.</p>
        <p>Actions from your pack, the map, and other game panels appear here too.</p>
        {!world && <Button onClick={() => openPanel('builtin.chat')}>Create your character in Chat</Button>}
      </div>}
      {turns.map((turn) => <article className="mythfall-chat-turn" key={turn.id} data-status={turn.status}>
        <div className="mythfall-chat-player"><header><strong>{player?.name ?? 'You'}</strong><time>{timestamp(turn.tick)}</time></header><p>{turn.player}</p></div>
        {turn.messages.map((message) => <div className="mythfall-chat-message" key={message.id}>
          <strong>{message.speaker}</strong><p>{message.text}</p>
        </div>)}
        <p className="mythfall-chat-outcome"><span>{turn.status === 'rejected' ? 'Could not act · ' : ''}</span>{turn.summary}</p>
      </article>)}
      {busy && <div className="mythfall-chat-pending" role="status">
        {unacknowledged && submission.intent.text && <p>{submission.intent.text}</p>}
        <span>Resolving your action…</span>
      </div>}
    </div>
    {showLatest && <Button className="mythfall-chat-latest" icon={ArrowDown} onClick={() => {
      follow.current = true; setShowLatest(false); history.current.scrollTop = history.current.scrollHeight
    }}>Latest</Button>}
    {error && <InlineState kind="error">{error}</InlineState>}
    {!busy && world?.pending?.status === 'running' && <div className="mythfall-padding mythfall-buttons">
      <Button onClick={() => act({ kind: 'resume', wait_id: world.pending.id })}>Continue saved activity</Button>
      <Button icon={Pause} onClick={() => act({ kind: 'cancel', wait_id: world.pending.id })}>Pause saved activity</Button>
    </div>}
    <form className="mythfall-chat-composer" onSubmit={submit}>
      <TextArea label="Your intent" value={intentText} onChange={setIntentText} maxLength={4000} rows={3}
        placeholder="I ask Nessa about the village…" onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) submit(event)
        }} />
      <div className="mythfall-chat-send"><span>Time advances when you act.</span>
        {busy && <Button icon={Pause} onClick={cancel}>Pause activity</Button>}
        <Button type="submit" icon={Send} disabled={!canAct || !available || !intentText.trim()}>Send intent</Button>
      </div>
    </form>
  </section>
}
