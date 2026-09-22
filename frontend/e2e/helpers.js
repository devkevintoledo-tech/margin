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
  await expect(page.getByText(user.username)).toBeVisible()
  return user
}

// Opens the first book returned by a search and waits for the book detail page.
// Depends on the live Open Library integration; pass a broad, popular query.
export async function openFirstSearchResult(page, query = 'dune') {
  await page.goto(`/search?q=${encodeURIComponent(query)}`)
  const firstBook = page.locator('a[href^="/books/"]').first()
  await firstBook.click()
  await expect(page).toHaveURL(/\/books\//)
}
