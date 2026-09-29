import { test, expect } from '@playwright/test'
import { registerViaUi } from './helpers'

// A reader tags Red Rising as space opera and finds it by that genre, on the
// genre page and through the search filter. Uses live Open Library for the
// first search; needs the full stack with the taxonomy synced (compose runs
// `scripts.sync_genres` on start).
test('a reader tags a book and finds it by that genre', async ({ page }) => {
  await registerViaUi(page)
  await page.goto('/search?q=red%20rising')
  await page.locator('a[href^="/series/red-rising"]').first().click()

  const books = page.getByRole('list', { name: 'Books in this series' })
  const row = books.getByRole('listitem').filter({ has: page.getByRole('heading', { name: 'Red Rising', exact: true }) })
  await expect(row).toBeVisible({ timeout: 30_000 })

  await row.getByRole('button', { name: 'tag genres of Red Rising' }).click()
  await page.getByRole('combobox', { name: 'filter genres' }).fill('space opera')
  await page.getByRole('option', { name: 'space-opera' }).click()
  await page.getByRole('button', { name: '[done]' }).click()
  await expect(row.getByRole('link', { name: 'space-opera' })).toBeVisible()
  await expect(row.getByText('you tagged this')).toBeAttached()

  await page.goto('/genres/space-opera')
  await expect(page.getByText('Red Rising', { exact: true }).first()).toBeVisible()

  await page.goto('/search?genre=space-opera')
  await expect(page.locator('a[href^="/series/red-rising"]').first()).toBeVisible()
})
