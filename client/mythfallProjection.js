// Shared by the native camera preview and pointer/label projection. Narrow
// panels zoom closer instead of showing a tall strip of empty world space.
export function mythfallProjection({ width, height }) {
  const aspect = Math.max(1, width) / Math.max(1, height)
  const cameraWidth = Math.min(36, Math.max(16, 28 * aspect))
  const cameraHeight = 28
  return {
    cameraWidth, cameraHeight,
    mapWidth: Math.max(cameraWidth, cameraHeight * aspect),
    mapHeight: Math.max(cameraHeight, cameraWidth / aspect),
  }
}

export function mythfallMapPoint(center, viewport, x, y) {
  const { mapWidth, mapHeight } = mythfallProjection(viewport)
  return [center[0] + (x - .5) * mapWidth, center[1] + (y - .5) * mapHeight]
}

export function mythfallCamera(center, viewport, entity) {
  const { cameraWidth, cameraHeight } = mythfallProjection(viewport)
  const [x, y] = [center[0] - 32, 23 - center[1]]
  return { ...entity, transform: { ...entity.transform, position: [x, y, 100] },
    camera: { ...entity.camera, target: [x, y, 0], width: cameraWidth, height: cameraHeight } }
}
