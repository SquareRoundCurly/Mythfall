import assert from 'node:assert/strict'
import test from 'node:test'
import { CreationConversation } from '../creation/CreationConversation.js'

const turn = () => new Promise(resolve => setTimeout(resolve, 0))

test('character creation reads history without starting a turn and tab subscriptions do not repeat a send', async () => {
  const messages = [{ id: 1, role: 'assistant', body: 'Welcome' }]
  const calls = []
  let complete
  const pending = new Promise(resolve => { complete = resolve })
  const conversation = new CreationConversation()
  conversation.connect(async (type, payload) => {
    calls.push([type, payload])
    if (type === 'chat.history') return { payload: { messages: [...messages] } }
    if (type === 'chat.message.create') {
      const user = { id: 2, role: 'user', body: payload.message }
      messages.push(user)
      return { payload: { user_message: user } }
    }
    if (type === 'chat.reply.create') return pending
    throw new Error(`Unexpected ${type}`)
  }, true)
  await turn()
  assert.deepEqual(calls.map(([type]) => type), ['chat.history'])
  conversation.setDraft('A scholarly ranger')
  const send = conversation.send()
  await turn()
  const closeTab = conversation.subscribe(() => {})
  closeTab()
  conversation.subscribe(() => {})
  assert.equal(conversation.getSnapshot().busy, true)
  complete({ payload: { messages: [{ id: 3, role: 'assistant', body: 'Assign your stats', payload: { reply_to_message_id: 2 } }] } })
  await send
  assert.deepEqual(calls.map(([type]) => type), ['chat.history', 'chat.message.create', 'chat.reply.create'])
  assert.equal(conversation.getSnapshot().messages.length, 3)
  assert.equal(conversation.getSnapshot().busy, false)
})

test('unknown reply is not replayed and only its observed completion clears uncertainty', async () => {
  const calls = []
  const messages = [{ id: 2, role: 'user', body: 'A healer' }]
  const conversation = new CreationConversation()
  conversation.connect(async type => {
    calls.push(type)
    if (type === 'chat.history') return { payload: { messages } }
    if (type === 'chat.message.create') return { payload: { user_message: messages[0] } }
    throw Object.assign(new Error('Reply result lost'), { completionUnknown: true })
  }, true)
  await turn()
  conversation.setDraft('A healer')
  await conversation.send()
  assert.equal(conversation.getSnapshot().uncertain, true)
  await conversation.send()
  assert.equal(calls.filter(type => type === 'chat.reply.create').length, 1)
  conversation.receive({ type: 'chat.messages.created', payload: { messages: [
    { id: 3, role: 'assistant', event_type: 'agent.commentary', body: 'Working', payload: { reply_to_message_id: 2 } },
  ] } }, 'commentary')
  assert.equal(conversation.getSnapshot().uncertain, true)
  conversation.receive({ type: 'chat.reply.created', payload: { messages: [
    { id: 4, role: 'assistant', body: 'Done', payload: { reply_to_message_id: 2 } },
  ] } }, 'final')
  assert.equal(conversation.getSnapshot().uncertain, false)
})

test('retained invalidation events are not replayed on each new message', async () => {
  let reads = 0
  const conversation = new CreationConversation()
  conversation.connect(async () => { reads += 1; return { payload: { messages: [] } } }, true)
  await turn()
  const invalidate = { type: 'chat.history.changed', payload: {} }
  conversation.receive(invalidate, 1)
  await turn()
  conversation.receive({ type: 'chat.message.created', payload: { user_message: { id: 5, role: 'user', body: 'New concept' } } }, 2)
  conversation.receive(invalidate, 1)
  assert.equal(reads, 2)
  assert.equal(conversation.getSnapshot().messages[0].body, 'New concept')
})

test('a late result from a disconnected scope cannot trigger another creation operation', async () => {
  let resolveMessage
  const calls = []
  const conversation = new CreationConversation()
  const disconnect = conversation.connect(async type => {
    calls.push(type)
    if (type === 'chat.history') return { payload: { messages: [] } }
    return new Promise(resolve => { resolveMessage = resolve })
  }, true)
  await turn()
  conversation.setDraft('A wizard')
  const send = conversation.send()
  disconnect()
  resolveMessage({ payload: { user_message: { id: 3, role: 'user', body: 'A wizard' } } })
  await send
  assert.deepEqual(calls, ['chat.history', 'chat.message.create'])
  assert.deepEqual(conversation.getSnapshot().messages, [])
})

test('a read-only history failure does not make existing gameplay uncertain', async () => {
  const conversation = new CreationConversation()
  conversation.connect(async () => { throw new Error('History unavailable') }, true)
  await turn()
  assert.equal(conversation.getSnapshot().loading, false)
  assert.equal(conversation.getSnapshot().busy, false)
  assert.equal(conversation.getSnapshot().uncertain, false)
  assert.equal(conversation.getSnapshot().error, 'History unavailable')
})

test('explicit history acknowledgement unblocks future actions without replaying an uncertain component', async () => {
  let mutations = 0
  const conversation = new CreationConversation()
  conversation.connect(async type => {
    if (type === 'chat.history') return { payload: { messages: [] } }
    mutations += 1
    throw Object.assign(new Error('Component result lost'), { completionUnknown: true })
  }, true)
  await turn()
  await assert.rejects(conversation.componentAction('component.action', { message_id: 4 }), /result lost/)
  assert.equal(conversation.getSnapshot().uncertain, true)
  await assert.rejects(conversation.componentAction('component.action', { message_id: 4 }), /not ready/)
  await conversation.refresh()
  conversation.acknowledgeHistory()
  assert.equal(conversation.getSnapshot().uncertain, false)
  assert.equal(mutations, 1)
})

test('autosave contention retries only explicit unapplied refusals for each creation operation', async () => {
  const applied = []
  const attempts = new Map()
  const delays = []
  const conversation = new CreationConversation({ sleep: async delay => { delays.push(delay) } })
  conversation.connect(async (type, payload) => {
    if (type === 'chat.history') return { payload: { messages: [] } }
    const count = (attempts.get(type) ?? 0) + 1
    attempts.set(type, count)
    if (count === 1) throw Object.assign(new Error('Busy'), { code: 'chat_mutation_busy' })
    applied.push([type, payload])
    if (type === 'chat.message.create') return { payload: { user_message: { id: 2, role: 'user', body: payload.message } } }
    return { payload: { messages: [{ id: 3, role: 'assistant', body: 'Ready', payload: { reply_to_message_id: 2 } }] } }
  }, true)
  await turn()
  conversation.setDraft('A ranger')
  await conversation.send()
  await conversation.componentAction('component.action', { message_id: 3, action: 'submit_stat_assignment' })
  assert.deepEqual(applied.map(([type]) => type), ['chat.message.create', 'chat.reply.create', 'component.action'])
  assert.equal(applied[1][1].message_id, 2)
  assert.deepEqual(delays, [100, 100, 100])
  assert.equal(conversation.getSnapshot().busy, false)
})

test('disconnecting during a busy delay cannot send on the replaced connection', async () => {
  let release
  let writes = 0
  const conversation = new CreationConversation({ sleep: () => new Promise(resolve => { release = resolve }) })
  const disconnect = conversation.connect(async type => {
    if (type === 'chat.history') return { payload: { messages: [] } }
    writes += 1
    throw Object.assign(new Error('Busy'), { code: 'chat_mutation_busy' })
  }, true)
  conversation.setDraft('A ranger')
  const sent = conversation.send()
  await turn()
  disconnect()
  release()
  await sent
  assert.equal(writes, 1)
})

test('busy retries stop after five refusals and never retry a completion-unknown result', async () => {
  for (const completionUnknown of [false, true]) {
    let writes = 0
    const conversation = new CreationConversation({ sleep: async () => {} })
    conversation.connect(async type => {
      if (type === 'chat.history') return { payload: { messages: [] } }
      writes += 1
      throw Object.assign(new Error('Busy'), { code: 'chat_mutation_busy', completionUnknown })
    }, true)
    conversation.setDraft('A ranger')
    await conversation.send()
    assert.equal(writes, completionUnknown ? 1 : 5)
    assert.equal(conversation.getSnapshot().uncertain, completionUnknown)
  }
})
