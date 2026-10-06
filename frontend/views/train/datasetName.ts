/**
 * The default name for a new dataset (QA pass 2026-10-01): "Dataset N" with
 * N one past the highest in use - the count repeated a name after a deletion.
 */
export function nextDatasetName(names: string[]): string {
  const used = names.map(name => /^Dataset (\d+)$/.exec(name.trim())).filter(Boolean).map(m => Number(m![1]))
  return `Dataset ${(used.length ? Math.max(...used) : 0) + 1}`
}
