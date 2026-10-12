// Renders docs/screenshot.svg: the pane's table for fixture rows, through the mod's own cells, colors and widths.
// Run with bun from anywhere: `bun plugins/divramod-subagent-context/scripts/screenshot.ts`. No dependencies.
import { writeFileSync } from 'node:fs'

import type { SubagentRow } from '../types'
import { header, line, rule } from '../hooks/grid'
import { ALIGNS, WIDTHS, cells, color, foot, heads, limits, sums } from '../hooks/table'

const l = limits({ window: '1m', warn_percent: 30, alert_percent: 35 }, 1_000_000)

const row = (r: Partial<SubagentRow> & Pick<SubagentRow, 'id' | 'description' | 'peak'>): SubagentRow => ({
  model: 'opus', effort: 'high', calls: 12, now: r.peak, compactions: 0, seconds: 240, started: 0, mtime: 0, status: 'completed', ...r,
})

const fixture = [
  row({ id: 'a1', description: 'Plan 0149 row 163 part 2: e2e', model: 'sonnet', effort: 'medium', calls: 31, peak: 142_000, now: 118_000, seconds: 540 }),
  row({ id: 'a2', description: 'Plan 0149 row 232: Automations plugin', calls: 54, peak: 336_000, now: 336_000, seconds: 1020, status: 'running' }),
  row({ id: 'a3', description: 'Plan 0149 row 212: Servers plugin', model: 'sonnet', effort: 'medium', calls: 22, peak: 288_000, now: 288_000, seconds: 660, status: 'running' }),
  row({ id: 'a4', description: 'Explore the code map', model: 'haiku', effort: 'low', calls: 8, peak: 41_000, now: 41_000, seconds: 125 }),
  row({ id: 'a5', description: 'Plan 0149 row 178: Repositories plugin', calls: 66, peak: 410_000, now: 120_000, compactions: 1, seconds: 1440, status: 'failed' }),
]

const COLORS: Record<string, string> = { red: '#f7768e', yellow: '#e0af68', cyan: '#7dcfff' }
const TEXT = '#c0caf5'
const DIM = '#565f89'
const CW = 9
const LH = 22
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;')

// The same lines the pane draws: the tabs, the rules, the header, a rule between rows, the sum row.
const lines: { text: string; fill: string; bold?: boolean }[] = [
  { text: ' All 5   Running 2   Finished 3 ', fill: DIM },
  { text: rule(WIDTHS, 'top'), fill: DIM },
  { text: header(heads(l), WIDTHS, ALIGNS, undefined), fill: TEXT, bold: true },
  ...fixture.flatMap((r, i) => [
    { text: rule(WIDTHS, 'mid'), fill: DIM },
    { text: line(cells(r, l), WIDTHS, ALIGNS), fill: COLORS[color(r, l) ?? ''] ?? TEXT },
  ]),
  { text: rule(WIDTHS, 'mid'), fill: DIM },
  { text: line(sums(fixture, l), WIDTHS, ALIGNS), fill: TEXT, bold: true },
  { text: rule(WIDTHS, 'bottom'), fill: DIM },
  { text: `${foot(l)} · live`, fill: DIM },
]

const cols = Math.max(...lines.map(x => [...x.text].length)) + 2
const width = cols * CW + 24
const height = lines.length * LH + 48
const body = lines
  .map((x, i) => `<text x="12" y="${36 + i * LH}" fill="${x.fill}"${x.bold ? ' font-weight="bold"' : ''} xml:space="preserve">${esc(x.text)}</text>`)
  .join('\n  ')

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" font-family="Menlo, Consolas, 'DejaVu Sans Mono', monospace" font-size="15">
  <title>Subagents: context</title>
  <rect width="100%" height="100%" rx="8" fill="#1a1b26"/>
  ${body}
</svg>
`

writeFileSync(new URL('../docs/screenshot.svg', import.meta.url), svg)
