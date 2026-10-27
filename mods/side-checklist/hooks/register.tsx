import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Checklist, ChecklistItem } from '../types'

const PANE = 'side-checklist'
const TOOL = 'mcp__side-checklist__checklist'
const EMPTY: Checklist = { title: 'Checklist', items: [] }
const list = atom({ plugin: 'side-checklist', key: 'list' } as const, EMPTY)

// Ticks the person made in the pane that the model has not been told about.
let isTickedByPerson = false

const GUIDE = [
  'The person keeps a checklist pane beside this session.',
  `Whenever you give them steps they must carry out themselves (a plan, a to-do list, a table of steps with who and by when), also call ${TOOL} with action "set" and the whole list, and still show the steps in your reply.`,
  'When they say a step is done, or you finish one that is on the list, call it with action "check" and that step\'s number.',
  'Use "add" for a new step and "remove" for one that no longer applies. Keep each item under 70 characters; put the owner in "who" and the deadline in "by".',
  'Do not put your own tool steps on it. Leave the list alone when the person asks an unrelated question.',
].join(' ')

function describe(c: Checklist): string
{
  if (c.items.length === 0) {
    return 'The checklist is empty.'
  }
  const rows = c.items.map((item, i) => {
    const meta = [item.who, item.by].filter(Boolean).join(', ')
    return `${i + 1}. [${item.isDone ? 'x' : ' '}] ${item.text}${meta ? ` (${meta})` : ''}`
  })
  return `${c.title}\n${rows.join('\n')}`
}

function toItems(raw: unknown): ChecklistItem[]
{
  if (!Array.isArray(raw)) {
    return []
  }
  return raw.flatMap(one => {
    if (typeof one === 'string') {
      return [{ text: one, isDone: false }]
    }
    if (one && typeof one === 'object' && typeof (one as { text?: unknown }).text === 'string') {
      const o = one as { text: string; done?: unknown; who?: unknown; by?: unknown }
      return [{
        text: o.text,
        isDone: o.done === true,
        ...(typeof o.who === 'string' && o.who ? { who: o.who } : {}),
        ...(typeof o.by === 'string' && o.by ? { by: o.by } : {}),
      }]
    }
    return []
  })
}

// Applies one tool call to the list; answers the error text, or null.
function apply(c: Checklist, input: Record<string, unknown>): { next: Checklist; error: string | null }
{
  const action = input.action
  const numbers = Array.isArray(input.numbers) ? input.numbers : typeof input.number === 'number' ? [input.number] : []
  const bad = numbers.find(n => typeof n !== 'number' || n < 1 || n > c.items.length)
  if (action === 'set') {
    const title = typeof input.title === 'string' && input.title ? input.title : c.title
    return { next: { title, items: toItems(input.items) }, error: null }
  }
  if (action === 'add') {
    return { next: { ...c, items: [...c.items, ...toItems(input.items)] }, error: null }
  }
  if (action === 'clear') {
    return { next: EMPTY, error: null }
  }
  if (action === 'check' || action === 'uncheck' || action === 'remove') {
    if (numbers.length === 0 || bad !== undefined) {
      return { next: c, error: `No step ${bad ?? '(none given)'}; the list has ${c.items.length}.` }
    }
    const picked = new Set(numbers as number[])
    if (action === 'remove') {
      return { next: { ...c, items: c.items.filter((_, i) => !picked.has(i + 1)) }, error: null }
    }
    const items = c.items.map((item, i) => (picked.has(i + 1) ? { ...item, isDone: action === 'check' } : item))
    return { next: { ...c, items }, error: null }
  }
  return { next: c, error: `Unknown action ${String(action)}.` }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.tool.register({
      name: 'checklist',
      description: 'Keep the checklist pane beside the session up to date: set the whole list, add steps, check or uncheck steps by number, remove steps, or clear it. Answers the list as it now stands.',
      inputSchema: {
        type: 'object',
        properties: {
          action: { type: 'string', enum: ['set', 'add', 'check', 'uncheck', 'remove', 'clear'] },
          title: { type: 'string', description: 'Short heading, for "set".' },
          items: {
            type: 'array',
            description: 'For "set" and "add".',
            items: {
              type: 'object',
              properties: {
                text: { type: 'string' },
                done: { type: 'boolean' },
                who: { type: 'string' },
                by: { type: 'string' },
              },
              required: ['text'],
            },
          },
          numbers: { type: 'array', items: { type: 'integer' }, description: 'Step numbers, from 1, for "check", "uncheck" and "remove".' },
        },
        required: ['action'],
      },
    })
    await $.command.register({
      name: 'checklist',
      description: 'Show the checklist pane (or: /checklist clear)',
      argumentHint: '[clear]',
    })
    return next(e)
  })

  on('command.run', { command: 'checklist' }, async ($, e) => {
    if (e.args.trim() === 'clear') {
      await update($, list, () => EMPTY)
      await $.ui.close({ id: PANE }).catch(() => undefined)
      return { text: 'Checklist cleared.' }
    }
    await $.ui.open({ id: PANE, title: 'Checklist' })
    return { text: 'Checklist pane opened.' }
  })

  on('tool.call', { tool: TOOL }, async ($, e) => {
    // An MCP tool's arguments sit on the event itself, beside tool and tool_use_id.
    const input = e as unknown as Record<string, unknown>
    let error: string | null = null
    const after = await update($, list, c => {
      const done = apply(c ?? EMPTY, input)
      error = done.error
      return done.next
    })
    if (error) {
      return { deny: error }
    }
    isTickedByPerson = false
    if (input.action === 'clear') {
      void $.ui.close({ id: PANE }).catch(() => undefined)
    } else {
      void $.ui.open({ id: PANE, title: 'Checklist' }).catch(() => undefined)
    }
    return { result: describe(after ?? EMPTY) }
  })

  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e)
    return { sections: [...composed.sections, { id: 'side-checklist:guide', text: GUIDE, scope: 'session' }] }
  })

  on('prompt.submit', async ($, e, next) => {
    if (!isTickedByPerson) {
      return next(e)
    }
    isTickedByPerson = false
    const now = await read($, list)
    const note = `The person ticked steps in the checklist pane. It now reads:\n${describe(now)}`
    return next({ ...e, context: [...(e.context ?? []), note] })
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const c = await read($, list)
    const total = c.items.length
    const doneCount = c.items.filter(item => item.isDone).length
    const nextIndex = c.items.findIndex(item => !item.isDone)
    const barWidth = 12
    const filled = total === 0 ? 0 : Math.round((doneCount / total) * barWidth)
    const toggle = (index: number) => {
      isTickedByPerson = true
      return update($, list, cur => ({
        ...cur,
        items: cur.items.map((item, i) => (i === index ? { ...item, isDone: !item.isDone } : item)),
      }))
    }

    return (
      <Box flexDirection="column" gap={1}>
        <Box flexDirection="row" gap={1}>
          <Text bold color="claude">{c.title}</Text>
          {total > 0 && <Text color="success">{'━'.repeat(filled)}</Text>}
          {total > 0 && <Text color="inactive">{'─'.repeat(barWidth - filled)}</Text>}
          {total > 0 && <Text bold>{`${doneCount}/${total}`}</Text>}
        </Box>
        {total === 0 && <Text>Nothing yet. Steps Claude gives you land here.</Text>}
        <Box flexDirection="column">
          {c.items.map((item, i) => {
            const isNext = i === nextIndex
            // "you" is the default owner, so it is left out to cut noise.
            const meta = [item.who && item.who.toLowerCase() !== 'you' ? item.who : '', item.by ?? '']
              .filter(Boolean)
              .join(' · ')
            return (
              <Box key={`row-${i}`} flexDirection="row" gap={1}>
                <Text color="claude">{isNext ? '›' : ' '}</Text>
                <Button
                  key={`tick-${i}`}
                  label={item.isDone ? '✓' : ' '}
                  hotkey={i < 9 ? String(i + 1) : undefined}
                  onPress={() => toggle(i)}
                />
                <Box flexDirection="column" flexShrink={1}>
                  <Text color={item.isDone ? 'inactive' : 'text'} bold={isNext}>{`${i + 1}. ${item.text}`}</Text>
                  {meta && <Text color={item.isDone ? 'inactive' : 'suggestion'}>{meta}</Text>}
                </Box>
              </Box>
            )
          })}
        </Box>
      </Box>
    )
  })
}
