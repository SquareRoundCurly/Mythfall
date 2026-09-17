/** Ordinary UI actions and real touch input; canonical/native observers are read-only. */
import { chromium, expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'
import process from 'node:process'

const evidence = process.env.MYTHFALL_EVIDENCE
if (!evidence) throw new Error('Set MYTHFALL_EVIDENCE to a fresh fixture directory.')
const world = async () => JSON.parse(await readFile(`${evidence}/workspace/state/world.json`, 'utf8'))
const browser = await chromium.launch({ headless: true })
let page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const report = { assertions: [], actions: [], errors: [] }
const check = (condition, label) => { if (!condition) throw new Error(label); report.assertions.push(label); console.log(label) }
function observe() {
  page.on('pageerror', (error) => report.errors.push(error.message))
  page.on('request', (request) => {
    if (!request.url().endsWith('/rpc')) return
    const body = request.postDataJSON()
    if (body.type === 'realm.action') report.actions.push(body.payload)
  })
}
const button = (name) => page.getByRole('button', { name, exact: true })
const tab = (name) => page.locator('.dock-tab-btn').filter({ hasText: new RegExp(`^${name}$`) })
async function ready() {
  await page.waitForFunction(() => window.moduleObserver?.entity(10041), { timeout: 60000 })
  await expect(page.getByLabel('Emberwick map', { exact: true })).toBeVisible()
}
const camera = () => page.evaluate(() => window.moduleObserver.entity(0))
async function tilePoint(position) {
  return page.getByLabel('Emberwick map', { exact: true }).evaluate((node, point) => {
    const bounds = node.getBoundingClientRect()
    const entity = window.moduleObserver.entity(0)
    const width = Math.max(entity.camera.width, entity.camera.height * bounds.width / bounds.height)
    const height = Math.max(entity.camera.height, entity.camera.width * bounds.height / bounds.width)
    return { x: bounds.left + (.5 + (point[0] - 32 - entity.transform.position[0]) / width) * bounds.width,
      y: bounds.top + (.5 - (23 - point[1] - entity.transform.position[1]) / height) * bounds.height }
  }, position)
}
try {
  observe()
  await page.goto('http://127.0.0.1:4178/test/module-host.html')
  await ready()
  check((await world()).revision === 0, 'Fresh canonical fixture')
  await expect(tab('Game chat')).toBeVisible()
  await expect(tab('Chat')).toBeVisible()
  await expect(page.getByLabel('Your intent', { exact: true })).toBeVisible()
  check(true, 'Game chat is an additional PWA dock panel beside existing Chat')
  const inits = await page.evaluate(() => window.moduleRenderTimings.filter((entry) => entry.name === 'init').length)
  await button('Select inventory Iron sword').click()
  await button('Drop').click()
  await expect.poll(async () => (await world()).game_chat?.turns.length).toBe(1)
  await expect(page.getByRole('log', { name: 'Game history' })).toContainText('Drop Iron sword.')
  check((await world()).items['item.sword'].place.ground?.[0] === 24, 'Inventory action records its intent and actual item transfer in Game chat')

  const words = 'Pick up my iron sword.'
  await page.getByLabel('Your intent', { exact: true }).fill(words)
  await button('Send intent').click()
  await expect.poll(async () => (await world()).game_chat?.turns.length, { timeout: 150000 }).toBe(2)
  await expect(button('Drop')).toBeEnabled()
  check((await world()).items['item.sword'].place.carrier === 'char.player', 'Live Astra intent resolves through the same inventory rules')
  await expect(page.getByRole('log', { name: 'Game history' })).toContainText(words)

  await button('Select Old Nessa').click()
  await page.getByLabel('Speak to Old Nessa', { exact: true }).fill('Good morning. What is this place?')
  await button('Speak').click()
  await expect.poll(async () => (await world()).game_chat?.turns.length, { timeout: 150000 }).toBe(3)
  await expect(button('Speak')).toBeDisabled()
  const conversation = (await world()).game_chat.turns[2]
  const npc = conversation.messages.find((entry) => entry.speaker === 'Old Nessa')
  check(Boolean(npc?.text), 'NPC panel speech and live NPC response join the same ordered transcript')
  await button('View in Game chat').click()
  await expect(page.getByRole('log', { name: 'Game history' })).toContainText(npc.text)
  check(report.actions.length === 3, 'Mirroring GUI actions in chat never submits a second action')

  const beforeRejected = await world()
  const wall = await tilePoint([35, 20])
  await page.mouse.click(wall.x, wall.y)
  await expect.poll(async () => (await world()).game_chat?.turns.length).toBe(4)
  const rejected = await world()
  check(rejected.tick === beforeRejected.tick && rejected.revision === beforeRejected.revision && rejected.rng === beforeRejected.rng,
    'Rejected map destination is recorded without advancing clock, revision, or randomness')
  await expect(page.getByRole('log', { name: 'Game history' })).toContainText('Choose a reachable map destination.')

  await page.getByLabel('Your intent', { exact: true }).fill('An unsent thought survives closing this tab.')
  await button('Close Game chat panel').click()
  await button('Open Game chat').click()
  await expect(page.getByLabel('Your intent', { exact: true })).toHaveValue('An unsent thought survives closing this tab.')
  await page.getByLabel('Your intent', { exact: true }).fill('')
  check((await world()).game_chat.turns.length === 4, 'Panel closure preserves the composer without sending it')

  // A delayed resume transport makes it possible to pause deterministically.
  await page.route('**/__module__/rpc', async (route) => {
    if (route.request().postDataJSON()?.payload?.intent?.kind === 'resume') await new Promise((resolve) => setTimeout(resolve, 300))
    await route.continue()
  })
  await button('Until dawn').click()
  await expect.poll(async () => (await world()).game_chat?.revision).toBeGreaterThan(5)
  await button('Pause activity').click()
  await expect(button('One turn')).toBeEnabled()
  const paused = await world()
  check(paused.pending.status === 'cancelled' && paused.game_chat.turns.length === 5,
    'Multiple continuation chunks and a chat Pause update one original activity turn')
  await page.unroute('**/__module__/rpc')
  await expect(page.getByRole('log', { name: 'Game history' })).toContainText('Activity paused.')
  check(await page.evaluate(() => window.moduleRenderTimings.filter((entry) => entry.name === 'init').length) === inits,
    'Chat updates and panel changes do not reinitialize Atlas')
  await page.screenshot({ path: `${evidence}/desktop-game-chat.png` })
  await page.reload()
  await ready()
  await expect(page.getByRole('log', { name: 'Game history' })).toContainText(npc.text)
  check(JSON.stringify(await world()) === JSON.stringify(paused), 'Reload restores transcript and exact paused world without replay')
  await page.close()

  page = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  observe()
  await page.goto('http://127.0.0.1:4178/test/module-host.html')
  await ready()
  const cdp = await page.context().newCDPSession(page)
  const touch = (type, points) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: points.map(([x, y, id = 1]) => ({ x, y, id })) })
  const map = page.getByLabel('Emberwick map', { exact: true })
  const bounds = await map.boundingBox()
  const beforePan = await world()
  const actionCount = report.actions.length
  const originalCamera = await camera()
  const start = [bounds.x + bounds.width * .6, bounds.y + bounds.height * .65]
  await touch('touchStart', [start])
  for (let n = 1; n <= 8; n++) await touch('touchMove', [[start[0] + n * 7, start[1] + n * 5]])
  await touch('touchEnd', [])
  await expect.poll(async () => (await camera()).transform.position[0]).not.toBe(originalCamera.transform.position[0])
  await page.waitForTimeout(350)
  check(report.actions.length === actionCount && JSON.stringify(await world()) === JSON.stringify(beforePan),
    'Real one-finger drag moves the camera without a click, action, or clock change')
  const panned = await camera()
  check(panned.transform.position[0] < originalCamera.transform.position[0] && panned.transform.position[1] > originalCamera.transform.position[1],
    'Map follows the finger in both axes in the native Atlas camera')
  const nativeWidth = Math.max(originalCamera.camera.width, originalCamera.camera.height * bounds.width / bounds.height)
  const nativeHeight = Math.max(originalCamera.camera.height, originalCamera.camera.width * bounds.height / bounds.width)
  check(Math.abs(panned.transform.position[0] - originalCamera.transform.position[0] + 56 * nativeWidth / bounds.width) < .05 &&
    Math.abs(panned.transform.position[1] - originalCamera.transform.position[1] - 40 * nativeHeight / bounds.height) < .05,
    'Capture transfer preserves the entire drag distance, including subsequent pointer moves')
  const label = page.getByRole('button', { name: 'Select Rowan', exact: true })
  const playerPoint = await tilePoint(beforePan.actors['char.player'].position)
  const labelBounds = await label.boundingBox()
  check(Math.abs(labelBounds.x + labelBounds.width / 2 - playerPoint.x) < 2,
    'Character label remains aligned with the panned native sprite')
  await page.screenshot({ path: `${evidence}/mobile-panned.png` })

  const destination = [beforePan.actors['char.player'].position[0] - 1, beforePan.actors['char.player'].position[1]]
  const point = await tilePoint(destination)
  await page.touchscreen.tap(point.x, point.y)
  await expect.poll(async () => (await world()).actors['char.player'].position).toEqual(destination)
  check(report.actions.length === actionCount + 1, 'A tap after dragging walks once to the tile rendered under the finger')
  await expect.poll(async () => (await world()).game_chat?.turns.length).toBe(beforePan.game_chat.turns.length + 1)

  const beforeCancel = await world()
  const cancelCount = report.actions.length
  await touch('touchStart', [start])
  await touch('touchMove', [[start[0] + 24, start[1] + 18]])
  await touch('touchCancel', [])
  await touch('touchStart', [[start[0], start[1], 1]])
  await touch('touchStart', [[start[0], start[1], 1], [start[0] - 40, start[1], 2]])
  await touch('touchMove', [[start[0] + 10, start[1], 1], [start[0] - 50, start[1], 2]])
  await touch('touchEnd', [])
  await page.waitForTimeout(300)
  check(report.actions.length === cancelCount && JSON.stringify(await world()) === JSON.stringify(beforeCancel),
    'Cancelled and two-finger gestures cannot accidentally move the character')
  await button('Recenter on character').tap()
  await expect.poll(async () => (await camera()).transform.position.slice(0, 2)).toEqual([destination[0] - 29, 23 - destination[1]])
  check(JSON.stringify(await world()) === JSON.stringify(beforeCancel), 'Recenter resumes following the character without changing the world')

  // Start a drag on a character label: it must neither select nor walk.
  const actorBox = await label.boundingBox()
  const onActor = [actorBox.x + actorBox.width / 2, actorBox.y + actorBox.height / 2]
  await touch('touchStart', [onActor])
  await touch('touchMove', [[onActor[0] + 30, onActor[1] - 30]])
  await touch('touchEnd', [])
  await expect(map).toBeVisible()
  check(report.actions.length === cancelCount, 'Dragging from an actor label does not activate its panel or walk')
  const cameraBeforePanel = await camera()
  await button('Open Game chat').tap()
  await expect(page.getByRole('log', { name: 'Game history' })).toContainText(npc.text)
  await expect(page.getByLabel('Your intent', { exact: true })).toBeVisible()
  check((await page.getByRole('region', { name: 'Game chat', exact: true }).boundingBox()).width > 300,
    'Game chat uses the full mobile dock width and retains desktop history')
  await expect.poll(() => page.getByRole('log', { name: 'Game history' }).evaluate((node) => node.scrollHeight - node.scrollTop - node.clientHeight)).toBeLessThan(2)
  check(true, 'Opening a previously hidden Game chat shows the latest outcome')
  await page.screenshot({ path: `${evidence}/mobile-game-chat.png` })
  await tab('World').click()
  await expect.poll(async () => (await camera()).transform.position).toEqual(cameraBeforePanel.transform.position)
  check(await page.evaluate(() => document.body.scrollWidth <= window.innerWidth), 'Phone panels remain within the viewport')
  check(report.errors.length === 0, 'No browser runtime errors')
  report.finalTick = (await world()).tick
} catch (error) {
  report.failure = error.stack
  process.exitCode = 1
  console.error(error)
  if (!page.isClosed()) await page.screenshot({ path: `${evidence}/failure.png` }).catch(() => {})
} finally {
  await writeFile(`${evidence}/chat-touch-report.json`, JSON.stringify(report, null, 2))
  await browser.close()
}
