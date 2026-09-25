import { test, expect } from '@playwright/test'
import { registerViaUi, openFirstSearchResult } from './helpers'

// "Writing threads": create a discussion thread on a work page.
// Depends on the live search to surface a work, so it needs the
// full stack up and network access. test-engineer can swap the search step for
// a seeded work to make this fully deterministic.
test.describe('threads', () => {
  test('create a thread on a work page', async ({ page }) => {
    await registerViaUi(page)
    await openFirstSearchResult(page, 'dune')

    await page.getByRole('button', { name: 'Start a Thread' }).click()

    const title = `Thread ${Date.now()}`
    await page.getByPlaceholder('Thread title').fill(title)
    await page.getByPlaceholder('Opening post (optional)').fill('Kicking off the discussion.')
    await page.getByRole('button', { name: 'Create Thread' }).click()

    // Lands on the new thread page showing the title and the opening post.
    await expect(page).toHaveURL(/\/threads\//)
    await expect(page.getByText(title)).toBeVisible()
    await expect(page.getByText('Kicking off the discussion.')).toBeVisible()
  })
})
