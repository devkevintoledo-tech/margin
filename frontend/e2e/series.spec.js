import { test, expect } from '@playwright/test'
import { registerViaUi } from './helpers'

// Search → series page → a thread tagged to book two shows under book two's
// filter and not book three's. Uses live Open Library (Red Rising carries
// `franchise:Red Rising`), so it needs the full stack and network.
test('a thread tagged to one book of a series filters by that book', async ({ page }) => {
  await registerViaUi(page)
  await page.goto('/search?q=red%20rising')
  await page.locator('a[href^="/series/red-rising"]').first().click()
  await expect(page).toHaveURL(/\/series\/red-rising/)

  const books = page.getByRole('list', { name: 'Books in this series' })
  await expect(books.getByRole('heading', { name: 'Golden Son' })).toBeVisible({ timeout: 30_000 })

  await page.getByRole('button', { name: 'Start a Thread' }).click()
  const title = `Golden Son thread ${Date.now()}`
  await page.getByPlaceholder('Thread title').fill(title)
  await page.getByLabel('About which book').selectOption({ label: 'Golden Son' })
  await page.getByRole('button', { name: 'Create Thread' }).click()
  await expect(page).toHaveURL(/\/series\/red-rising\/threads\//)
  // The URL changes before the lazily loaded thread page renders; going back
  // before it does would return to the still-mounted page with its modal open.
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()

  await page.goBack()
  const filters = page.getByRole('group', { name: 'Filter by book' })
  await filters.getByRole('button', { name: 'Golden Son' }).click()
  await expect(page.getByRole('link', { name: title })).toBeVisible()
  await filters.getByRole('button', { name: 'Morning Star' }).click()
  await expect(page.getByRole('link', { name: title })).toHaveCount(0)
})
