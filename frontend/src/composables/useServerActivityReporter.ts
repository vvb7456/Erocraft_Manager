import type { Ref } from 'vue'

type ServerActivityEvent = 'server:console.command' | 'server:file.uploaded'

export function useServerActivityReporter(serverId: Ref<number | undefined>) {
  async function reportServerActivity(event: ServerActivityEvent, properties: Record<string, unknown>) {
    if (!serverId.value) return
    try {
      await fetch(`/api/user/servers/${serverId.value}/activity`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event, properties }),
      })
    } catch {
      // Activity reporting must not affect the user operation that already succeeded.
    }
  }

  return { reportServerActivity }
}
