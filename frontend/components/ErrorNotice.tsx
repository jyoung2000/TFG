import { AlertTriangle } from 'lucide-react'
import { describeError, requestSettings } from '../lib/error-messages'

/**
 * Inline, actionable error: human title + what to do + a button that takes
 * the user to the right place (API keys, models) when one exists.
 */
export function ErrorNotice({
  error,
  onRetry,
  onOpenModels,
  compact = false,
}: {
  error: unknown
  onRetry?: () => void
  onOpenModels?: () => void
  compact?: boolean
}) {
  const friendly = describeError(error)
  const raw = error instanceof Error ? error.message : String(error)
  const action = () => {
    if (friendly.action === 'open-api-keys') requestSettings('apiKeys')
    else if (friendly.action === 'open-models') onOpenModels?.()
    else if (friendly.action === 'retry') onRetry?.()
  }
  const showAction =
    (friendly.action === 'open-api-keys') ||
    (friendly.action === 'open-models' && !!onOpenModels) ||
    (friendly.action === 'retry' && !!onRetry)
  return (
    <div
      role="alert"
      className={`rounded border border-red-900/60 bg-red-950/30 ${compact ? 'px-2 py-1.5' : 'p-3'} text-red-200`}
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className={`${compact ? 'h-3 w-3 mt-0.5' : 'h-4 w-4 mt-0.5'} shrink-0 text-red-400`} />
        <div className="flex-1 min-w-0">
          <div className={`${compact ? 'text-[11px]' : 'text-xs'} font-medium`}>{friendly.title}</div>
          <div className={`${compact ? 'text-[10px]' : 'text-[11px]'} text-red-200/80 leading-snug mt-0.5`}>{friendly.detail}</div>
          {friendly.detail !== raw && (
            <div className={`${compact ? 'text-[9px]' : 'text-[10px]'} text-red-300/50 font-mono truncate mt-0.5`} title={raw}>
              {raw}
            </div>
          )}
        </div>
        {showAction && (
          <button
            onClick={action}
            className={`shrink-0 ${compact ? 'text-[10px] px-1.5 py-0.5' : 'text-[11px] px-2 py-1'} rounded bg-red-900/50 hover:bg-red-800/60 text-red-100`}
          >
            {friendly.actionLabel}
          </button>
        )}
      </div>
    </div>
  )
}
