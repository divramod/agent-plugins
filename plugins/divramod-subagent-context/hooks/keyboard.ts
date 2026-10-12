// The pane and the keyboard (plan 0233 D3, D6): the pane never opens or takes the keyboard by itself, says on its
// title line while it holds the keyboard, and gives it back after a while without a key. Pure: register.tsx does the IO.

export const TITLE = 'divramod subagents context'

// Drawn on the title line while the pane holds the keyboard. The prefix `[pane has the keyboard` is a contract: hal2's
// typing guard greps for it before it types into the prompt, and presses Escape to get the keyboard back.
export const MARKER = '[pane has the keyboard - Esc returns it]'

// Focused and no key seen this long, the pane hands the keyboard back. Keys the pane swallows reach no hook, so the
// module sees only presses, the table's posts and the person's focus moves: the timeout stays generous.
export const IDLE_MS = 60_000

// The focus log keeps this many lines, the newest last.
export const LOG_LINES = 200

// The body rows the pane asks for: the tabs, the header, one per subagent and the footer, between 9 and 20. A pane
// opened without `rows` is a third of the screen and showed one row of five (the user, 2026-10-09).
export const wanted = (subagents: number) => Math.min(20, Math.max(9, subagents + 4))

// One line of the focus log: when, what moved, who moved it, whether it was granted, and what it named.
export const logLine = (at: number, what: string, origin: string, granted: boolean, detail = '') =>
  [new Date(at).toISOString(), what, origin, granted ? 'granted' : 'refused', detail].filter(Boolean).join(' ')

// The log's text with `line` appended, cut to the last `cap` lines.
export const appended = (text: string, line: string, cap = LOG_LINES) =>
  `${[...text.split('\n').filter(Boolean), line].slice(-cap).join('\n')}\n`

// Whether a pane focused since `focusedAt` (0: not focused) and last keyed at `lastKey` has idled long enough.
export const idle = (now: number, focusedAt: number, lastKey: number, ms = IDLE_MS) =>
  focusedAt > 0 && now - Math.max(focusedAt, lastKey) >= ms

// An open's arguments without the request for the keyboard.
export const unfocused = <T extends { focus?: true }>(e: T): T => {
  const { focus: _, ...rest } = e
  return rest as T
}

// The version field of a plugin.json's text; empty when it cannot be read.
export const versionIn = (text: string) => {
  try {
    return String(JSON.parse(text).version ?? '')
  } catch {
    return ''
  }
}
