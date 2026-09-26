import { useEffect } from 'react'
import { useKeyboardShortcuts } from '../contexts/KeyboardShortcutsContext'
import { useProjects } from '../contexts/ProjectContext'
import { resolveAction } from '../lib/keyboard-shortcuts'

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

/**
 * App-wide shortcuts (the `app.*` actions in the keyboard layout): jump to
 * Home / Create / Reproduce / Train / History and open the shortcuts editor.
 * Editor-only actions stay with the Video Editor, which handles its own keys.
 */
export function useGlobalShortcuts(): void {
  const { activeLayout, setEditorOpen, isEditorOpen } = useKeyboardShortcuts()
  const { goHome, openQuickMode, openAnalysis, openTrain, openHistory } = useProjects()
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditorOpen || isTypingTarget(event.target)) return
      const action = resolveAction(activeLayout, event)
      if (!action || !action.startsWith('app.')) return
      event.preventDefault()
      switch (action) {
        case 'app.home': goHome(); break
        case 'app.create': openQuickMode(); break
        case 'app.reproduce': openAnalysis('image', ''); break
        case 'app.train': openTrain(); break
        case 'app.history': openHistory(); break
        case 'app.shortcuts': setEditorOpen(true); break
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [activeLayout, isEditorOpen, goHome, openQuickMode, openAnalysis, openTrain, openHistory, setEditorOpen])
}
