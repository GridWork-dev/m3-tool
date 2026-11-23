import { expect, test, vi } from 'vitest'
import { validateGlb } from '../../../src/lib/asset-validate.ts'
import { makeProduct, toGlb } from './fixtures.ts'

// Makes a check throw, as a bug in one would. The module is mocked for this file only.
vi.mock('@gltf-transform/core', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@gltf-transform/core')>()),
  getBounds: () => {
    throw new Error('bug in a check')
  },
}))

test('a throw from the checks propagates, and is not reported as an unreadable GLB', async () => {
  const glb = await toGlb(makeProduct())
  await expect(validateGlb(glb, 'product')).rejects.toThrow('bug in a check')
})
