import { Backpack, BookOpen, Clock3, MessageSquare, Sparkles, UserRound, Users } from 'lucide-react'
import { MythfallGamePanel } from './MythfallPanels'
import { MythfallSession } from './MythfallSession'
import { panels, defaultLayout } from './registry.js'

const icons = {
  chat: MessageSquare, character: UserRound, inventory: Backpack,
  conversation: MessageSquare, actions: Clock3, journal: BookOpen,
  abilities: Sparkles, party: Users,
}

export default function createMythfallUi(host) {
  return {
    contract: 1,
    panels: panels(host.builtinPanels).map((panel) => ({
      ...panel, Icon: icons[panel.id.replace('mythfall.', '')],
    })),
    defaultLayout,
    atlas: { initialPaused: true },
    SessionProvider: MythfallSession,
    renderPanel(panel) {
      return panel.id === 'builtin.atlas' || panel.id.startsWith('mythfall.')
        ? <MythfallGamePanel panelId={panel.id} /> : null
    },
  }
}
