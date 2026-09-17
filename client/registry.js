export function panels(builtinPanels) { return [
  ...builtinPanels.map((panel) => (
    panel.id === 'builtin.atlas' ? { ...panel, title: 'World', size: 5 }
      : panel.id === 'builtin.chat' ? { ...panel, size: 1 } : panel
  )),
  ...[
    ['chat', 'Game chat'], ['character', 'Character'], ['inventory', 'Inventory'],
    ['conversation', 'Conversation'], ['actions', 'Actions & time'], ['journal', 'Journal'],
    ['abilities', 'Abilities'], ['party', 'Party & initiative'],
  ].map(([name, title]) => ({
    id: `mythfall.${name}`, tabId: `mythfall.${name}`, panelId: `panel.mythfall.${name}`,
    title, size: 1, defaultOpen: true, kind: 'mythfall',
  })),
  ...[1, 2, 3, 4].map((slot) => ({ id: `mythfall.abilities-${slot}`, tabId: `mythfall.abilities-${slot}`,
    panelId: `panel.mythfall.abilities-${slot}`, title: `Pinned abilities ${slot}`, size: 1, defaultOpen: false, kind: 'mythfall' })),
]
}

export function defaultLayout({ compact = false } = {}) {
  const pane = (id, size, ...tabs) => ({ id: `panel.${id}`, size, activeId: tabs[0], tabs: tabs.map((id) => ({ id })) })
  if (compact) return {
    dockbox: { id: 'mythfall.dock', mode: 'horizontal', children: [pane('mythfall.mobile', 1,
      'builtin.atlas', 'mythfall.chat', 'mythfall.character', 'mythfall.inventory', 'mythfall.conversation',
      'mythfall.abilities', 'mythfall.party', 'mythfall.actions', 'mythfall.journal', 'builtin.chat')] },
  }
  return {
    dockbox: { id: 'mythfall.dock', mode: 'horizontal', children: [
      { id: 'mythfall.character-column', mode: 'vertical', size: 2, children: [
        pane('mythfall.character', 3, 'mythfall.character', 'mythfall.abilities'),
        pane('mythfall.inventory', 2, 'mythfall.inventory'),
      ] },
      { id: 'mythfall.world-column', mode: 'vertical', size: 5, children: [
        pane('builtin.atlas', 3, 'builtin.atlas'),
        pane('mythfall.actions', 1, 'mythfall.actions'),
      ] },
      { id: 'mythfall.story-column', mode: 'vertical', size: 2.5, children: [
        pane('mythfall.conversation', 3, 'mythfall.chat', 'mythfall.conversation', 'builtin.chat'),
        pane('mythfall.journal', 2, 'mythfall.party', 'mythfall.journal'),
      ] },
    ] },
  }
}
