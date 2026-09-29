import { test, expect } from '@playwright/test'
import { grantLibrarian, openFirstSearchResult, registerViaUi } from './helpers'

// A librarian moves a book into a new series, lands on the new room, sees the
// book there, and undoes the move. Needs the full stack and live Open Library.
test('a librarian moves a book into a new series and undoes it', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload() // useMe refreshes the stored user, now a librarian

  await openFirstSearchResult(page, 'the left hand of darkness')
  await page.getByRole('button', { name: '[edit]' }).click()
  const books = page.getByRole('list', { name: 'Books in this series' })
  const title = await books.getByRole('heading').first().textContent()

  await books.getByRole('button', { name: `move ${title}`, exact: true }).click()
  const saga = `E2E Saga ${Date.now()}`
  await page.getByLabel('Find a series').fill(saga)
  await page.getByRole('radio', { name: `new series: ${saga}` }).check()
  await page.getByLabel('Reason', { exact: true }).fill('e2e: checking the move flow')
  await page.getByRole('button', { name: 'Move', exact: true }).click()

  const status = page.getByRole('group', { name: 'Librarian fix result' })
  await expect(status).toBeVisible()
  // A singleton the move emptied redirects to the new room by itself; a book
  // moved out of a real series needs the link.
  const heading = page.getByRole('heading', { level: 1, name: saga })
  const follow = status.getByRole('link', { name: /go to its page/ })
  await expect(async () => {
    if (await follow.isVisible()) await follow.click({ timeout: 1000 }).catch(() => {})
    await expect(heading).toBeVisible({ timeout: 1000 })
  }).toPass()
  await expect(books.getByRole('heading', { name: title })).toBeVisible()

  await status.getByRole('button', { name: 'undo' }).click()
  await expect(status.getByText('undone')).toBeVisible()
})

// Edit mode is sticky: on for the next book, still on after a reload, and
// left from the navbar. Needs the full stack and live Open Library.
test("a librarian's edit mode follows them to the next book", async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload() // useMe refreshes the stored user, now a librarian

  const books = page.getByRole('list', { name: 'Books in this series' })
  const rowMove = books.getByRole('button', { name: /^move / }).first()

  await openFirstSearchResult(page, 'the dispossessed')
  await page.getByRole('button', { name: '[edit]' }).click()
  await expect(rowMove).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: 'EDIT' })).toBeVisible()

  await openFirstSearchResult(page, 'a wizard of earthsea') // a full navigation
  await expect(rowMove).toBeVisible()
  await page.reload()
  await expect(rowMove).toBeVisible()

  await page.getByRole('button', { name: '[done editing]' }).click()
  await expect(books.getByRole('button', { name: /^move / })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '[edit]' })).toBeVisible()
})

// A preset reason is one click, lands in the log as its text, and the fix
// undoes from the log. Needs the full stack and live Open Library.
test('a librarian gives a reason with one click', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload() // useMe refreshes the stored user, now a librarian

  await openFirstSearchResult(page, 'the lathe of heaven')
  await page.getByRole('button', { name: '[edit]' }).click()
  const books = page.getByRole('list', { name: 'Books in this series' })
  const title = await books.getByRole('heading').first().textContent()

  await books.getByRole('button', { name: `move ${title}`, exact: true }).click()
  const saga = `E2E Reasons ${Date.now()}`
  await page.getByLabel('Find a series').fill(saga)
  await page.getByRole('radio', { name: `new series: ${saga}` }).check()
  const chip = page.getByRole('group', { name: 'Quick reasons' }).getByRole('button', { name: 'belongs to this series' })
  await chip.click()
  await expect(chip).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByLabel('Reason', { exact: true })).toHaveValue('belongs to this series')
  await page.getByRole('button', { name: 'Move', exact: true }).click()
  await expect(page.getByRole('group', { name: 'Librarian fix result' })).toBeVisible()

  await page.goto('/librarian')
  const table = page.getByRole('table', { name: 'Catalog fixes' })
  await expect(table.getByText('belongs to this series').first()).toBeVisible()
  await table.getByRole('button', { name: `undo ${title}` }).first().click()
  await expect(table.getByText('undone').first()).toBeVisible()
})
