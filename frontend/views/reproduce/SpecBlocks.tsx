import { useMemo, useState } from 'react'
import { Lock, Unlock } from 'lucide-react'
import { SECTION_LABEL, PROVENANCE_LABEL } from '../../lib/shotspec/schema'
import type { ShotSpec, SpecSection } from '../../types/shotspec'

/**
 * The ShotSpec as lockable blocks (the CozyClay concept of composable prompt
 * blocks with provenance — written fresh). Editing a block locks it; a
 * locked block survives re-analysis.
 */

const EDITABLE: SpecSection[] = ['subjects', 'scene', 'camera', 'lighting', 'style', 'narrative', 'motion']

type FieldSpec = { key: string; label: string; kind: 'text' | 'number' | 'bool' | 'list' }
const FIELDS: Partial<Record<SpecSection, FieldSpec[]>> = {
  scene: [
    { key: 'location', label: 'Location', kind: 'text' }, { key: 'environment', label: 'Environment', kind: 'text' },
    { key: 'time_of_day', label: 'Time of day', kind: 'text' }, { key: 'weather', label: 'Weather', kind: 'text' },
    { key: 'fg', label: 'Foreground', kind: 'text' }, { key: 'mg', label: 'Midground', kind: 'text' }, { key: 'bg', label: 'Background', kind: 'text' },
  ],
  camera: [
    { key: 'shot_size', label: 'Shot size', kind: 'text' }, { key: 'angle', label: 'Angle', kind: 'text' }, { key: 'height', label: 'Height', kind: 'text' },
    { key: 'focal_mm', label: 'Focal (mm)', kind: 'number' }, { key: 'lens_estimate', label: 'Lens', kind: 'text' }, { key: 'aperture', label: 'Aperture', kind: 'text' },
    { key: 'dof', label: 'Depth of field', kind: 'text' }, { key: 'focus', label: 'Focus', kind: 'text' }, { key: 'move', label: 'Move', kind: 'text' },
    { key: 'move_intensity', label: 'Move intensity', kind: 'number' }, { key: 'handheld', label: 'Handheld', kind: 'bool' },
  ],
  lighting: [
    { key: 'key_direction', label: 'Key direction', kind: 'text' }, { key: 'quality', label: 'Quality', kind: 'text' },
    { key: 'color_temp', label: 'Colour temperature', kind: 'text' }, { key: 'mood', label: 'Mood', kind: 'text' },
  ],
  style: [
    { key: 'medium', label: 'Medium', kind: 'text' }, { key: 'artists', label: 'Artists', kind: 'list' }, { key: 'negatives', label: 'Negatives', kind: 'list' },
  ],
  narrative: [
    { key: 'what_happens', label: 'What happens', kind: 'text' }, { key: 'purpose', label: 'Purpose', kind: 'text' }, { key: 'beat', label: 'Beat', kind: 'text' },
  ],
  motion: [{ key: 'pacing', label: 'Pacing', kind: 'text' }, { key: 'magnitude', label: 'Magnitude', kind: 'number' }, { key: 'subject_motion', label: 'Subject motion', kind: 'number' }],
}

interface Props {
  spec: ShotSpec
  disabled?: boolean
  onCommit: (section: SpecSection, value: unknown, lock: boolean) => void
  onToggleLock: (section: SpecSection, locked: boolean) => void
}

export function SpecBlocks({ spec, disabled, onCommit, onToggleLock }: Props) {
  const [open, setOpen] = useState<SpecSection | null>('camera')
  return (
    <div className="space-y-1.5" data-testid="spec-blocks">
      {EDITABLE.map(section => (
        <Block
          key={section}
          section={section}
          spec={spec}
          expanded={open === section}
          onExpand={() => setOpen(open === section ? null : section)}
          disabled={disabled}
          onCommit={onCommit}
          onToggleLock={onToggleLock}
        />
      ))}
    </div>
  )
}

function Block({ section, spec, expanded, onExpand, disabled, onCommit, onToggleLock }: Props & { section: SpecSection; expanded: boolean; onExpand: () => void }) {
  const locked = Boolean(spec.locks[section])
  const provenance = spec.provenance[section] ?? ''
  const confidence = spec.confidence[section] ?? 0
  const summary = useMemo(() => summarise(spec, section), [spec, section])
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null)
  const value = draft ?? (spec[section] as unknown as Record<string, unknown>)
  const fields = FIELDS[section]
  const commit = () => {
    if (draft) onCommit(section, draft, true)
    setDraft(null)
  }
  return (
    <div className={`rounded-lg border ${locked ? 'border-violet-700/70' : 'border-zinc-800'} bg-zinc-900/50`} data-testid={`spec-block-${section}`}>
      <div className="flex items-center gap-2 px-3 py-2">
        <button onClick={onExpand} className="flex-1 text-left" aria-expanded={expanded} aria-controls={`spec-${section}`}>
          <span className="text-xs font-semibold text-zinc-200">{SECTION_LABEL[section]}</span>
          <span className="ml-2 text-[10px] text-zinc-500">{PROVENANCE_LABEL[provenance] ?? provenance}{confidence ? ` · ${Math.round(confidence * 100)}%` : ''}</span>
          {!expanded && summary && <span className="block text-[11px] text-zinc-400 truncate">{summary}</span>}
        </button>
        <button
          onClick={() => onToggleLock(section, !locked)}
          disabled={disabled}
          aria-label={`${locked ? 'Unlock' : 'Lock'} ${SECTION_LABEL[section]}`}
          aria-pressed={locked}
          className={`p-1 rounded ${locked ? 'text-violet-300' : 'text-zinc-600 hover:text-zinc-300'}`}
        >
          {locked ? <Lock className="h-3.5 w-3.5" /> : <Unlock className="h-3.5 w-3.5" />}
        </button>
      </div>
      {expanded && (
        <div id={`spec-${section}`} className="px-3 pb-3 space-y-1.5">
          {section === 'subjects' ? (
            <SubjectsEditor spec={spec} disabled={disabled} onCommit={list => onCommit('subjects', list, true)} />
          ) : fields ? (
            <>
              <div className="grid grid-cols-2 gap-1.5">
                {fields.map(field => (
                  <label key={field.key} className="text-[10px] text-zinc-500">
                    {field.label}
                    {field.kind === 'bool' ? (
                      <input type="checkbox" checked={Boolean(value[field.key])} disabled={disabled} onChange={e => setDraft({ ...value, [field.key]: e.target.checked })} className="ml-2 accent-violet-500" aria-label={field.label} />
                    ) : (
                      <input
                        value={field.kind === 'list' ? (Array.isArray(value[field.key]) ? (value[field.key] as string[]).join(', ') : '') : String(value[field.key] ?? '')}
                        disabled={disabled}
                        aria-label={`${SECTION_LABEL[section]} ${field.label}`}
                        onChange={e => setDraft({ ...value, [field.key]: field.kind === 'list' ? e.target.value.split(',').map(s => s.trim()).filter(Boolean) : field.kind === 'number' ? (e.target.value === '' ? null : Number(e.target.value)) : e.target.value })}
                        className="select-chip w-full mt-0.5"
                      />
                    )}
                  </label>
                ))}
              </div>
              {section === 'style' && spec.style.tags.length > 0 && (
                <p className="text-[10px] text-zinc-500">Tags (CLIP, by score): {spec.style.tags.slice(0, 10).map(t => `${t.term} ${t.score.toFixed(2)}`).join(' · ')}</p>
              )}
              {draft && (
                <div className="flex gap-1.5">
                  <button onClick={commit} className="btn-chip">Apply &amp; lock</button>
                  <button onClick={() => setDraft(null)} className="btn-chip">Discard</button>
                </div>
              )}
            </>
          ) : null}
        </div>
      )}
    </div>
  )
}

function SubjectsEditor({ spec, disabled, onCommit }: { spec: ShotSpec; disabled?: boolean; onCommit: (list: ShotSpec['subjects']) => void }) {
  const [text, setText] = useState(() => spec.subjects.map(s => (s.count > 1 ? `${s.count} ${s.label}` : s.label)).join(', '))
  const parse = () =>
    text.split(',').map(part => part.trim()).filter(Boolean).map(part => {
      const match = /^(\d+)\s+(.+)$/.exec(part)
      return { label: match ? match[2] : part, count: match ? Number(match[1]) : 1, bbox: [], depth_median: null, attributes: [] }
    })
  return (
    <div className="space-y-1.5">
      <input value={text} onChange={e => setText(e.target.value)} disabled={disabled} aria-label="Subjects" className="select-chip w-full" placeholder="2 person, dog" />
      <ul className="text-[10px] text-zinc-500 space-y-0.5">
        {spec.subjects.map((s, i) => (
          <li key={i}>{s.count > 1 ? `${s.count}× ` : ''}{s.label}{s.bbox.length === 4 ? ` · box ${s.bbox.map(v => v.toFixed(2)).join(', ')}` : ''}{s.depth_median !== null ? ` · depth ${s.depth_median.toFixed(2)}` : ''}</li>
        ))}
      </ul>
      <button onClick={() => onCommit(parse())} disabled={disabled} className="btn-chip">Apply &amp; lock</button>
    </div>
  )
}

function summarise(spec: ShotSpec, section: SpecSection): string {
  switch (section) {
    case 'subjects':
      return spec.subjects.map(s => (s.count > 1 ? `${s.count} ${s.label}` : s.label)).join(', ')
    case 'scene':
      return [spec.scene.location, spec.scene.environment, spec.scene.time_of_day].filter(Boolean).join(' · ')
    case 'camera':
      return [spec.camera.shot_size, spec.camera.angle, spec.camera.height, spec.camera.move].filter(Boolean).join(' · ')
    case 'lighting':
      return [spec.lighting.quality, spec.lighting.key_direction, spec.lighting.color_temp, spec.lighting.mood].filter(Boolean).join(' · ')
    case 'style':
      return [spec.style.medium, ...spec.style.tags.slice(0, 4).map(t => t.term)].filter(Boolean).join(' · ')
    case 'narrative':
      return spec.narrative.what_happens
    case 'motion':
      return spec.motion.magnitude ? `magnitude ${spec.motion.magnitude.toFixed(2)} · ${spec.motion.pacing}` : ''
    default:
      return ''
  }
}
