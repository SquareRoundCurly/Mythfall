import { chromium, expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'
import process from 'node:process'
const evidence = process.env.MYTHFALL_EVIDENCE ?? '/app/artifacts/mythfall-evaluations/browser-03'
const state = async () => JSON.parse(await readFile(`${evidence}/workspace/state/world.json`, 'utf8'))
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
const report = { assertions: [], errors: [], actions: [] }
page.on('pageerror', (error) => report.errors.push(error.message))
const check = (value, text) => { if (!value) throw new Error(text); report.assertions.push(text) }
async function act(fn, label, timeout = 15000) {
  const before = await state(), started = Date.now()
  await fn()
  await expect.poll(async () => (await state()).revision, { timeout }).toBeGreaterThan(before.revision)
  await expect(page.getByRole('button', { name: 'One turn', exact: true })).toBeEnabled({ timeout })
  const after = await state()
  report.actions.push({ label, tick: after.tick, elapsedMs: Date.now() - started })
  console.log(label, after.tick)
  return after
}
try {
  await page.goto('http://127.0.0.1:4178/test/module-host.html')
  await page.waitForFunction(() => window.moduleObserver?.entity(10041))
  await page.getByRole('button', { name: 'Select inventory Iron sword', exact: true }).click()
  await act(() => page.getByRole('button', { name: 'Drop', exact: true }).click(), 'Drop sword')
  await act(() => page.getByRole('button', { name: 'Pick up', exact: true }).click(), 'Intervene before Nessa')
  let world = await act(() => page.getByRole('button', { name: '1 minute', exact: true }).click(), 'Observe changed NPC plan')
  check(world.items['item.sword'].place.carrier === 'char.player', 'Player intervention keeps the same sword')
  check(!world.events.some((e) => e.kind === 'take' && e.actor !== 'char.player' && e.targets.includes('item.sword')), 'The stale NPC plan cannot take a carried sword')
  check(world.events.some((e) => e.kind === 'plan_blocked' && e.actor === 'char.old_nessa'), 'Nessa reconsiders the changed circumstances')
  await page.screenshot({ path: `${evidence}/01-intervention.png` })
  await page.getByLabel('Your action', { exact: true }).fill('Leave my brass lantern on the ground here.')
  await act(() => page.getByRole('button', { name: 'Act', exact: true }).click(), 'Language drop of a different item', 100000)
  await page.getByRole('button', { name: 'Select ground Brass lantern', exact: true }).click()
  world = await act(() => page.getByRole('button', { name: 'Watch for pickup', exact: true }).click(), 'Watch for lantern collection')
  check(world.items['item.lantern'].place.carrier === 'char.old_nessa', 'The same motive and resolver also collect a lantern')
  await page.getByRole('button', { name: 'Select Old Nessa', exact: true }).click()
  await page.getByLabel('Speak to Old Nessa', { exact: true }).fill('Please return the brass lantern you picked up. Do you remember me taking my sword back earlier?')
  world = await act(() => page.getByRole('button', { name: 'Speak', exact: true }).click(), 'Conversation grounded in witnessed events', 100000)
  for (let n = 0; world.items['item.lantern'].place.carrier !== 'char.player' && n < 12; n++) world = await act(() => page.getByRole('button', { name: 'One turn', exact: true }).click(), 'Execute return plan')
  check(world.items['item.lantern'].place.carrier === 'char.player', 'Live NPC returns the second item through normal rules')
  await page.screenshot({ path: `${evidence}/02-memory-and-return.png` })
  // The player can give an actual object, then discuss it; testimony alone cannot transfer it.
  await act(() => page.getByLabel('Give an item', { exact: true }).selectOption('item.lantern'), 'Give Nessa the returned lantern')
  world = await state()
  check(world.items['item.lantern'].owner === 'char.old_nessa', 'Giving changes ownership as well as possession')
  const beforeKeyboard = world.actors['char.player'].position
  await page.locator('canvas').focus()
  world = await act(() => page.keyboard.press('ArrowDown'), 'Arrow-key movement through shared rules')
  check(world.actors['char.player'].position[1] === beforeKeyboard[1] + 1, 'Focused canvas forwards the player arrow key')
  // Actual pointer coordinates route through travel; no teleport helper exists.
  const beforeClick = world.actors['char.player'].position
  await act(async () => {
    const rect = await page.getByRole('application', { name: 'Emberwick map' }).boundingBox()
    const camera = await page.evaluate(() => window.moduleObserver.entity(0).camera)
    const width = Math.max(camera.width, camera.height * rect.width / rect.height)
    await page.mouse.click(rect.x + rect.width * (.5 + (beforeClick[0] + 1 - beforeClick[0] - 3) / width), rect.y + rect.height * .5)
  }, 'Pointer travel')
  world = await state()
  check(world.actors['char.player'].position[0] === beforeClick[0] + 1, 'Map pointer destination matches the actual native view')
  // Reload and touch preserve the authoritative state and usable controls.
  const saved = JSON.stringify(world)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await page.waitForFunction(() => window.moduleObserver?.entity(10041))
  check(JSON.stringify(await state()) === saved, 'Second save/resume preserves exact state')
  await page.screenshot({ path: `${evidence}/03-mobile.png` })
  await act(() => page.getByRole('button', { name: 'One turn', exact: true }).click(), 'Narrow-screen time control')
  check(report.errors.length === 0, 'No browser errors in intervention/mobile playthrough')
  report.completed = true
} catch (error) {
  report.completed = false; report.failure = error.stack; process.exitCode = 1; console.error(error)
  await page.screenshot({ path: `${evidence}/failure.png` }).catch(() => {})
} finally {
  await writeFile(`${evidence}/intervention-report.json`, JSON.stringify(report, null, 2))
  await browser.close()
}
