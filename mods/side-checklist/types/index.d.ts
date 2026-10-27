export type ChecklistItem = { text: string; isDone: boolean; who?: string; by?: string }
export type Checklist = { title: string; items: ChecklistItem[] }

declare module 'claude-code' {
  interface PluginState {
    'side-checklist': { list: Checklist }
  }
}
