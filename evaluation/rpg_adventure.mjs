/** A bounded player playthrough. NPC/DM inference uses the installed gateway. */
import { chromium, expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'
import process from 'node:process'

const evidence = process.env.MYTHFALL_EVIDENCE ?? '/app/artifacts/mythfall-evaluations/rpg-03'
const world = async () => JSON.parse(await readFile(`${evidence}/workspace/state/world.json`, 'utf8'))
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } })
const report = { assertions: [], errors: [], outcomes: [], requests: [], actions: 0 }
const playerId = 'char.player'
page.on('pageerror', (error) => report.errors.push(error.message))
page.on('request', (request) => {
  if (!request.url().endsWith('/rpc')) return
  const body = request.postDataJSON()
  if (body.type === 'realm.action') report.requests.push(body.payload.intent)
})
const check = (condition, label) => { if (!condition) throw new Error(label); report.assertions.push(label); console.log(label) }
const button = (name) => page.getByRole('button', { name, exact: true })
const tab = (name) => page.locator('.dock-tab-btn').filter({ hasText: new RegExp(`^${name}$`) })
const ready = async () => {
  await page.waitForFunction(() => window.moduleObserver?.entity(10041), { timeout: 60000 })
  await expect(page.locator('.mythfall-world')).toBeVisible()
}
async function action(callback) {
  if (++report.actions > 65) throw new Error('Player action budget exhausted')
  const before = (await world()).game_chat?.turns.length ?? 0
  await callback()
  await expect.poll(async () => (await world()).game_chat?.turns.length ?? 0, { timeout: 190000 }).toBeGreaterThan(before)
  await expect(button('One turn')).toBeEnabled({ timeout: 190000 })
  const renderingErrors = await page.evaluate(() => (window.moduleAtlasEvents ?? []).filter((event) => event.type.endsWith('.error')))
  if (renderingErrors.length) throw new Error('Atlas reported: ' + JSON.stringify(renderingErrors))
  const after = await world()
  report.outcomes.push(after.game_chat.turns.at(-1))
  if (report.requests.filter((intent) => ['continue_combat', 'ask', 'talk'].includes(intent.kind)).length > 42) throw new Error('Live request budget exhausted')
  return after
}
const ask = (text) => action(async () => {
  await tab('Game chat').click()
  await page.getByLabel('Your intent', { exact: true }).fill(text)
  await button('Send intent').click()
})
const travel = (place) => action(() => page.getByLabel('Travel to', { exact: true }).selectOption(place))
const distance = (a, b) => Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1])
async function mapClick(point) {
  const screen = await page.getByLabel('Emberwick map', { exact: true }).evaluate((node, position) => {
    const bounds = node.getBoundingClientRect(), entity = window.moduleObserver.entity(0)
    const width = Math.max(entity.camera.width, entity.camera.height * bounds.width / bounds.height)
    const height = Math.max(entity.camera.height, entity.camera.width * bounds.height / bounds.width)
    return { x: bounds.left + (.5 + (position[0] - 32 - entity.transform.position[0]) / width) * bounds.width,
      y: bounds.top + (.5 - (23 - position[1] - entity.transform.position[1]) / height) * bounds.height }
  }, point)
  await page.mouse.click(screen.x, screen.y)
}
function route(w, destination) {
  const obstacles = new Set([...w.map.walls, ...Object.values(w.map.doors).filter((d) => !d.open).map((d) => d.position)].map(String))
  const origin = w.actors[playerId].position, queue = [[origin, []]], visited = new Set([String(origin)])
  for (let n = 0; n < queue.length; n++) {
    const [point, path] = queue[n]
    if (distance(point, destination) <= 1) return path
    for (const next of [[point[0] - 1, point[1]], [point[0] + 1, point[1]], [point[0], point[1] - 1], [point[0], point[1] + 1]]) {
      if (next[0] < 0 || next[0] >= w.map.width || next[1] < 0 || next[1] >= w.map.height || obstacles.has(String(next)) || visited.has(String(next))) continue
      visited.add(String(next)); queue.push([next, [...path, next]])
    }
  }
  throw new Error('No visible-map route')
}
try {
  await page.goto('http://127.0.0.1:4178/test/module-host.html')
  await ready()
  if (!(await world()).combat) {
  if (!(await world()).actors[playerId].rpg.classes.length) {
    await page.getByLabel('Starting class', { exact: true }).selectOption('rogue')
    await action(() => button('Begin this class').click())
  }
  await button('Select inventory Shortsword').click()
  await action(() => button('Equip').click())
  if (!(await world()).party.members.includes('char.ellis_crow')) {
  await travel('shrine')
  await button('Select Ellis Crow').click()
  await action(async () => {
    await page.getByLabel('Speak to Ellis Crow', { exact: true }).fill('I want to recover the village survey ledger safely. Would you accompany me to investigate the mine and help anyone who gets hurt? I will listen to your advice and avoid unnecessary violence.')
    await button('Speak').click()
  })
  await action(() => button('Recruit').click())
  }
  check((await world()).party.members.includes('char.ellis_crow'), 'Ellis agrees through his own live agent and joins with identity and class intact')
  await tab('Party & initiative').click()
  await expect(page.getByRole('region', { name: 'Party and initiative' })).toContainText('Ellis Crow')
  if ((await world()).quests['quest.survey_lead'].status !== 'complete') {
  await travel('mine')
  await ask('I investigate the visible survey marker and try to understand where the records were taken.')
  if ((await world()).quests['quest.survey_lead'].status !== 'complete') {
    await ask('My investigation did not resolve it. Can the old marks be interpreted through History instead? If so I attempt that check; do not reroll the same failed approach.')
  }
  }
  check((await world()).quests['quest.survey_lead'].status === 'complete', 'A resolved check reveals the first lead and awards earned XP')
  if ((await world()).actors[playerId].rpg.classes.length < 2) {
  await tab('Character').click()
  await page.getByLabel('Next class level', { exact: true }).selectOption('rogue')
  await action(() => button('Take earned level').click())
  }
  check((await world()).actors[playerId].rpg.classes.length === 2, 'The character panel spends the earned level on Rogue 2')
  await travel('office')
  await ask('I walk within arm’s reach of the survey chest in this room.')
  await ask('I open the survey chest.')
  check((await world()).fixtures['chest.survey'].open, 'The actual chest opens through the shared intent boundary')
  await button('Inspect nearby Crowglass survey ledger').click()
  await action(() => button('Pick up').click())
  let current = await world()
  check(current.items['item.survey_ledger'].place.carrier === playerId, 'Taking the protected ledger transfers that same physical item')
  check(current.combat?.participants.length === 4, 'Taking guarded property starts a four-actor party encounter')
  }
  let current = await world()
  await page.screenshot({ path: `${evidence}/encounter-start.png` })
  for (let turn = 0; turn < 16 && (await world()).combat; turn++) {
    current = await world()
    if (current.actors[playerId].life === 'dead') throw new Error('Player died; retain this failed approach')
    if (current.combat.pending?.reactor === playerId) {
      await action(() => button('Pass reaction').click()); continue
    }
    if (current.combat.awaiting !== playerId || current.combat.pending) {
      await action(() => button('Continue NPC turn').click()); continue
    }
    const targets = current.combat.participants.filter((entry) => entry.side !== 'party' && !entry.withdrawn && current.actors[entry.id].hp > 0)
      .map((entry) => current.actors[entry.id]).sort((a, b) => distance(current.actors[playerId].position, a.position) - distance(current.actors[playerId].position, b.position))
    const enemy = targets[0], budget = current.combat.economy[playerId]
    if (current.combat.round >= 3) {
      await tab('Party & initiative').click()
      await action(() => button('offer truce').click())
      continue
    }
    if (current.actors[playerId].hp > 0 && enemy && budget.action > 0) {
      if (distance(current.actors[playerId].position, enemy.position) > 1 && budget.movement > 0) {
        const path = route(current, enemy.position)
        await action(() => mapClick(path[Math.min(path.length, budget.movement) - 1]))
        current = await world()
      }
      if (current.combat && !current.combat.pending && distance(current.actors[playerId].position, current.actors[enemy.id].position) <= 1) {
        await button(`Select ${enemy.name}`).click()
        await action(() => button('Attack').click())
      }
    }
    current = await world()
    if (current.combat && current.combat.awaiting === playerId && !current.combat.pending) {
      await tab('Party & initiative').click()
      await action(() => button('end turn').click())
    }
  }
  current = await world()
  check(!current.combat && current.actors[playerId].hp > 0, 'Party resolves the encounter using live NPC and companion decisions')
  check(current.decisions.some((decision) => decision.actor === 'char.ellis_crow' && decision.encounter), 'The companion has a persisted independent combat decision')
  await page.screenshot({ path: `${evidence}/encounter-end.png` })
  await action(() => button('Long rest · 8 hours').click())
  current = await world()
  check(current.actors[playerId].hp === current.actors[playerId].max_hp, 'A completed long rest recovers the surviving player')
  await travel('hall')
  await button('Select Mara Vell').click()
  await action(() => page.getByLabel('Give an item', { exact: true }).selectOption('item.survey_ledger'))
  current = await world()
  check(current.quests['quest.survey_return'].status === 'complete' && current.items['item.survey_ledger'].place.carrier === 'char.mara_vell', 'Delivering the real ledger completes the adventure and preserves item identity')
  await tab('Character').click()
  await page.getByLabel('Next class level', { exact: true }).selectOption('rogue')
  await action(() => button('Take earned level').click())
  check((await world()).actors[playerId].rpg.subclasses.rogue === 'thief', 'Earned level 3 unlocks the Thief subclass and Fast Hands')
  await page.screenshot({ path: `${evidence}/adventure-complete.png` })
  const beforeReload = JSON.stringify(await world())
  await page.reload(); await ready()
  check(JSON.stringify(await world()) === beforeReload, 'Adventure completion, resources, minds and item transfers survive reload without replay')
  const atlasErrors = await page.evaluate(() => (window.moduleAtlasEvents ?? []).filter((event) => event.type.endsWith('.error')))
  report.atlasErrors = atlasErrors
  check(atlasErrors.length === 0, 'No Atlas renderer or asset errors')
  check(report.errors.length === 0, 'No browser runtime errors')
} catch (error) {
  report.failure = error.stack
  await page.screenshot({ path: `${evidence}/failure.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await writeFile(`${evidence}/adventure-report.json`, JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
  await browser.close()
}
