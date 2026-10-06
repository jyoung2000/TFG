/**
 * The script as beats, each matched to the storyboard shot it became, so the
 * Script tab can show the picture of the scene next to every line (asked
 * 2026-10-01). Works for storyboards from the script parser, the AI Director
 * or built by hand: beats and shots both run in story order, and a beat is
 * matched by the words it shares with a shot near where the last one landed.
 */

export interface ScriptBeat {
  kind: 'heading' | 'action' | 'dialogue'
  text: string
  /** The shot this beat became, if one matches. */
  shotId: string | null
}

export interface BeatShot {
  id: string
  title: string
  description: string
  action: string
  dialogue: string
}

const HEADING = /^(INT\.|EXT\.|INT\/EXT|I\/E\.)/i
const STOP = new Set(['the', 'and', 'with', 'that', 'this', 'from', 'into', 'onto', 'their', 'there', 'they', 'them', 'his', 'her', 'she', 'him', 'for', 'are', 'was', 'were', 'has', 'have', 'its', 'but', 'not', 'you', 'all', 'out', 'off', 'over', 'under', 'then'])

function words(text: string): Set<string> {
  return new Set(text.toLowerCase().match(/[a-z0-9']+/g)?.filter(w => w.length > 2 && !STOP.has(w)) ?? [])
}

function overlap(a: Set<string>, b: Set<string>): number {
  if (!a.size || !b.size) return 0
  let shared = 0
  for (const w of a) if (b.has(w)) shared++
  return shared / Math.min(a.size, b.size)
}

/** Split a screenplay into headings, action paragraphs and dialogue blocks. */
export function splitBeats(script: string): Omit<ScriptBeat, 'shotId'>[] {
  const beats: Omit<ScriptBeat, 'shotId'>[] = []
  const blocks = script.replace(/\r\n/g, '\n').split(/\n\s*\n/).map(b => b.trim()).filter(Boolean)
  for (const block of blocks) {
    const lines = block.split('\n').map(l => l.trim()).filter(Boolean)
    if (lines.length && HEADING.test(lines[0])) {
      beats.push({ kind: 'heading', text: lines[0] })
      if (lines.length > 1) beats.push({ kind: 'action', text: lines.slice(1).join(' ') })
      continue
    }
    const speaker = lines[0]
    const isDialogue = lines.length > 1 && speaker === speaker.toUpperCase() && /[A-Z]/.test(speaker) && speaker.length <= 40
    beats.push({ kind: isDialogue ? 'dialogue' : 'action', text: isDialogue ? `${speaker}: ${lines.slice(1).join(' ')}` : lines.join(' ') })
  }
  return beats
}

/** Beats with the shot each became (null for headings and unmatched lines). */
export function matchBeats(script: string, shots: BeatShot[]): ScriptBeat[] {
  const shotWords = shots.map(s => words([s.title, s.description, s.action, s.dialogue].join(' ')))
  let cursor = 0
  return splitBeats(script).map(beat => {
    if (beat.kind === 'heading' || !shots.length) return { ...beat, shotId: null }
    const beatWords = words(beat.text)
    let best = -1
    let bestScore = 0.2
    // Story order: look a little behind (several beats can make one shot) and ahead.
    for (let i = Math.max(0, cursor - 1); i < Math.min(shots.length, cursor + 4); i++) {
      const score = overlap(beatWords, shotWords[i]) - (i < cursor ? 0.05 : 0)
      if (score > bestScore) {
        best = i
        bestScore = score
      }
    }
    if (best < 0) return { ...beat, shotId: null }
    cursor = Math.max(cursor, best)
    return { ...beat, shotId: shots[best].id }
  })
}
