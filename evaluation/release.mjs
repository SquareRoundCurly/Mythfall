/** Observe a published rule and panel change together through real controls. */
import assert from 'node:assert/strict'
import { readFile, writeFile } from 'node:fs/promises'
import { chromium, expect } from '@playwright/test'

const evidence = process.env.MYTHFALL_EVIDENCE
if (!evidence) throw new Error('Set MYTHFALL_EVIDENCE')
const world = async () => JSON.parse(await readFile(`${evidence}/workspace/state/world.json`, 'utf8'))
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const report = { assertions: [], errors: [] }
page.on('pageerror', (error) => report.errors.push(error.message))
try {
  await page.goto('http://127.0.0.1:4178/test/module-host.html')
  await expect(page.getByLabel('Starting class', { exact: true })).toBeVisible()
  await page.getByLabel('Starting class', { exact: true }).selectOption('cleric')
  await page.getByRole('button', { name: 'Begin this class', exact: true }).click()
  await expect.poll(async () => (await world()).actors['char.player'].rpg.classes).toContain('cleric')
  if ((await world()).actors['char.player'].equipped) {
    await page.getByRole('button', { name: 'Stow weapon', exact: true }).click()
  }
  await expect.poll(async () => (await world()).actors['char.player'].equipped).toBeNull()
  await page.getByRole('button', { name: 'Open Abilities', exact: true }).click()
  await page.getByLabel('Ability', { exact: true }).selectOption('ability.light@1')
  await expect(page.getByRole('region', { name: 'Character abilities' })).toContainText('Duration 2 hours')
  await page.getByLabel('Ability targets', { exact: true }).getByRole('button', { name: 'Brass lantern', exact: true }).click()
  const before = await world()
  await page.getByRole('button', { name: 'Use ability', exact: true }).click()
  await expect.poll(async () => (await world()).items['item.lantern'].light?.source).toBe('char.player')
  const after = await world()
  assert.equal(after.items['item.lantern'].light.ends_at - before.tick, 1200)
  report.assertions.push('Class and ability controls work in the external panel bundle',
    'The panel displays the published two-hour duration', 'Casting produces that duration in canonical state')
  report.light = after.items['item.lantern'].light
  await page.screenshot({ path: `${evidence}/release-light.png` })
  assert.deepEqual(report.errors, [])
} catch (error) {
  report.failure = error.message
  await page.screenshot({ path: `${evidence}/release-light-failed.png` }).catch(() => {})
  throw error
} finally {
  await writeFile(`${evidence}/release-report.json`, JSON.stringify(report, null, 2) + '\n')
  await browser.close()
}
