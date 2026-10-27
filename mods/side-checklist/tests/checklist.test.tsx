import { expect, test } from 'claude-code/testing'

const TOOL = 'mcp__side-checklist__checklist'
const SURFACES = ['terminal', 'desktop'] as const

test('set, check, and tick from the pane', async ($, on) => {
  let seen: readonly string[] = []
  on('prompt.submit', async (_, e) => {
    seen = e.context ?? []
    return { text: e.text }
  })
  let opened = 0
  on('ui.open', async () => {
    opened += 1
    return { value: { isPlaced: true as const } }
  })
  on('ui.close', async () => ({ value: undefined }))

  const set = await $.tool.call({
    tool: TOOL,
    action: 'set',
    title: 'Launch',
    items: [{ text: 'Share the folder', who: 'you', by: '14:45' }, { text: 'Send the DM' }],
  })
  expect(String(set.result)).toContain('1. [ ] Share the folder (you, 14:45)')

  const checked = await $.tool.call({ tool: TOOL, action: 'check', numbers: [1] })
  expect(String(checked.result)).toContain('1. [x] Share the folder')

  const bad = await $.tool.call({ tool: TOOL, action: 'check', numbers: [9] })
  expect(bad.deny).toContain('No step 9')
  expect(opened).toBe(2)

  for (const surface of SURFACES) {
    const pane = await $.ui.mount({
      plugin: 'side-checklist',
      surface,
      component: 'Pane',
      requestId: 'side-checklist',
      props: {
        title: 'Checklist',
        isFocused: true,
        bodyColumns: 40,
        placement: 'dock',
        scroll: { offset: 0, bodyRows: 20 },
        view: {},
      },
    })
    expect(await pane.find({ type: 'Text', text: /^\d\/2$/ })).toBeDefined()
    expect(await pane.find({ type: 'Text', text: '2. Send the DM' })).toBeDefined()
    await pane.press({ key: 'tick-1' })
  }
  await $.prompt.submit({ text: 'next?', wait: false, origin: { kind: 'composer' } })
  expect(seen.join('\n')).toContain('The person ticked steps')
  expect(seen.join('\n')).toContain('2. [ ] Send the DM')

  // Two presses (one per surface) on step 2 leave it unticked again.
  const now = await $.tool.call({ tool: TOOL, action: 'add', items: [{ text: 'Send the deck', who: 'Alex' }] })
  expect(String(now.result)).toContain('2. [ ] Send the DM')
  expect(String(now.result)).toContain('3. [ ] Send the deck (Alex)')
})
