import { describe, expect, it } from 'vitest'
import { nextDatasetName } from './datasetName'

/* QA pass 2026-10-01 (Train): a new dataset was named "Dataset <count + 1>",
 * so after deleting one the next name repeated an existing one. */

describe('nextDatasetName', () => {
  it('takes the number after the highest one in use', () => {
    expect(nextDatasetName([])).toBe('Dataset 1')
    expect(nextDatasetName(['Dataset 1', 'Dataset 3'])).toBe('Dataset 4')
    expect(nextDatasetName(['Mara', 'Dataset 2', 'dataset 7 (old)'])).toBe('Dataset 3')
  })
})
