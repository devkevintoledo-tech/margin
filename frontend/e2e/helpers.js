import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { expect } from '@playwright/test'

// Unique-per-run identity so reruns never collide on the unique email/username.
export function freshUser() {
  const tag = `${Date.now()}${Math.floor(Math.random() * 1000)}`
  return {
    email: `e2e_${tag}@example.com`,
    username: `e2e_${tag}`,
    password: 'e2e-password-123',
  }
}

// Registers a new account through the UI and lands authenticated on the home
// page (the navbar then shows the username). Returns the created user.
export async function registerViaUi(page, user = freshUser()) {
  await page.goto('/register')
  await page.getByRole('textbox').first().fill(user.email) // email
  await page.locator('input[type="text"]').fill(user.username)
  const passwordFields = page.locator('input[type="password"]')
  await passwordFields.nth(0).fill(user.password) // password
  await passwordFields.nth(1).fill(user.password) // confirm password
  await page.getByRole('button', { name: /create account/i }).click()
  await expect(signedInAs(page, user)).toBeVisible()
  return user
}

// The navbar's profile link is the signed-in signal. Matching the bare username
// text is ambiguous: the pinned status bar shows it too.
export function signedInAs(page, user) {
  return page.locator(`a[href="/profile/${user.username}"]`)
}

// Opens the first work returned by a search and waits for the book's series page.
// Depends on the live Google Books and Open Library integrations; pass a broad,
// popular query. If Open Library is slow the heuristic tier still groups the
// results, so nothing here may depend on a work's edition_count.
export async function openFirstSearchResult(page, query = 'dune') {
  await page.goto(`/search?q=${encodeURIComponent(query)}`)
  const firstWork = page.locator('a[href^="/series/"]').first()
  await firstWork.click()
  await expect(page).toHaveURL(/\/series\//)
}

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')

// Librarians are granted from a shell (spec §3); e2e does the same through compose.
export function grantLibrarian(user) {
  execSync(`docker compose exec -T backend python -m scripts.grant_librarian ${user.username}`, {
    cwd: REPO, stdio: 'pipe',
  })
}

// Edit mode is sticky after roadmap item 01 and per-URL before it: click
// [edit] only when the page is not already in edit mode.
export async function ensureEditMode(page) {
  const done = page.getByRole('button', { name: '[done]' })
  if (!(await done.isVisible())) await page.getByRole('button', { name: '[edit]' }).click()
  await expect(done).toBeVisible()
}

// Opens the first search result for `query` and moves its first book into
// `saga`. `create` names a new series; otherwise `saga` must already exist.
// Leaves the page on the saga's series page. Returns the moved book's title.
export async function moveFirstResultInto(page, query, saga, { create = false, position } = {}) {
  await openFirstSearchResult(page, query)
  await ensureEditMode(page)
  const books = page.getByRole('list', { name: 'Books in this series' })
  const title = (await books.getByRole('heading', { level: 3 }).first().textContent()).trim()
  await books.getByRole('button', { name: `move ${title}`, exact: true }).click()
  await page.getByLabel('Find a series', { exact: true }).fill(saga)
  const radio = create
    ? page.getByRole('radio', { name: `new series: ${saga}` })
    : page.getByRole('radio', { name: new RegExp(`^${saga}`) })
  await radio.check()
  if (position != null) await page.getByLabel('Position (optional)').fill(String(position))
  await page.getByLabel('Reason', { exact: true }).fill('e2e: building a series')
  await page.getByRole('button', { name: 'Move', exact: true }).click()
  const status = page.getByRole('group', { name: 'Librarian fix result' })
  await expect(status).toBeVisible()
  // A singleton the move emptied redirects by itself; a book moved out of a
  // real series needs the link.
  const heading = page.getByRole('heading', { level: 1, name: saga })
  const follow = status.getByRole('link', { name: /go to its page/ })
  await expect(async () => {
    if (await follow.isVisible()) await follow.click({ timeout: 1000 }).catch(() => {})
    await expect(heading).toBeVisible({ timeout: 1000 })
  }).toPass()
  return title
}
