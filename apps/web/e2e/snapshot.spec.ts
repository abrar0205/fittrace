import { expect, test } from '@playwright/test'

declare const process: { env: Record<string, string | undefined> }

// Only for the static GitHub Pages build (E2E_SNAPSHOT=1).
test.skip(!process.env.E2E_SNAPSHOT, 'snapshot build only')

test('snapshot: deep links, provenance and read-only actions', async ({ page }) => {
  await page.goto('investigations')
  await expect(page.getByRole('heading', { name: 'Investigation records' })).toBeVisible()
  await page.getByRole('row').nth(1).click()
  await expect(page.getByRole('heading', { name: 'Corrective-action verification' })).toBeVisible()
  // Precomputed verification results are shown; starting a new run is disabled.
  await expect(page.getByText('Paired change, 95% CI')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Run simulated verification' })).toBeDisabled()

  // A deep link served through the 404 fallback still renders the workbench with its image.
  await page.goto('inspect/701')
  await expect(page.locator('.ov-dim .dimtext')).toBeVisible({ timeout: 8000 })
  await expect(page.getByRole('button', { name: 'Run measurement' })).toBeDisabled()
  await page.getByRole('button', { name: 'Compare with generator ground truth' }).click()
  await expect(page.getByText('True gap')).toBeVisible()

  await page.goto('')
  await expect(page.getByText(/static snapshot: every measurement/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Line map' })).toBeVisible()
  await page.getByRole('button', { name: /^FX-202:/ }).click()
  await expect(page).toHaveURL(/analytics\?location=FD-FF-M&station=S20/)
  await expect(page.getByRole('img', { name: /Gap distribution by equipment at S20/ })).toBeVisible()
})
