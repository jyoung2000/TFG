import { describe, expect, it } from 'vitest'
import { matchBeats, splitBeats, type BeatShot } from './scriptBeats'

/* Asked 2026-10-01: the storyboard should have an image of the scene it is
 * describing next to each line or bit. Each script beat is matched to the
 * shot it became, so its picture can sit next to it. */

const SCRIPT = `INT. COFFEE SHOP - DAY

Sunlight cuts across empty tables. SARAH sits alone, staring at an unopened letter.

SARAH
I can't keep pretending this never happened.

She tears the envelope open.

EXT. CITY STREET - NIGHT

JOHN walks fast through the rain, phone pressed to his ear.`

// What the script parser makes of it (descriptions follow the text).
const SHOTS: BeatShot[] = [
  { id: 's1', title: 'Shot 1', description: 'Sunlight cuts across empty tables. Sarah sits alone, staring at an unopened letter.', action: '', dialogue: '' },
  { id: 's2', title: 'Shot 2', description: 'Sarah speaks', action: '', dialogue: "I can't keep pretending this never happened." },
  { id: 's3', title: 'Shot 3', description: 'She tears the envelope open.', action: '', dialogue: '' },
  { id: 's4', title: 'Shot 4', description: 'John walks fast through the rain, phone pressed to his ear.', action: '', dialogue: '' },
]

describe('splitBeats', () => {
  it('splits headings, action and dialogue', () => {
    expect(splitBeats(SCRIPT).map(b => b.kind)).toEqual(['heading', 'action', 'dialogue', 'action', 'heading', 'action'])
    expect(splitBeats(SCRIPT)[2].text).toBe("SARAH: I can't keep pretending this never happened.")
  })
})

describe('matchBeats', () => {
  it('puts every line next to the shot it became', () => {
    expect(matchBeats(SCRIPT, SHOTS).map(b => b.shotId)).toEqual([null, 's1', 's2', 's3', null, 's4'])
  })

  it('follows an AI Director storyboard that reworded the beats', () => {
    const reworded: BeatShot[] = [
      { id: 'a', title: 'Alone with the letter', description: 'Close on Sarah at an empty table, an unopened letter in front of her', action: 'staring', dialogue: '' },
      { id: 'b', title: 'Confession', description: 'Sarah, voice breaking', action: '', dialogue: 'pretending this never happened' },
      { id: 'c', title: 'Opening', description: 'Her hands tear the envelope', action: '', dialogue: '' },
      { id: 'd', title: 'Rain', description: 'John hurries along a wet street in the rain on the phone', action: '', dialogue: '' },
    ]
    expect(matchBeats(SCRIPT, reworded).map(b => b.shotId)).toEqual([null, 'a', 'b', 'c', null, 'd'])
  })

  it('leaves a line with no matching shot without a picture', () => {
    expect(matchBeats(SCRIPT, [SHOTS[3]]).map(b => b.shotId)).toEqual([null, null, null, null, null, 's4'])
  })
})
