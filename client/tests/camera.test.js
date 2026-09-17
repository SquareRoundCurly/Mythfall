import { defaultLayout } from '../registry.js'
import assert from 'node:assert/strict'
import test from 'node:test'
import { mythfallCamera, mythfallMapPoint, mythfallProjection } from '../mythfallProjection.js'

test('map interaction and native camera use matching extents on phones and wide docks', () => {
  for (const viewport of [{ width: 348, height: 746 }, { width: 800, height: 600 }, { width: 1200, height: 400 }]) {
    const { mapWidth, mapHeight, cameraWidth, cameraHeight } = mythfallProjection(viewport)
    assert.ok(Number.isFinite(mapWidth) && Number.isFinite(mapHeight))
    assert.ok(Math.abs(mapWidth / mapHeight - viewport.width / viewport.height) < 1e-10)
    assert.ok(mapWidth >= cameraWidth && mapHeight >= cameraHeight)
  }
  assert.equal(mythfallProjection({ width: 348, height: 746 }).mapWidth, 16)
})

test('panned map picks the world position rendered by the native camera at every aspect ratio', () => {
  for (const viewport of [{ width: 348, height: 746 }, { width: 800, height: 600 }, { width: 1200, height: 400 }]) {
    const center = [33.8, 19.4]
    const camera = mythfallCamera(center, viewport, { id: 0, camera: { projection: 'orthographic' } })
    const { mapWidth, mapHeight } = mythfallProjection(viewport)
    for (const [x, y] of [[.2, .3], [.5, .5], [.9, .85]]) {
      const point = mythfallMapPoint(center, viewport, x, y)
      const nativeX = point[0] - 32
      const nativeY = 23 - point[1]
      assert.ok(Math.abs((nativeX - camera.transform.position[0]) / mapWidth + .5 - x) < 1e-10)
      assert.ok(Math.abs(.5 - (nativeY - camera.transform.position[1]) / mapHeight - y) < 1e-10)
    }
  }
})


test('both game layouts give every dock container a stable unique identity', () => {
  for (const compact of [false, true]) {
    const ids = new Set()
    const inspect = (box) => {
      assert.ok(box.id)
      assert.ok(!ids.has(box.id))
      ids.add(box.id)
      box.children?.forEach(inspect)
    }
    inspect(defaultLayout({ compact }).dockbox)
  }
})
