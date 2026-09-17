/** Phone panels, touch and pause against an actual completed adventure save. */
import { chromium, expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'
import process from 'node:process'

const evidence = process.env.MYTHFALL_EVIDENCE
if (!evidence) throw new Error('Set MYTHFALL_EVIDENCE to the server fixture directory')
const world = async () => JSON.parse(await readFile(`${evidence}/workspace/state/world.json`, 'utf8'))
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
const report = { assertions: [], requests: [], errors: [] }
page.on('pageerror', (error) => report.errors.push(error.message))
page.on('request', (request) => {
  if (request.url().endsWith('/rpc') && request.postDataJSON()?.type === 'realm.action') report.requests.push(request.postDataJSON().payload.intent)
})
const button = (name) => page.getByRole('button', { name, exact: true })
const check = (value, message) => { if (!value) throw new Error(message); report.assertions.push(message); console.log(message) }
async function selectTab(name) {
  await button('...').tap()
  await page.getByRole('option', { name: new RegExp(`^${name}`) }).tap()
}
let release
try {
  await page.goto('http://127.0.0.1:4178/test/module-host.html')
  await page.waitForFunction(() => window.moduleObserver?.entity(10041), { timeout: 60000 })
  const before = JSON.stringify(await world())
  await button('Open Abilities').tap()
  let abilities = page.locator('section[aria-label="Character abilities"]:visible')
  check((await abilities.boundingBox()).width > 300, 'Abilities use the phone dock width')
  await abilities.getByLabel('Character', { exact: true }).selectOption('char.ellis_crow')
  await expect(abilities).toContainText('Ellis Crow')
  await expect(abilities).toContainText('Companions decide their own actions')
  await abilities.getByLabel('Ability', { exact: true }).selectOption('ability.healing_word@1')
  await expect(abilities).toContainText('1d4')
  await abilities.getByRole('button', { name: 'Pin abilities', exact: true }).tap()
  await expect(page.locator('.dock-tab-btn').filter({ hasText: /^Pinned abilities 1$/ })).toBeVisible()
  await page.screenshot({ path: `${evidence}/mobile-abilities.png` })
  check(JSON.stringify(await world()) === before && report.requests.length === 0, 'Character selection, ability inspection and pinning consume no time or requests')
  await selectTab('World')
  await button('Open Party & initiative').tap()
  await expect(page.getByRole('region', { name: 'Party and initiative' })).toContainText('Ellis Crow')
  check((await page.getByRole('region', { name: 'Party and initiative' }).boundingBox()).width > 300, 'The party panel remains usable on a phone')
  await selectTab('World')
  const map = page.getByLabel('Emberwick map', { exact: true })
  const bounds = await map.boundingBox()
  const camera = () => page.evaluate(() => window.moduleObserver.entity(0))
  const original = await camera()
  const cdp = await page.context().newCDPSession(page)
  const touch = (type, points) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: points.map(([x, y, id = 1]) => ({ x, y, id })) })
  const start = [bounds.x + bounds.width * .5, bounds.y + bounds.height * .7]
  await touch('touchStart', [start])
  for (let n = 1; n <= 6; n++) await touch('touchMove', [[start[0] + n * 7, start[1] + n * 4]])
  await touch('touchEnd', [])
  await expect.poll(async () => (await camera()).transform.position[0]).not.toBe(original.transform.position[0])
  check(JSON.stringify(await world()) === before && report.requests.length === 0, 'Touch panning changes the native camera without changing gameplay')
  await touch('touchStart', [start])
  await touch('touchMove', [[start[0] - 20, start[1] - 15]])
  await touch('touchCancel', [])
  await touch('touchStart', [[start[0], start[1], 1], [start[0] - 40, start[1], 2]])
  await touch('touchMove', [[start[0] + 10, start[1], 1], [start[0] - 50, start[1], 2]])
  await touch('touchEnd', [])
  await button('Recenter on character').tap()
  check(JSON.stringify(await world()) === before && report.requests.length === 0, 'Cancelled and two-finger gestures do not submit movement')
  await page.screenshot({ path: `${evidence}/mobile-map.png` })
  await button('Open Actions & time').tap()
  let held = false
  await page.route('**/__module__/rpc', async (route) => {
    const intent = route.request().postDataJSON()?.payload?.intent
    if (!held && intent?.kind === 'wait') {
      held = true
      await new Promise((resolve) => { release = resolve })
    }
    await route.continue()
  })
  await button('Until dawn').tap()
  await expect.poll(() => Boolean(release)).toBe(true)
  await button('Pause').evaluate((node) => {
    node.addEventListener('click', () => {
      const started = performance.now()
      const observer = new MutationObserver(() => {
        if (node.disabled && node.textContent.includes('Pausing')) {
          window.mythfallPauseLatency = performance.now() - started
          observer.disconnect()
        }
      })
      observer.observe(node, { attributes: true, childList: true, subtree: true })
    }, { once: true })
  })
  await button('Pause').tap()
  await expect.poll(() => page.evaluate(() => window.mythfallPauseLatency ?? 10000)).toBeLessThan(250)
  report.pauseLatencyMs = await page.evaluate(() => window.mythfallPauseLatency)
  await button('Close Actions & time panel').tap()
  await button('Open Actions & time panel').tap()
  await expect(button('Pausing after current action…')).toBeDisabled()
  check(true, 'Closing and reopening the action panel preserves the pending pause')
  release()
  await expect(button('One turn')).toBeEnabled({ timeout: 30000 })
  check((await world()).pending.status === 'cancelled', 'Pause stops at the saved simulation boundary')
  check(report.requests.filter((intent) => intent.kind === 'wait').length === 1 && report.requests.filter((intent) => intent.kind === 'resume').length === 0,
    'The in-flight action finishes once and no new advancement begins after Pause')
  check(report.pauseLatencyMs < 250, 'Pause acknowledgement meets the frozen 250 ms target')
  const saved = JSON.stringify(await world())
  await selectTab('World')
  await page.reload()
  await page.waitForFunction(() => window.moduleObserver?.entity(10041), { timeout: 60000 })
  await selectTab('Pinned abilities 1')
  abilities = page.locator('section[aria-label="Character abilities"]:visible')
  await expect(abilities).toContainText('Ellis Crow')
  check(JSON.stringify(await world()) === saved, 'Pinned character and paused world survive a full reload')
  check(await page.evaluate(() => document.body.scrollWidth <= window.innerWidth), 'Phone panels stay within the viewport')
  report.atlasErrors = await page.evaluate(() => (window.moduleAtlasEvents ?? []).filter((event) => event.type.endsWith('.error')))
  check(report.errors.length === 0 && report.atlasErrors.length === 0, 'No browser or Atlas errors')
} catch (error) {
  report.failure = error.stack
  release?.()
  await page.screenshot({ path: `${evidence}/mobile-failure.png` }).catch(() => {})
  process.exitCode = 1
} finally {
  await writeFile(`${evidence}/mobile-report.json`, JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
  await browser.close()
}
