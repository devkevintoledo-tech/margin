import { test, expect } from '@playwright/test'
import { registerViaUi, openFirstSearchResult } from './helpers'

// "Answering": post a top-level reply in a freshly created thread.
// Like thread.spec, this exercises the live search → work → thread path and
// needs the full stack running.
test.describe('replies', () => {
  test('post a reply in a thread', async ({ page }) => {
    await registerViaUi(page)
    await openFirstSearchResult(page, 'dune')

    // Create a thread to answer in.
    await page.getByRole('button', { name: 'Start a Thread' }).click()
    await page.getByPlaceholder('Thread title').fill(`Reply target ${Date.now()}`)
    await page.getByRole('button', { name: 'Create Thread' }).click()
    await expect(page).toHaveURL(/\/threads\//)

    // The composer at the bottom of the thread posts a top-level message.
    const answer = `My answer ${Date.now()}`
    await page.getByPlaceholder('Join the discussion...').fill(answer)
    await page.getByRole('button', { name: 'Post' }).click()

    await expect(page.getByText(answer)).toBeVisible()
  })
})
