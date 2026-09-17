/** Exercise the production WorkspaceEditor, Sidebar, Dockspace and game session. */
import { chromium, expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'
import process from 'node:process'

const evidence = process.env.MYTHFALL_EVIDENCE ?? '/app/artifacts/mythfall-evaluations/panels-04'
const world = async () => JSON.parse(await readFile(`${evidence}/workspace/state/world.json`, 'utf8'))
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const report = { assertions: [], requests: [], errors: [] }
const observe = (page) => {
  page.on('pageerror', (error) => report.errors.push(error.message))
  page.on('request', (request) => {
    if (!request.url().endsWith('/rpc')) return
    const body = request.postDataJSON()
    if (body.type === 'realm.action') report.requests.push(body.payload.intent)
  })
}
observe(page)
const button = (name) => page.getByRole('button', { name, exact: true })
const tab = (name) => page.locator('.dock-tab-btn').filter({ hasText: new RegExp(`^${name}$`) })
const check = (condition, label) => { if (!condition) throw new Error(label); report.assertions.push(label); console.log(label) }
const ready = async (page) => {
  await page.waitForFunction(() => window.moduleObserver?.entity(10041), { timeout: 60000 })
  await page.waitForFunction(() => window.moduleAtlasEvents?.some((event) => event.type === 'atlas.game.loaded'))
  await expect(page.locator('.mythfall-world')).toBeVisible()
}
const swordPixels = (page) => page.getByLabel('Atlas game canvas').evaluate((canvas) => {
  const camera = window.moduleObserver.entity(0)
  const width = Math.max(camera.camera.width, camera.camera.height * canvas.width / canvas.height)
  const height = Math.max(camera.camera.height, camera.camera.width * canvas.height / canvas.width)
  const x = Math.round(((24.7 - 32 - camera.transform.position[0]) / width + .5) * canvas.width)
  const y = Math.round(((23 - 24.6 - camera.transform.position[1]) / height + .5) * canvas.height)
  const pixels = new Uint8Array(30 * 30 * 4)
  const gl = canvas.getContext('webgl2')
  gl.readPixels(x - 15, y - 15, 30, 30, gl.RGBA, gl.UNSIGNED_BYTE, pixels)
  return [...pixels]
})
const topology = (layout) => {
  const box = (value) => value ? { id: value.id, mode: value.mode, activeId: value.activeId,
    tabs: value.tabs?.map((tab) => tab.id), children: value.children?.map(box) } : null
  return Object.fromEntries(['dockbox', 'floatbox', 'maxbox', 'windowbox'].map((key) => [key, box(layout[key])]))
}
let mobile
try {
  await page.goto('http://127.0.0.1:4178/test/module-host.html')
  await ready(page)
  const initial = await world()
  check(initial.revision === 0, 'Fresh canonical fixture')
  await expect(page.locator('.dock-tab-btn')).toHaveCount(10)
  check((await page.locator('canvas').count()) === 1, 'One Atlas canvas across ten PWA tabs')
  await button('Select inventory Iron sword').click()
  const beforePixels = await swordPixels(page)
  const beforeInits = await page.evaluate(() => window.moduleRenderTimings.filter((entry) => entry.name === 'init').length)
  await button('Drop').click()
  await expect(button('Select ground Iron sword')).toBeVisible()
  await expect.poll(async () => (await world()).revision).toBe(1)
  check(report.requests.length === 1, 'One click submits exactly one authoritative action')
  const swordId = 20000 + Object.keys(initial.items).sort().indexOf('item.sword') * 5
  await expect.poll(() => page.evaluate((id) => window.moduleObserver.entity(id).canvas.bitmask, swordId)).toBe(2)
  const afterPixels = await swordPixels(page)
  report.swordChangedChannels = afterPixels.filter((value, index) => index % 4 !== 3 && Math.abs(value - beforePixels[index]) > 18).length
  check(report.swordChangedChannels > 30, 'Initially hidden sword art appears in actual WebGL pixels')
  check(await page.evaluate(() => window.moduleRenderTimings.filter((entry) => entry.name === 'init').length) === beforeInits,
    'An ordinary action updates the renderer without reinitializing it')
  check(JSON.stringify((await world()).items['item.sword'].place) === JSON.stringify({ ground: [24, 24] }), 'Visible textured sword retains its world identity and position')
  await page.screenshot({ path: `${evidence}/panels-sword.png` })

  await button('Close Conversation panel').click()
  await button('Select Old Nessa').click()
  await expect(page.getByLabel('Speak to Old Nessa', { exact: true })).toBeVisible()
  await page.getByLabel('Speak to Old Nessa', { exact: true }).fill('An unsent thought survives moving this panel.')
  await button('Close Conversation panel').click()
  await button('Select Old Nessa').click()
  await expect(page.getByLabel('Speak to Old Nessa', { exact: true })).toHaveValue('An unsent thought survives moving this panel.')
  check(report.requests.length === 1, 'Selecting, reopening and editing a dialogue draft do not advance time or call a model')
  await expect(tab('Conversation')).toHaveCount(1)

  // Use a real drag gesture to dock Journal beside World.
  const source = await tab('Journal').boundingBox()
  const target = await tab('World').boundingBox()
  await page.mouse.move(source.x + 20, source.y + source.height / 2)
  await page.mouse.down()
  await page.mouse.move(source.x + 30, source.y + source.height / 2, { steps: 3 })
  await page.mouse.move(target.x + target.width / 2, target.y + target.height / 2, { steps: 18 })
  await page.waitForTimeout(150)
  await page.mouse.up()
  const docked = JSON.parse(await page.evaluate(() => localStorage.getItem('module-dock-evaluation-v1')))
  const hasBoth = (box) => box?.tabs?.some((tab) => tab.id === 'builtin.atlas') && box.tabs.some((tab) => tab.id === 'mythfall.journal')
    || box?.children?.some(hasBoth)
  check(hasBoth(docked.dockbox), 'Journal docks alongside World using the existing PWA drag interaction')

  // Delay resume transport so panel closure reliably overlaps an in-flight activity.
  await page.route('**/__module__/rpc', async (route) => {
    if (route.request().postDataJSON()?.payload?.intent?.kind === 'resume') await new Promise((resolve) => setTimeout(resolve, 300))
    await route.continue()
  })
  const beforeWait = await world()
  await button('Until dawn').click()
  await expect(button('Pause')).toBeVisible()
  await button('Close World panel').click()
  await button('Close Actions & time panel').click()
  await expect(page.locator('canvas')).toHaveCount(0)
  await expect.poll(async () => (await world()).tick, { timeout: 15000 }).toBeGreaterThan(beforeWait.tick + 600)
  check(true, 'Time advancement continues with both World and Actions panels closed')
  await button('Open Actions & time panel').click()
  await button('Pause').click()
  await expect(button('One turn')).toBeEnabled()
  const paused = await world()
  check(paused.pending.status === 'cancelled', 'Reopened Actions panel pauses the existing activity at a saved boundary')
  await button('Open World panel').click()
  await ready(page)
  const loadedCount = await page.evaluate(() => window.moduleAtlasEvents.filter((event) => event.type === 'atlas.game.loaded').length)
  check(loadedCount === 1, 'Reopening the map reattaches its canvas without restarting the Atlas scene')
  await expect.poll(() => page.evaluate((id) => window.moduleObserver.entity(id).canvas.bitmask, swordId)).toBe(0)
  check((await world()).items['item.sword'].place.carrier === 'char.old_nessa', 'NPC pickup and sprite removal remain synchronized while the map is closed')
  await page.unroute('**/__module__/rpc')
  const layoutBefore = topology(JSON.parse(await page.evaluate(() => localStorage.getItem('module-dock-evaluation-v1'))))
  await page.reload()
  await ready(page)
  const layoutAfter = topology(JSON.parse(await page.evaluate(() => localStorage.getItem('module-dock-evaluation-v1'))))
  check(JSON.stringify(layoutBefore) === JSON.stringify(layoutAfter), 'Panel arrangement and active tabs survive reload')
  check(JSON.stringify(await world()) === JSON.stringify(paused), 'Reloading the panel layout does not mutate or resume the world')
  await page.screenshot({ path: `${evidence}/panels-restored.png` })
  await page.close()

  mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  observe(mobile)
  await mobile.goto('http://127.0.0.1:4178/test/module-host.html')
  await ready(mobile)
  await mobile.screenshot({ path: `${evidence}/mobile-world.png` })
  await mobile.getByRole('button', { name: 'Open Inventory', exact: true }).click()
  await expect(mobile.getByRole('region', { name: 'Inventory', exact: true })).toBeVisible()
  const bounds = await mobile.getByRole('region', { name: 'Inventory', exact: true }).boundingBox()
  check(bounds.width > 300, 'Mobile Inventory uses the full dock width')
  await mobile.screenshot({ path: `${evidence}/mobile-inventory.png` })
  // Selecting Inventory scrolls the expanded set of game tabs; World may now
  // be offscreen. Use the ordinary dock overflow menu, as a phone user would.
  await mobile.getByRole('button', { name: '...', exact: true }).tap()
  await mobile.getByRole('option', { name: /^World/ }).tap()
  await mobile.getByRole('button', { name: 'Open Actions & time', exact: true }).click()
  const beforeStep = await world()
  await mobile.getByRole('button', { name: 'One turn', exact: true }).click()
  await expect.poll(async () => (await world()).tick).toBe(beforeStep.tick + 1)
  await expect(mobile.getByRole('button', { name: 'One turn', exact: true })).toBeEnabled()
  check((await world()).revision === beforeStep.revision + 1, 'A mobile action resolves once through the shared session')
  check(await mobile.evaluate(() => document.body.scrollWidth <= window.innerWidth), 'Mobile panels do not overflow the viewport')
  check(report.errors.length === 0, 'No browser runtime errors')
  report.finalTick = (await world()).tick
} catch (error) {
  report.failure = error.stack
  process.exitCode = 1
  console.error(error)
  const current = mobile ?? page
  if (!current.isClosed()) await current.screenshot({ path: `${evidence}/panels-failure.png` }).catch(() => {})
} finally {
  await writeFile(`${evidence}/panels-report.json`, JSON.stringify(report, null, 2))
  await browser.close()
}
