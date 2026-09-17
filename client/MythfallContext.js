import { createContext, useContext } from 'react'

export const MythfallContext = createContext(null)

export function useMythfallSession() {
  const session = useContext(MythfallContext)
  if (!session) throw new Error('Mythfall panels require a session')
  return session
}
