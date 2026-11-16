// Character creation uses the module's existing durable chat and component
// operations. This client observes history; reads never initiate agent turns.
export class CreationConversation {
  constructor({ sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)) } = {}) {
    this.sleep = sleep
    this.listeners = new Set()
    this.epoch = 0
    this.active = false
    this.request = null
    this.seenEvents = new Set()
    this.seenPayloads = new WeakSet()
    this.state = { messages: [], draft: '', loading: false, busy: false, error: '', uncertain: false, hasMore: false }
    this.getSnapshot = () => this.state
    this.subscribe = listener => { this.listeners.add(listener); return () => this.listeners.delete(listener) }
  }

  emit(patch) {
    this.state = { ...this.state, ...patch }
    for (const listener of this.listeners) listener()
  }

  connect(request, connected, onChanged) {
    const epoch = ++this.epoch
    this.active = connected
    this.request = request
    this.onChanged = onChanged
    if (this.state.busy) this.emit({ busy: false, uncertain: true,
      error: 'The connection changed during character creation. Check saved history before continuing.' })
    if (connected) void this.refresh()
    return () => { if (this.epoch === epoch) { this.active = false; this.epoch += 1 } }
  }

  setDraft(value) { this.emit({ draft: value }) }

  async mutate(type, payload, epoch) {
    for (let attempt = 0; ; attempt += 1) {
      if (!this.active || epoch !== this.epoch) {
        throw Object.assign(new Error('The character creation connection changed.'), { definitelyUnsent: true })
      }
      try { return await this.request(type, payload) } catch (error) {
        // This server refusal occurs before any mutation. Autosave can briefly
        // hold the same fence; unknown outcomes and other errors never replay.
        if (!['chat_mutation_busy', 'workspace_mutation_busy'].includes(error.code)
          || error.completionUnknown === true || attempt >= 4) throw error
        await this.sleep(100 * 2 ** attempt)
      }
    }
  }

  merge(messages) {
    const known = new Map(this.state.messages.map(message => [message.id, message]))
    for (const message of messages ?? []) known.set(message.id, message)
    const next = [...known.values()].sort((left, right) => left.id - right.id)
    this.emit({ messages: next })
    const isFinal = message => message.role === 'assistant' && message.event_type !== 'agent.commentary'
    const nextVisible = next.find(message => message.id > this.pendingReply && (message.role === 'user' || isFinal(message)))
    if (this.pendingReply && (next.some(message => isFinal(message) && message.payload?.reply_to_message_id === this.pendingReply)
      || (nextVisible && isFinal(nextVisible) && !nextVisible.payload?.reply_to_message_id))) {
      this.pendingReply = null
      this.emit({ uncertain: false, error: '' })
    }
  }

  async refresh({ older = false } = {}) {
    if (!this.active || typeof this.request !== 'function') return
    const epoch = this.epoch
    this.emit({ loading: true })
    try {
      const before = older ? this.state.messages[0]?.id : undefined
      const response = await this.request('chat.history', { limit: 100,
        ...(before ? { before_message_id: before } : {}) })
      if (!this.active || epoch !== this.epoch) return
      this.merge(response.payload.messages)
      this.emit({ hasMore: response.payload.has_more === true })
    } catch (error) {
      if (this.active && epoch === this.epoch) this.emit({ error: error.message })
    } finally {
      if (this.active && epoch === this.epoch) this.emit({ loading: false })
    }
  }

  receive(message, eventId) {
    if (!message || typeof message !== 'object') return
    if (eventId != null) {
      if (this.seenEvents.has(eventId)) return
      this.seenEvents.add(eventId)
      if (this.seenEvents.size > 2000) this.seenEvents.delete(this.seenEvents.values().next().value)
    } else {
      if (this.seenPayloads.has(message)) return
      this.seenPayloads.add(message)
    }
    if (message?.type === 'chat.message.created') this.merge([message.payload.user_message])
    if (['chat.messages.created', 'chat.reply.created', 'component.action.result'].includes(message?.type)) {
      this.merge(message.payload?.messages)
    }
    if (message?.type === 'chat.history.changed') {
      this.emit({ messages: [], uncertain: false, error: '' })
      void this.refresh()
    }
  }

  async send() {
    const text = this.state.draft.trim()
    if (!this.active || this.state.busy || this.state.uncertain || !text) return
    const epoch = this.epoch
    this.emit({ busy: true, error: '' })
    let phase = 'message'
    try {
      const created = await this.mutate('chat.message.create', { message: text }, epoch)
      if (!this.active || epoch !== this.epoch) return
      this.merge([created.payload.user_message])
      this.pendingReply = created.payload.user_message.id
      this.emit({ draft: '' })
      phase = 'reply'
      const response = await this.mutate('chat.reply.create', { message_id: this.pendingReply }, epoch)
      if (!this.active || epoch !== this.epoch) return
      this.merge(response.payload.messages)
      this.pendingReply = null
      await this.onChanged?.()
    } catch (error) {
      if (!this.active || epoch !== this.epoch) return
      const unknown = error.definitelyUnsent !== true && (error.completionUnknown === true || error instanceof TypeError)
      this.emit({ uncertain: unknown, error: unknown
        ? `The ${phase === 'message' ? 'message' : 'reply'} result is unknown. Check saved history before continuing; it was not resent.`
        : error.message })
      await this.refresh()
    } finally {
      if (this.active && epoch === this.epoch) this.emit({ busy: false })
    }
  }

  async componentAction(_type, payload) {
    if (!this.active || this.state.busy || this.state.uncertain) throw new Error('Character creation is not ready for another action.')
    const epoch = this.epoch
    this.emit({ busy: true, error: '' })
    try {
      const response = await this.mutate('component.action', payload, epoch)
      if (this.active && epoch === this.epoch) {
        this.merge(response.payload.messages)
        await this.refresh()
        await this.onChanged?.()
      }
      return response
    } catch (error) {
      if (this.active && epoch === this.epoch) {
        this.emit({ error: error.message, uncertain: error.completionUnknown === true || error instanceof TypeError })
        await this.refresh()
      }
      throw error
    } finally {
      if (this.active && epoch === this.epoch) this.emit({ busy: false })
    }
  }

  acknowledgeHistory() {
    if (this.state.busy) return
    this.pendingReply = null
    this.emit({ uncertain: false, error: '' })
  }
}
