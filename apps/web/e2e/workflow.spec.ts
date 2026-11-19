import { expect, test } from '@playwright/test'

// Runs against a live stack seeded with `python -m app.cli seed-demo`.
test('inspect, investigate, trace and check the pipeline monitor', async ({ page }) => {
  await page.goto('/inspect')
  await page.getByLabel('Result').selectOption('out_of_tolerance')
  const first = page.getByRole('listbox', { name: 'Inspections' }).getByRole('option').first()
  await expect(first).toBeVisible()
  await first.click()

  // The measurement result comes from the API and the overlay is drawn.
  await expect(page.getByText('Over USL').first()).toBeVisible()
  await expect(page.locator('.ov-dim .dimtext')).toBeVisible({ timeout: 5000 })
  await expect(page.getByRole('img', { name: /Measured \d\.\d{3} mm against specification/ })).toBeVisible()

  // Start or open the investigation for this deviation.
  const open = page.getByRole('link', { name: /Open investigation/ })
  if (await open.count()) await open.click()
  else await page.getByRole('button', { name: 'Start investigation' }).click()
  await expect(page).toHaveURL(/\/investigations\/\d+/)
  await expect(page.getByRole('heading', { name: 'Ranked candidate contributors' })).toBeVisible()
  await expect(page.getByText('Limitations of this analysis')).toBeVisible()

  // Navigate to traceability for the trigger unit.
  const serial = (await page.locator('.inv-head .fig-v a').first().textContent())!.trim()
  await page.getByRole('link', { name: serial }).first().click()
  await page.getByRole('link', { name: 'Trace unit' }).click()
  await expect(page.getByRole('heading', { name: 'Process route' })).toBeVisible()
  await expect(page.getByText(serial).first()).toBeVisible()

  // Pipeline monitor lists real executions, including the deliberately corrupted delivery.
  await page.getByRole('link', { name: 'Pipelines' }).click()
  await expect(page.getByRole('heading', { name: 'Executions' })).toBeVisible()
  await expect(page.getByText('checksum mismatch').first()).toBeVisible()
})

test('analytics points open their inspection', async ({ page }) => {
  await page.goto('/analytics?location=FD-FF-M')
  await expect(page.getByText('First signal')).toBeVisible()
  await expect(page.getByRole('img', { name: /Individuals control chart/ })).toBeVisible()
})
