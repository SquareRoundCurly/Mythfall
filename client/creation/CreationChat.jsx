import { useEffect, useRef, useSyncExternalStore } from 'react'
import { Button, InlineState, MessageContent, TextArea } from '@pocketrealms/ui'
import { useMythfallSession } from '../MythfallContext'
import { StatAssignmentMessage } from './StatAssignment'

export function CreationChat() {
  const { creation, world, connected, openPanel } = useMythfallSession()
  const state = useSyncExternalStore(creation.subscribe, creation.getSnapshot, creation.getSnapshot)
  const end = useRef(null)
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }) }, [state.messages])
  return <section className="mythfall-panel mythfall-creation-chat" aria-label="Character creation">
    {world && <div className="mythfall-padding"><Button onClick={() => openPanel('mythfall.chat')}>Continue in Game chat</Button></div>}
    <div className="mythfall-creation-history" role="log" aria-label="Character creation history">
      {state.hasMore && <Button disabled={state.loading} onClick={() => creation.refresh({ older: true })}>Earlier messages</Button>}
      {state.loading && <InlineState>Loading saved character creation…</InlineState>}
      {state.messages.filter(message => ['user', 'assistant'].includes(message.role) || message.event_type === 'component').map(message => {
        const view = { id: `archive-${message.id}`, archiveId: message.id, role: message.role,
          text: message.body, payload: message.payload, component: message.component }
        return <article className={`message message-${message.role === 'user' ? 'user' : 'realm'}`} key={message.id}>
          {message.label && <strong>{message.label}</strong>}
          {message.component === 'stat_assignment' ? <StatAssignmentMessage message={view}
            isRealtimeConnected={connected && !state.busy && !state.uncertain}
            onSendRealtimeCommand={(type, payload) => creation.componentAction(type, payload)}
            onMessageUpdated={() => {}} /> : <MessageContent message={view} />}
        </article>
      })}
      <div ref={end} />
    </div>
    {state.error && <InlineState kind="error">{state.error}</InlineState>}
    {(state.error || state.uncertain) && <div className="mythfall-padding mythfall-buttons">
      <Button disabled={state.loading} onClick={() => creation.refresh()}>Check saved history</Button>
      {state.uncertain && <Button disabled={state.loading || state.busy} onClick={() => creation.acknowledgeHistory()}>I checked history; continue</Button>}
    </div>}
    {state.busy && <InlineState>Character Creator is responding…</InlineState>}
    <form className="mythfall-chat-composer" onSubmit={event => { event.preventDefault(); void creation.send() }}>
      <TextArea label="Character concept" value={state.draft} onChange={value => creation.setDraft(value)} rows={3}
        placeholder="A name, a personality, and the kind of adventure you want…" maxLength={4000}
        onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void creation.send() } }} />
      <Button type="submit" disabled={!connected || state.loading || state.busy || state.uncertain || !state.draft.trim()}>Send to Character Creator</Button>
    </form>
  </section>
}
