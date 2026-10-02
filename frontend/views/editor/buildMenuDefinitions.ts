import { audioPartner, clipTargets, deleteClips } from './timelineOps'
import { APP_NAME } from "../../lib/brand";
import { type MenuDefinition } from '../../components/MenuBar'
import type { TimelineClip } from '../../types/project'
import { TEXT_PRESETS } from '../../types/project'
import { getShortcutLabel, type ToolType } from './video-editor-utils'
import type { KeyboardLayout } from '../../lib/keyboard-shortcuts'

export interface MenuDepsParams {
  selectedClip: TimelineClip | null | undefined
  selectedClipIds: Set<string>
  clips: TimelineClip[]
  tracks: any[]
  subtitles: any[]
  snapEnabled: boolean
  showEffectsBrowser: boolean
  showSourceMonitor: boolean
  showPropertiesPanel: boolean
  showICLoraPanel: boolean
  sourceAsset: any
  activeTool: ToolType
  activeTimeline: any
  timelines: any[]
  kbLayout: KeyboardLayout
  fileInputRef: React.RefObject<HTMLInputElement>
  subtitleFileInputRef: React.RefObject<HTMLInputElement>
  setShowImportTimelineModal: (v: boolean) => void
  setShowExportModal: (v: boolean) => void
  handleExportTimelineXml: () => void
  handleExportSrt: () => void
  undoRef: React.RefObject<() => void>
  redoRef: React.RefObject<() => void>
  cutRef: React.RefObject<() => void>
  copyRef: React.RefObject<() => void>
  pasteRef: React.RefObject<() => void>
  setSelectedClipIds: (v: Set<string>) => void
  handleInsertEdit: () => void
  handleOverwriteEdit: () => void
  matchFrameRef: React.RefObject<() => void>
  setKbEditorOpen: (v: boolean) => void
  splitClipAtPlayhead: (id: string, atTime?: number, batchClipIds?: string[]) => void
  duplicateClip: (id: string) => void
  pushUndo: () => void
  setClips: React.Dispatch<React.SetStateAction<TimelineClip[]>>
  updateClip: (id: string, patch: Partial<TimelineClip>) => void
  setTracks: React.Dispatch<React.SetStateAction<any[]>>
  addTrack: (kind?: 'video' | 'audio') => void
  pushTrackUndo: () => void
  minZoom: number
  addTextClip: (style?: any) => void
  addSubtitleTrack: () => void
  createAdjustmentLayerAsset: () => void
  setSnapEnabled: (v: boolean) => void
  fitToViewRef: React.RefObject<() => void>
  setZoom: React.Dispatch<React.SetStateAction<number>>
  setShowSourceMonitor: (v: boolean) => void
  setShowEffectsBrowser: (v: boolean) => void
  setShowPropertiesPanel: (v: boolean) => void
  setShowICLoraPanel: (v: boolean) => void
  setIcLoraSourceClipId: (v: string | null) => void
  setActiveTool: (v: ToolType) => void
  setLastTrimTool: (v: ToolType) => void
  handleAddTimeline: () => void
  handleDuplicateTimeline: (id: string) => void
  handleResetLayout: () => void
}

export function buildMenuDefinitions(p: MenuDepsParams): MenuDefinition[] {
  // Clip commands act on every selected clip (QA 2026-10-01: they acted on one).
  const targets = clipTargets(p.selectedClip, p.selectedClipIds, p.clips)
  const none = targets.length === 0
  const allMuted = !none && targets.every(c => c.muted)
  const apply = (patch: (clip: TimelineClip) => Partial<TimelineClip>) => {
    const ids = new Set(targets.map(c => c.id))
    p.pushUndo()
    p.setClips(prev => prev.map(c => (ids.has(c.id) ? { ...c, ...patch(c) } : c)))
  }
  const partner = p.selectedClip ? audioPartner(p.selectedClip, p.clips, p.tracks) : null
  return [
    // ── File ──
    // Import/export, timeline management, project settings
    {
      id: 'file',
      label: 'File',
      items: [
        { id: 'new-timeline', label: 'New Timeline', action: () => p.handleAddTimeline() },
        { id: 'duplicate-timeline', label: 'Duplicate Active Timeline', action: () => { if (p.activeTimeline) p.handleDuplicateTimeline(p.activeTimeline.id) }, disabled: !p.activeTimeline },
        { id: 'sep-0', label: '', separator: true },
        { id: 'import-media', label: 'Import Media...', shortcut: 'Ctrl+I', action: () => p.fileInputRef.current?.click() },
        { id: 'import-timeline', label: 'Import Timeline (XML)...', action: () => p.setShowImportTimelineModal(true) },
        { id: 'import-srt', label: 'Import Subtitles (SRT)...', action: () => p.subtitleFileInputRef.current?.click() },
        { id: 'sep-1', label: '', separator: true },
        { id: 'export-timeline', label: 'Export Timeline...', shortcut: 'Ctrl+E', action: () => p.setShowExportModal(true) },
        { id: 'export-xml', label: 'Export FCP7 XML...', action: () => p.handleExportTimelineXml() },
        { id: 'export-srt', label: 'Export Subtitles (SRT)...', action: () => p.handleExportSrt(), disabled: p.subtitles.length === 0 },
      ],
    },

    // ── Edit ──
    // Undo/redo, clipboard, selection, source monitor edits
    {
      id: 'edit',
      label: 'Edit',
      items: [
        { id: 'undo', label: 'Undo', shortcut: getShortcutLabel(p.kbLayout, 'edit.undo'), action: () => p.undoRef.current!() },
        { id: 'redo', label: 'Redo', shortcut: getShortcutLabel(p.kbLayout, 'edit.redo'), action: () => p.redoRef.current!() },
        { id: 'sep-1', label: '', separator: true },
        { id: 'cut', label: 'Cut', shortcut: getShortcutLabel(p.kbLayout, 'edit.cut'), action: () => p.cutRef.current!() },
        { id: 'copy', label: 'Copy', shortcut: getShortcutLabel(p.kbLayout, 'edit.copy'), action: () => p.copyRef.current!() },
        { id: 'paste', label: 'Paste', shortcut: getShortcutLabel(p.kbLayout, 'edit.paste'), action: () => p.pasteRef.current!() },
        { id: 'sep-2', label: '', separator: true },
        { id: 'select-all', label: 'Select All', shortcut: getShortcutLabel(p.kbLayout, 'edit.selectAll'), action: () => p.setSelectedClipIds(new Set(p.clips.map(c => c.id))) },
        { id: 'deselect-all', label: 'Deselect All', shortcut: getShortcutLabel(p.kbLayout, 'edit.deselect'), action: () => p.setSelectedClipIds(new Set()) },
        { id: 'sep-3', label: '', separator: true },
        { id: 'insert-edit', label: 'Insert Edit', shortcut: getShortcutLabel(p.kbLayout, 'edit.insertEdit'), action: () => p.handleInsertEdit(), disabled: !p.sourceAsset },
        { id: 'overwrite-edit', label: 'Overwrite Edit', shortcut: getShortcutLabel(p.kbLayout, 'edit.overwriteEdit'), action: () => p.handleOverwriteEdit(), disabled: !p.sourceAsset },
        { id: 'match-frame', label: 'Match Frame', shortcut: getShortcutLabel(p.kbLayout, 'edit.matchFrame'), action: () => p.matchFrameRef.current!() },
        { id: 'sep-4', label: '', separator: true },
        { id: 'keyboard-shortcuts', label: 'Keyboard Shortcuts...', action: () => p.setKbEditorOpen(true) },
      ],
    },

    // ── Clip ──
    // Operations on selected clip(s): split, duplicate, delete, transform, audio, speed
    {
      id: 'clip',
      label: 'Clip',
      items: [
        { id: 'split', label: 'Split at Playhead', action: () => { if (targets.length) p.splitClipAtPlayhead(targets[0].id, undefined, targets.map(c => c.id)) }, disabled: none },
        { id: 'duplicate', label: 'Duplicate Clip', action: () => { if (p.selectedClip) p.duplicateClip(p.selectedClip.id) }, disabled: !p.selectedClip },
        // The Delete key's rules: locked tracks keep their clips; links are cleaned up.
        { id: 'delete', label: 'Delete', shortcut: getShortcutLabel(p.kbLayout, 'edit.delete'), action: () => { const ids = new Set(targets.map(c => c.id)); p.pushUndo(); p.setClips(prev => deleteClips(prev, p.tracks, ids)); p.setSelectedClipIds(new Set()) }, disabled: none },
        { id: 'sep-1', label: '', separator: true },
        { id: 'flip-h', label: 'Flip Horizontal', action: () => apply(c => ({ flipH: !c.flipH })), disabled: none },
        { id: 'flip-v', label: 'Flip Vertical', action: () => apply(c => ({ flipV: !c.flipV })), disabled: none },
        { id: 'reverse', label: 'Reverse', action: () => apply(c => ({ reversed: !c.reversed })), disabled: none },
        { id: 'sep-2', label: '', separator: true },
        { id: 'mute', label: allMuted ? 'Unmute Clip' : 'Mute Clip', action: () => apply(() => ({ muted: !allMuted })), disabled: none },
        { id: 'link-audio', label: p.selectedClip?.linkedClipIds?.length ? 'Unlink Audio' : 'Link Audio', action: () => {
          const clip = p.selectedClip
          if (!clip) return
          p.pushUndo()
          if (clip.linkedClipIds?.length) {
            const linkedIds = clip.linkedClipIds
            p.setClips(prev => prev.map(c => {
              if (c.id === clip.id) return { ...c, linkedClipIds: undefined }
              if (linkedIds.includes(c.id)) return { ...c, linkedClipIds: c.linkedClipIds?.filter(lid => lid !== clip.id) }
              return c
            }))
          } else if (partner) {
            // Pair it with the same media at the same time on a track of the other kind.
            p.setClips(prev => prev.map(c => c.id === clip.id ? { ...c, linkedClipIds: [partner.id] } : c.id === partner.id ? { ...c, linkedClipIds: [clip.id] } : c))
          }
        }, disabled: !p.selectedClip || (!p.selectedClip.linkedClipIds?.length && !partner) },
        { id: 'sep-3', label: '', separator: true },
        ...([0.25, 0.5, 1, 1.5, 2, 4] as const).map(speed => ({
          id: `speed-${Math.round(speed * 100).toString().padStart(3, '0')}`,
          label: speed === 1 ? 'Speed: 1x (Normal)' : `Speed: ${speed}x`,
          action: () => apply(() => ({ speed })),
          disabled: none,
        })),
      ],
    },

    // ── Sequence ──
    // Timeline-level: add tracks, add layers, add text/captions, snapping
    {
      id: 'sequence',
      label: 'Sequence',
      items: [
        // The track header's own add (undoable as a track change).
        { id: 'add-video-track', label: 'Add Video Track', action: () => p.addTrack('video') },
        { id: 'add-audio-track', label: 'Add Audio Track', action: () => p.addTrack('audio') },
        { id: 'add-subtitle-track', label: 'Add Subtitle Track', action: () => { p.pushTrackUndo(); p.addSubtitleTrack() } },
        { id: 'sep-1', label: '', separator: true },
        { id: 'add-adjustment', label: 'Add Adjustment Layer', action: () => p.createAdjustmentLayerAsset() },
        { id: 'sep-2', label: '', separator: true },
        { id: 'add-text', label: 'Add Text Overlay', action: () => p.addTextClip() },
        { id: 'add-text-lower', label: 'Add Lower Third', action: () => p.addTextClip(TEXT_PRESETS.find((pr: any) => pr.id === 'lower-third-basic')?.style) },
        { id: 'add-text-subtitle', label: 'Add Caption', action: () => p.addTextClip(TEXT_PRESETS.find((pr: any) => pr.id === 'subtitle-style')?.style) },
        { id: 'sep-3', label: '', separator: true },
        { id: 'snap-toggle', label: p.snapEnabled ? 'Disable Snapping' : 'Enable Snapping', shortcut: getShortcutLabel(p.kbLayout, 'timeline.toggleSnap'), action: () => p.setSnapEnabled(!p.snapEnabled) },
      ],
    },

    // ── Tools ──
    // Timeline editing tools (selection, trim, blade, etc.)
    {
      id: 'tools',
      label: 'Tools',
      items: [
        { id: 'tool-select', label: 'Selection Tool', shortcut: getShortcutLabel(p.kbLayout, 'tool.select'), action: () => p.setActiveTool('select') },
        { id: 'tool-blade', label: 'Blade Tool', shortcut: getShortcutLabel(p.kbLayout, 'tool.blade'), action: () => p.setActiveTool('blade') },
        { id: 'sep-1', label: '', separator: true },
        { id: 'tool-ripple', label: 'Ripple Trim', shortcut: getShortcutLabel(p.kbLayout, 'tool.ripple'), action: () => { p.setActiveTool('ripple'); p.setLastTrimTool('ripple') } },
        { id: 'tool-roll', label: 'Roll Trim', shortcut: getShortcutLabel(p.kbLayout, 'tool.roll'), action: () => { p.setActiveTool('roll'); p.setLastTrimTool('roll') } },
        { id: 'tool-slip', label: 'Slip Tool', shortcut: getShortcutLabel(p.kbLayout, 'tool.slip'), action: () => { p.setActiveTool('slip'); p.setLastTrimTool('slip') } },
        { id: 'tool-slide', label: 'Slide Tool', shortcut: getShortcutLabel(p.kbLayout, 'tool.slide'), action: () => { p.setActiveTool('slide'); p.setLastTrimTool('slide') } },
        { id: 'sep-2', label: '', separator: true },
        // IC-LORA HIDDEN - IC-LoRA menu item hidden because IC-LoRA is broken on server
        // { id: 'ic-lora', label: 'IC-LoRA Style Transfer...', action: () => {
        //   p.setIcLoraSourceClipId(p.selectedClip?.type === 'video' ? p.selectedClip.id : null)
        //   p.setShowICLoraPanel(true)
        // }},
      ],
    },

    // ── View ──
    // Panel visibility, timeline zoom, layout
    {
      id: 'view',
      label: 'View',
      items: [
        { id: 'clip-viewer', label: p.showSourceMonitor ? 'Hide Clip Viewer' : 'Show Clip Viewer', action: () => p.setShowSourceMonitor(!p.showSourceMonitor) },
        // EFFECTS HIDDEN - effects-browser menu item hidden because effects are not applied during export
        // { id: 'effects-browser', label: p.showEffectsBrowser ? 'Hide Effects Browser' : 'Show Effects Browser', action: () => p.setShowEffectsBrowser(!p.showEffectsBrowser) },
        { id: 'properties-panel', label: p.showPropertiesPanel ? 'Hide Properties Panel' : 'Show Properties Panel', action: () => p.setShowPropertiesPanel(!p.showPropertiesPanel) },
        // IC-LORA HIDDEN - IC-LoRA panel toggle hidden because IC-LoRA is broken on server
        // { id: 'ic-lora-panel', label: p.showICLoraPanel ? 'Hide IC-LoRA Panel' : 'Show IC-LoRA Panel', action: () => p.setShowICLoraPanel(!p.showICLoraPanel) },
        { id: 'sep-1', label: '', separator: true },
        { id: 'fit-to-view', label: 'Zoom to Fit', shortcut: getShortcutLabel(p.kbLayout, 'timeline.fitToView'), action: () => p.fitToViewRef.current!() },
        // The same steps and limits as the keyboard and the zoom slider.
        { id: 'zoom-in', label: 'Zoom In', shortcut: getShortcutLabel(p.kbLayout, 'timeline.zoomIn'), action: () => p.setZoom(z => Math.min(4, +(z + 0.25).toFixed(2))) },
        { id: 'zoom-out', label: 'Zoom Out', shortcut: getShortcutLabel(p.kbLayout, 'timeline.zoomOut'), action: () => p.setZoom(z => Math.max(p.minZoom, +(z - 0.25).toFixed(2))) },
        { id: 'sep-2', label: '', separator: true },
        { id: 'reset-layout', label: 'Reset Layout', action: () => p.handleResetLayout() },
      ],
    },

    // ── Help ──
    {
      id: 'help',
      label: 'Help',
      items: [
        { id: 'shortcuts', label: 'Keyboard Shortcuts...', action: () => p.setKbEditorOpen(true) },
        { id: 'about', label: `About ${APP_NAME}`, action: () => window.dispatchEvent(new CustomEvent('open-settings', { detail: { tab: 'about' } })) },
      ],
    },
  ]
}
