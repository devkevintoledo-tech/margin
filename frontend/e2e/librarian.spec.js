import { test, expect } from '@playwright/test'
import { ensureEditMode, grantLibrarian, moveFirstResultInto, openFirstSearchResult, registerViaUi } from './helpers'

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
  await page.getByLabel('Find a series', { exact: true }).fill(saga)
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
  await page.getByLabel('Find a series', { exact: true }).fill(saga)
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

// A librarian builds a one-book series, then adds a second book from the
// series header. Needs the full stack and live Open Library.
test('a librarian adds a book from the series page and undoes it', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload()

  const saga = `E2E Add ${Date.now()}`
  await moveFirstResultInto(page, 'the left hand of darkness', saga, { create: true })
  await ensureEditMode(page)

  await page.getByRole('button', { name: 'add a book' }).click()
  await page.getByLabel('Find the book to add', { exact: true }).fill('the dispossessed')
  const hit = page.getByRole('radio', { name: /Dispossessed/ }).first()
  await hit.check()
  await page.getByLabel('Reason', { exact: true }).fill('e2e: checking add a book')
  await page.getByRole('button', { name: 'Add book' }).click()

  const status = page.getByRole('group', { name: 'Librarian fix result' })
  await expect(status).toBeVisible()
  const books = page.getByRole('list', { name: 'Books in this series' })
  await expect(books.getByRole('heading', { level: 3, name: /Dispossessed/ })).toBeVisible()

  await status.getByRole('button', { name: 'undo' }).click()
  await expect(status.getByText('undone')).toBeVisible()
  await expect(books.getByRole('heading', { level: 3, name: /Dispossessed/ })).toHaveCount(0)
})

// A librarian opens a merge from a series row, sees both books side by side,
// swaps which survives, and backs out. Never confirms: a merge is permanent.
test('a librarian previews a merge side by side and swaps the survivor', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload()

  await openFirstSearchResult(page, 'dune')
  await ensureEditMode(page)
  const books = page.getByRole('list', { name: 'Books in this series' })
  const title = await books.getByRole('heading').first().textContent()
  await books.getByRole('button', { name: `merge into… ${title}`, exact: true }).click()

  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Find the book to keep', { exact: true }).fill('dune messiah')
  await dialog.getByRole('radio').first().check()
  const preview = dialog.getByRole('group', { name: 'Merge preview' })
  await expect(preview.getByRole('region', { name: `merges away: ${title}` })).toBeVisible()

  await preview.getByRole('button', { name: 'swap which book survives' }).click()
  await expect(preview.getByRole('region', { name: `survives: ${title}` })).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})

// A librarian checks two search results, opens merge…, sees both side by
// side with the first merging into the second, swaps, and backs out.
test('a librarian selects two search results and previews their merge', async ({ page }) => {
  const user = await registerViaUi(page)
  grantLibrarian(user)
  await page.reload()

  await page.goto('/search?q=dune')
  await page.getByRole('button', { name: 'select', exact: true }).click()
  const boxes = page.getByRole('checkbox', { name: /^select / })
  await expect(boxes.nth(1)).toBeVisible()
  await boxes.nth(0).check()
  await boxes.nth(1).check()
  await expect(page).toHaveURL(/\/search\?q=dune$/) // selecting did not navigate
  await expect(page.getByRole('status').filter({ hasText: 'selected' })).toHaveText('2 selected')

  await page.getByRole('button', { name: 'merge…' }).click()
  const dialog = page.getByRole('dialog')
  const preview = dialog.getByRole('group', { name: 'Merge preview' })
  const away = preview.getByRole('region', { name: /^merges away: / })
  await expect(away).toBeVisible()
  const awayName = await away.getAttribute('aria-label')

  await preview.getByRole('button', { name: 'swap which book survives' }).click()
  await expect(preview.getByRole('region', { name: awayName.replace('merges away', 'survives') })).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(boxes.nth(0)).toBeChecked() // backing out keeps the picks
})
