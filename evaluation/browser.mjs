/** Independent acceptance: only ordinary rendered controls mutate the world. */
import { chromium, expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'
import process from 'node:process'

const evidence = process.env.MYTHFALL_EVIDENCE ?? '/app/artifacts/mythfall-evaluations/browser-01'
const statePath = `${evidence}/workspace/state/world.json`
const world = async () => JSON.parse(await readFile(statePath, 'utf8'))
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const record = { startedAt: new Date().toISOString(), actions: [], playerActions: [], errors: [], assertions: [] }
page.on('pageerror', (error) => record.errors.push(error.message))
page.on('crash', () => record.errors.push('Browser renderer crashed'))
process.once('SIGTERM', () => { record.terminationSignalAt = new Date().toISOString() })
page.on('response', async (response) => {
  if (!response.url().endsWith('/rpc')) return
  const request = response.request().postDataJSON()
  if (request?.type !== 'realm.action') return
  const result = await response.json()
  await response.finished()
  record.actions.push({ intent: request.payload.intent, status: response.status(), result: result.payload?.result ?? result,
    durationMs: response.request().timing().responseEnd })
})
async function act(interact, label, timeout = 15000) {
  const before = await world()
  const started = Date.now()
  await interact()
  await expect.poll(async () => (await world()).revision, { timeout, message: label }).toBeGreaterThan(before.revision)
  await expect(page.getByRole('button', { name: 'One turn', exact: true })).toBeEnabled({ timeout })
  const after = await world()
  record.playerActions.push({ label, elapsedMs: Date.now() - started, tick: after.tick })
  console.log(label, after.tick, after.revision)
  return after
}
async function screenshot(name) { await page.screenshot({ path: `${evidence}/${name}.png` }) }
function check(condition, label) {
  if (!condition) throw new Error(label)
  record.assertions.push(label)
}
try {
  await page.goto('http://127.0.0.1:4178/test/module-host.html')
  await page.waitForFunction(() => window.moduleObserver?.entity(10041))
  const initial = await world()
  check(initial.tick === 4800 && initial.revision === 0, 'Fresh fixed fixture')
  await page.waitForTimeout(1200)
  check((await world()).tick === initial.tick, 'Reading/rendering consumes no world time')
  await page.getByRole('button', { name: 'Select Old Nessa', exact: true }).click()
  await expect(page.getByRole('img', { name: 'Old Nessa', exact: true })).toBeVisible()
  await screenshot('01-village')
  await page.getByRole('button', { name: 'Select inventory Iron sword', exact: true }).click()
  let state = await act(() => page.getByRole('button', { name: 'Drop', exact: true }).click(), 'Drop sword')
  check(JSON.stringify(state.items['item.sword'].place) === JSON.stringify({ ground: [24, 24] }), 'Same sword lies on actual square tile')
  const swordEntity = 20000 + Object.keys(state.items).sort().indexOf('item.sword') * 5
  await expect.poll(() => page.evaluate((id) => window.moduleObserver.entity(id).canvas.bitmask === 2, swordEntity)).toBe(true)
  await screenshot('02-sword-ground')
  state = await act(() => page.getByRole('button', { name: 'Watch for pickup', exact: true }).click(), 'Watch for collection')
  check(state.items['item.sword'].place.carrier === 'char.old_nessa', 'Nessa holds the original sword')
  for (const kind of ['notice', 'move', 'take']) check(state.events.some((event) => event.actor === 'char.old_nessa' && event.kind === kind), `Ordinary NPC ${kind} event`)
  await expect.poll(() => page.evaluate((id) => window.moduleObserver.entity(id).canvas.bitmask === 2, swordEntity)).toBe(false)
  await expect(page.getByRole('button', { name: 'Select inventory Iron sword', exact: true })).toHaveCount(0)
  await screenshot('03-sword-collected')
  await page.getByRole('button', { name: 'Select Old Nessa', exact: true }).click()
  await page.getByLabel('Speak to Old Nessa', { exact: true }).fill('You picked up the iron sword I set down. Would you hand it back to me, please?')
  state = await act(() => page.getByRole('button', { name: 'Speak', exact: true }).click(), 'Ask Nessa for the sword', 100000)
  for (let n = 0; state.items['item.sword'].place.carrier !== 'char.player' && n < 15; n += 1) {
    state = await act(() => page.getByRole('button', { name: 'One turn', exact: true }).click(), 'Let Nessa carry out her plan')
  }
  check(state.items['item.sword'].place.carrier === 'char.player', 'Live Astra plan returns the same sword through give action')
  check(state.actors['char.old_nessa'].memories.some((memory) => memory.kind === 'speech'), 'Conversation persists in NPC memory')
  await screenshot('04-conversation')
  await page.getByRole('button', { name: 'Select inventory Iron sword', exact: true }).click()
  await act(() => page.getByRole('button', { name: 'Equip', exact: true }).click(), 'Equip returned sword')
  await act(() => page.getByLabel('Travel to', { exact: true }).selectOption('road'), 'Travel to Bramble Road')
  await page.getByRole('button', { name: 'Select Brakka', exact: true }).click()
  state = await act(() => page.getByRole('button', { name: 'Attack', exact: true }).click(), 'Start bounded encounter')
  check(state.combat !== null, 'Encounter pauses for the player on the same clock')
  await screenshot('05-encounter')
  for (let n = 0; state.combat && n < 12; n += 1) {
    state = await act(() => page.getByRole('button', { name: 'Attack', exact: true }).click(), 'Resolve encounter action')
  }
  check(state.combat === null && state.actors['char.player'].hp > 0, 'Bounded encounter resolves with player conscious')
  await act(() => page.getByLabel('Travel to', { exact: true }).selectOption('square'), 'Return to Emberwick')
  // Natural-language duration uses exactly the same bounded advancement controls.
  await page.getByLabel('Your action', { exact: true }).fill('Rest here for six hours.')
  await act(() => page.getByRole('button', { name: 'Act', exact: true }).click(), 'Language rest and accelerated time', 100000)
  await screenshot('06-evening')
  // Exercise cancellation without a hidden simulation helper.
  await page.getByRole('button', { name: 'Until dawn', exact: true }).click()
  const pauseStarted = Date.now()
  await page.getByRole('button', { name: 'Pause', exact: true }).click()
  await expect(page.getByRole('button', { name: 'One turn', exact: true })).toBeEnabled()
  check((await world()).pending.status === 'cancelled', 'Pause cancels at a persisted chunk boundary')
  record.pauseMs = Date.now() - pauseStarted
  check(record.pauseMs < 2000, 'Pause meets the frozen two-second responsiveness budget')
  for (let n = 0; (await world()).tick < initial.tick + 14400 && n < 40; n += 1) {
    state = await world()
    if (state.actors['char.player'].hunger >= 6000) {
      await page.getByRole('button', { name: 'Select inventory Bread and apple', exact: true }).first().click()
      await act(() => page.getByRole('button', { name: 'Eat', exact: true }).click(), 'Eat carried provisions')
    }
    await act(() => page.getByRole('button', { name: 'Rest 1 hour', exact: true }).click(), 'Advance village routines')
  }
  state = await world()
  check(state.tick >= initial.tick + 14400, 'A complete simulated day passes through ordinary controls')
  check(state.actors['char.player'].fatigue < initial.actors['char.player'].fatigue, 'Rest improves fatigue')
  const saved = JSON.stringify(state)
  await screenshot('07-next-day')
  await page.reload()
  await page.waitForFunction(() => window.moduleObserver?.entity(10041))
  check(JSON.stringify(await world()) === saved, 'Reload preserves exact canonical state, memories, schedules and clock')
  await expect(page.getByRole('button', { name: 'Select inventory Iron sword', exact: true })).toBeVisible()
  await screenshot('08-resumed')
  check(record.errors.length === 0, 'No browser runtime errors')
  record.completed = true
  record.final = { tick: state.tick, revision: state.revision, playerHp: state.actors['char.player'].hp }
} catch (error) {
  record.completed = false
  record.failure = error.stack
  console.error(error)
  await screenshot('failure').catch(() => {})
  process.exitCode = 1
} finally {
  record.finishedAt = new Date().toISOString()
  await writeFile(`${evidence}/browser-report.json`, JSON.stringify(record, null, 2))
  await browser.close()
}
