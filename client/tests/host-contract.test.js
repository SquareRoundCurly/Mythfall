import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import * as jsxRuntime from 'react/jsx-runtime'
import { panels } from '../registry.js'

const atlas = { id: 'builtin.atlas', tabId: 'builtin.atlas', panelId: 'panel.builtin.atlas', title: 'Atlas' }

test('the game registers only Atlas from either host generation', () => {
  const older = [atlas, { id: 'builtin.chat' }, { id: 'builtin.files' }, { id: 'builtin.scene' }]
  assert.deepEqual(panels(older), panels([atlas]))
  assert.ok(panels(older).some(panel => panel.id === 'mythfall.creation'))
  assert.ok(panels(older).every(panel => panel.id === 'builtin.atlas' || panel.id.startsWith('mythfall.')))
})

test('the built package loads in cached and current hosts without optional services', async () => {
  const { createModuleUi } = await import('../../build/client/panels.js')
  for (const sharedMessageUi of [undefined, () => null]) {
    const host = { React, jsxRuntime, atlas: {}, ui: { MessageContent: sharedMessageUi }, builtinPanels: [atlas] }
    const module = createModuleUi(host)
    assert.equal(module.contract, 1)
    assert.equal(typeof module.SessionProvider, 'function')
    assert.ok(module.panels.some(panel => panel.id === 'mythfall.creation'))
    assert.equal(module.renderPanel({ id: 'mythfall.creation' }).props.panelId, 'mythfall.creation')
  }
})
