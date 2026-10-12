import type { BoxProps, ButtonProps, ElementConstructor, RenderElement, TextProps } from 'claude-code'

import type { JobRow, SessionRow, SubagentRow, Tab } from '../types'
import { MARKER, TITLE } from './keyboard'
import { lines as gridLines } from './sessions'
import { type Limits, color, foot, head, line } from './table'
import { type bodyOf, TABS, count } from './tabs'

// The pane's body as the `Pane` render hook draws it, from what the hook read: pure, the hook passes the elements of
// its surface, the table's `Client` (absent where the surface draws none) and what each button does.

type Elements = { Box: ElementConstructor<BoxProps>; Text: ElementConstructor<TextProps>; Button: ElementConstructor<ButtonProps> }

export type PaneData = {
  focused: boolean
  version: string
  current: Tab
  // What the tabs' labels count: the sessions of this machine and this session's background jobs.
  found: readonly SessionRow[]
  jobs: readonly JobRow[]
  list: readonly SubagentRow[]
  l: Limits
  // The current tab's table as a `Client`, or undefined to draw plain lines.
  table: RenderElement | undefined
  other: ReturnType<typeof bodyOf> | undefined
  // The body rows the surface gave the pane, and the plain lines' room and width.
  height: number | undefined
  room: number
  columns: number
}

export type PaneActions = {
  show: (t: Tab) => unknown
  press: (key: 'h' | 'l' | 'j' | 'k') => unknown
  pressSessions: (key: 'j' | 'k') => unknown
  stepJobs: (dir: 'prev' | 'next') => unknown
  close: () => unknown
}

export const paneView = ({ Box, Text, Button }: Elements, d: PaneData, act: PaneActions) => {
  const close = (
    <>
      <Text dimColor>·</Text>
      <Button label="close" hotkey="q" plain onPress={act.close} />
    </>
  )
  const label = (t: Tab) => `${t} ${count(t, d.list.length, d.found, d.jobs)}`
  return (
    <Box flexDirection="column" {...(d.height ? { height: d.height } : {})}>
      {/* The surface draws no pane title, so the title is the body's first line: centered, the version at the right (a
          blank of its width at the left keeps it centered). While the pane holds the keyboard the marker leads the line. */}
      <Box>
        {d.focused ? <Text bold color="yellow">{`${MARKER} `}</Text> : <Text>{' '.repeat(d.version ? d.version.length + 1 : 0)}</Text>}
        <Box flexGrow={1} justifyContent="center">
          <Text bold>{TITLE}</Text>
        </Box>
        <Text dimColor>{d.version ? `v${d.version}` : ''}</Text>
      </Box>
      <Box gap={2}>
        {TABS.map(([t, key]) => (t === d.current ? <Text key={t} bold inverse>{` ${key}: ${label(t)} `}</Text> : <Button key={t} label={label(t)} hotkey={key} plain onPress={() => act.show(t)} />))}
      </Box>
      {d.current === 'subagents' ? (
        <>
          {d.table ?? (
            <Box flexDirection="column">
              <Text bold>{head(d.l)}</Text>
              {d.list.length === 0 && <Text dimColor>No subagents yet.</Text>}
              {d.list.slice(-d.room).map(row => <Text color={color(row, d.l)}>{line(row, d.l)}</Text>)}
            </Box>
          )}
          <Text dimColor>{`${foot(d.l)} · live`}</Text>
          {/* The pane's own keys: they work while the pane holds the keyboard, without a click into the table. */}
          <Box gap={1}>
            {([['h', 'prev'], ['l', 'next'], ['j', 'down'], ['k', 'up']] as const).map(([k, label]) => <Button key={label} label={label} hotkey={k} plain onPress={() => act.press(k)} />)}
            {close}
          </Box>
        </>
      ) : d.other && (
        <>
          {d.table ?? (
            <Box flexDirection="column" flexGrow={1}>
              {gridLines(d.other.grid, d.other.empty, d.columns, (d.height ?? 24) - 10).map((t, i) => <Text key={String(i)} dimColor={!/^│/.test(t)}>{t}</Text>)}
            </Box>
          )}
          <Text dimColor>{d.other.foot}</Text>
          <Box gap={1}>
            {d.current === 'jobs' && <Button label="prev type" hotkey="h" plain onPress={() => act.stepJobs('prev')} />}
            {d.current === 'jobs' && <Button label="next type" hotkey="l" plain onPress={() => act.stepJobs('next')} />}
            <Button label="down" hotkey="j" plain onPress={() => act.pressSessions('j')} />
            <Button label="up" hotkey="k" plain onPress={() => act.pressSessions('k')} />
            {close}
          </Box>
        </>
      )}
    </Box>
  )
}
