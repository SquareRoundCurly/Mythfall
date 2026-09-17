/** Real Atlas/PWA acceptance; start the Mythfall evaluation server on a copy of rpg-08. */
import { chromium, expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'
import process from 'node:process'

const evidence = process.env.MYTHFALL_EVIDENCE
if (!evidence) throw new Error('Set MYTHFALL_EVIDENCE to the copied adventure fixture')
const world = async () => JSON.parse(await readFile(`${evidence}/workspace/state/world.json`, 'utf8'))
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const report = { assertions: [], requests: [], errors: [] }
page.on('pageerror', (error) => report.errors.push(error.message))
page.on('request', (request) => {
  if (request.url().endsWith('/rpc') && request.postDataJSON()?.type === 'realm.action') report.requests.push(request.postDataJSON().payload.intent)
})
const button = (name) => page.getByRole('button', { name, exact: true })
const check = (value, message) => { if (!value) throw new Error(message); report.assertions.push(message); console.log(message) }
const sheet = () => page.getByRole('region', { name: 'Character sheet', exact: true })
try {
  await page.goto('http://127.0.0.1:4178/test/module-host.html')
  await page.waitForFunction(() => window.moduleObserver?.entity(10041), { timeout: 60000 })
  const before = await world()
  const companionId = 'char.ellis_crow'
  const initial = before.actors[companionId].relationships['char.player'] ?? 0
  await button('Open Character').click()
  await sheet().getByLabel('Character', { exact: true }).selectOption(companionId)
  await expect(sheet()).toContainText(`Relationship with you: ${initial}`)
  check(JSON.stringify(await world()) === JSON.stringify(before) && report.requests.length === 0,
    'Inspecting a companion relationship consumes no world time or action requests')
  await sheet().getByLabel('Character', { exact: true }).selectOption('char.player')
  await expect(sheet()).not.toContainText('Relationship with you:')
  check(true, 'The player sheet does not invent a relationship with oneself')
  await button('Open Conversation').click()
  const conversation = page.getByRole('region', { name: 'Conversation', exact: true })
  await conversation.getByLabel('Person in view').selectOption(companionId)
  await conversation.getByLabel('Give an item').selectOption('food.char.player.0')
  await expect.poll(async () => (await world()).actors[companionId].relationships['char.player']).toBe(initial + 1)
  await button('Open Party & initiative').click()
  const party = page.getByRole('region', { name: 'Party and initiative' })
  await expect(party).toContainText(`Relationship with you: +${initial + 1}`)
  const after = await world()
  check(after.items['food.char.player.0'].place.carrier === companionId && report.requests.length === 1 && report.requests[0].kind === 'give',
    'One real GUI gift transfers the same item and updates the companion relationship in the party panel')
  await button('Open Character').click()
  await sheet().getByLabel('Character', { exact: true }).selectOption(companionId)
  await expect(sheet()).toContainText(`Relationship with you: +${initial + 1}`)
  check(true, 'The character sheet agrees with the authoritative relationship after the gift')
  await page.screenshot({ path: `${evidence}/relationships-desktop.png` })
  const observation = await page.evaluate(async () => {
    const response = await fetch('/__module__/rpc', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'realm.observe' }) })
    return (await response.json()).payload.world
  })
  check(!['memories', 'beliefs', 'known', 'relationships', 'goals', 'values', 'thoughts'].some((key) => key in observation.characters[companionId]),
    'The companion panel receives a limited relationship score without the companion’s private mind')
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  mobile.on('pageerror', (error) => report.errors.push(error.message))
  await mobile.goto('http://127.0.0.1:4178/test/module-host.html')
  await mobile.waitForFunction(() => window.moduleObserver?.entity(10041), { timeout: 60000 })
  await mobile.getByRole('button', { name: 'Open Character', exact: true }).tap()
  const phoneSheet = mobile.getByRole('region', { name: 'Character sheet', exact: true })
  await phoneSheet.getByLabel('Character', { exact: true }).selectOption(companionId)
  const relationship = phoneSheet.getByText('Relationship with you:')
  await expect(relationship).toContainText(`+${initial + 1}`)
  await relationship.scrollIntoViewIfNeeded()
  const bounds = await relationship.boundingBox()
  check(bounds.x >= 0 && bounds.x + bounds.width <= 390 && await mobile.evaluate(() => document.body.scrollWidth <= window.innerWidth),
    'A new phone page restores the saved relationship and displays it within the viewport')
  await mobile.screenshot({ path: `${evidence}/relationships-mobile.png` })
  check(JSON.stringify(await world()) === JSON.stringify(after), 'Panel selection and the second browser leave the saved world unchanged')
  report.atlasErrors = [...await page.evaluate(() => window.moduleAtlasEvents ?? []), ...await mobile.evaluate(() => window.moduleAtlasEvents ?? [])]
    .filter((event) => event.type.endsWith('.error'))
  check(report.errors.length === 0 && report.atlasErrors.length === 0, 'No browser or Atlas errors on desktop or phone')
  report.result = 'passed'
} catch (error) {
  report.result = 'failed'
  report.failure = error.stack
  await page.screenshot({ path: `${evidence}/relationships-failure.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await writeFile(`${evidence}/relationships-report.json`, JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
  await browser.close()
}
