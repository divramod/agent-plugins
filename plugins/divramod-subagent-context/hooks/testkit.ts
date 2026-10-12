import type { AgentStatus, On } from 'claude-code'
import { type Engine, mock } from 'claude-code/testing'

// What the table tests share: the pane, three subagents with one step each, the Client mounted at 100 by 10.

export const PANE = { plugin: 'divramod-subagent-context', surface: 'terminal', component: 'Pane', props: { title: 'Subagents: context', isFocused: true, bodyColumns: 100, placement: 'dock', scroll: { offset: 0, bodyRows: 10 }, view: {} }, requestId: 'subagent-context', viewport: { columns: 100, rows: 12 } } as const

const usage = (tokens: number) => ({ input_tokens: 0, output_tokens: 1, cache_read_input_tokens: tokens, cache_creation_input_tokens: 0, model: 'claude-opus-5-5' })

// The Client's lines: the tabs (y 0), the top rule, the header (y 2), a rule, then each row with a rule between, the
// sum row and the bottom rule. At 120 columns the widths start at 3 34 9 10 9 7 8 9 7 8 with a `│` before and after
// each: Peak is column 6 at x 79-86, the border right of Subagent at x 45.
export const HEAD = 2
export const PEAK = 82
export const BORDER = 39

// Three subagents, one step each, in this order: alpha at 300k, beta at 100k, gamma at 200k (the stub answers a
// step with as many cached tokens as its `messageCount`); `status` is what `$.agent.list()` answers for each.
export const steps = async ($: Engine, on: On) => {
  const status: Record<string, AgentStatus> = { alpha: 'running', beta: 'running', gamma: 'running' }
  mock.clock(on)
  on('ui.status', () => ({ value: undefined }))
  on('classic.SubagentStart', () => ({}))
  on('classic.SubagentStop', () => ({}))
  on('agent.list', () => ({ value: Object.entries(status).map(([id, s]) => ({ id, description: id, type: 'general-purpose', status: s })) }))
  on('turn.step', async function* (_$, e) {
    const u = usage(e.messageCount)
    yield { kind: 'stop', stopReason: 'end_turn', usage: u }
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: 'end_turn', usage: u }
  })
  for (const [agentId, tokens] of [['alpha', 300_000], ['beta', 100_000], ['gamma', 200_000]] as const) {
    const s = $.turn.step({ turnId: 't', index: 0, model: 'opus', effort: 'high', messageCount: tokens, agentId })
    while (!(await s.next()).done);
  }
  return status
}

export const mounted = async ($: Engine, on: On, surface: 'terminal' | 'desktop' = 'terminal') => {
  const status = await steps($, on)
  const ui = await $.ui.mount({ ...PANE, surface })
  await ui.resize({ columns: 120, rows: 24, in: 'table' })
  const all = async () => (await ui.findAll({ type: 'Text', in: 'table' })).map(t => t.text)
  // The table's lines: the header, the rows, the sum row (the rules and the tabs are left out).
  const lines = async () => (await all()).filter(t => t.startsWith('│'))
  const header = async () => (await lines())[0]!
  const sum = async () => (await lines()).at(-1)!
  const texts = async () => (await lines()).slice(1, -1)
  // Each shown row's name: its second cell.
  const names = async () => (await texts()).map(t => t.split('│')[2]!.trim())
  const click = async (x: number, y = HEAD) => {
    await ui.pointer({ type: 'down', x, y, button: 'left' })
    await ui.pointer({ type: 'up', x, y, button: 'left' })
  }
  const drag = async (from: number, to: number) => {
    await ui.pointer({ type: 'down', x: from, y: HEAD, button: 'left' })
    await ui.pointer({ type: 'move', x: to, y: HEAD, button: 'left' })
    await ui.pointer({ type: 'up', x: to, y: HEAD, button: 'left' })
  }
  return { ui, status, all, texts, header, sum, names, click, drag }
}
