import { test, expect } from '@playwright/test'
import { registerViaUi, openFirstSearchResult } from './helpers'

// An author edits a reply, deletes the post above it (the reply survives under
// a tombstone), then deletes the thread and lands back in its room. Uses live
// search like thread.spec and reply.spec, so it needs the full stack.
test.describe('editing and deleting', () => {
  test('edit a reply, delete a post, delete the thread', async ({ page }) => {
    await registerViaUi(page)
    await openFirstSearchResult(page, 'dune')

    const title = `Edit target ${Date.now()}`
    await page.getByRole('button', { name: 'Start a Thread' }).click()
    await page.getByPlaceholder('Thread title').fill(title)
    await page.getByRole('button', { name: 'Create Thread' }).click()
    await expect(page).toHaveURL(/\/threads\//)

    const parent = `Parent ${Date.now()}`
    await page.getByPlaceholder('Join the discussion...').fill(parent)
    await page.getByRole('button', { name: 'Post' }).click()
    await expect(page.getByText(parent)).toBeVisible()

    await page.getByRole('button', { name: 'reply' }).first().click()
    const reply = `Reply ${Date.now()}`
    await page.getByPlaceholder('Write a reply...').fill(reply)
    await page.getByRole('button', { name: 'Post' }).first().click()
    // Scoped to the tree: until the post lands, the composer's textarea still
    // holds the same text, and getByText matches it.
    await expect(page.getByRole('listitem').getByText(reply)).toBeVisible()

    // The reply's actions come after its parent's in document order.
    await page.getByRole('button', { name: 'edit' }).last().click()
    const fixed = `${reply} (fixed)`
    await page.getByLabel('Edit post').fill(fixed)
    await page.getByRole('button', { name: 'save' }).click()
    await expect(page.getByText(fixed)).toBeVisible()
    await expect(page.getByText('edited', { exact: true })).toBeVisible()

    await page.getByRole('button', { name: 'delete', exact: true }).first().click()
    await page.getByRole('button', { name: 'yes, delete post' }).click()
    await expect(page.getByText(parent)).toHaveCount(0)
    await expect(page.getByText('[deleted]').first()).toBeVisible()
    await expect(page.getByText(fixed)).toBeVisible()

    await page.getByRole('button', { name: 'delete thread' }).click()
    await page.getByRole('button', { name: 'yes, delete thread' }).click()
    await expect(page).toHaveURL(/\/series\/[^/]+$/)
    await expect(page.getByText(title)).toHaveCount(0)
  })
})
