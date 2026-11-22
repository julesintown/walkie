/** Eine Einstellung, wie `walkie list --json` sie liefert. */
export type Setting = {
  key: string
  type: string
  value: unknown
  default: unknown
  group: string
  title: string
  help: string
  choices: string[]
  restart: boolean
  min: number | null
  max: number | null
}

declare module 'claude-code' {
  interface PluginState {
    'walkie': { view: string; note: string; settings: Shaped<Setting[]> }
  }
}
