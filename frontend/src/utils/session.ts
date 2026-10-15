import { getCurrentScope, onScopeDispose } from 'vue'

let revision = 0
const resets = new Set<() => void>()
export const sessionRevision = () => revision
export function resetSessionData() {
  revision++
  resets.forEach((reset) => reset())
}
export function onSessionReset(reset: () => void) {
  resets.add(reset)
  if (getCurrentScope()) onScopeDispose(() => resets.delete(reset))
}
