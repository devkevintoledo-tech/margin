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

// Opens the first work returned by a search and waits for the work detail page.
// Depends on the live Google Books and Open Library integrations; pass a broad,
// popular query. If Open Library is slow the heuristic tier still groups the
// results, so nothing here may depend on a work's edition_count.
export async function openFirstSearchResult(page, query = 'dune') {
  await page.goto(`/search?q=${encodeURIComponent(query)}`)
  const firstWork = page.locator('a[href^="/works/"]').first()
  await firstWork.click()
  await expect(page).toHaveURL(/\/works\//)
}
