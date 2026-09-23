import { test, expect } from '@playwright/test'
import { freshUser, registerViaUi, signedInAs } from './helpers'

// Login / registration is the foundational journey — no external API needed.
test.describe('auth', () => {
  test('register, log out, and log back in', async ({ page }) => {
    const user = await registerViaUi(page)

    // Logged in: navbar shows the username and a logout control.
    await expect(signedInAs(page, user)).toBeVisible()
    await page.getByRole('button', { name: 'Out' }).click()
    await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible()

    // Log back in with the same credentials.
    await page.goto('/login')
    await page.getByRole('textbox').first().fill(user.email)
    await page.locator('input[type="password"]').fill(user.password)
    await page.getByRole('button', { name: /sign in/i }).click()
    await expect(signedInAs(page, user)).toBeVisible()
  })

  test('rejects a wrong password', async ({ page }) => {
    const user = freshUser()
    await registerViaUi(page, user)
    await page.getByRole('button', { name: 'Out' }).click()

    await page.goto('/login')
    await page.getByRole('textbox').first().fill(user.email)
    await page.locator('input[type="password"]').fill('definitely-wrong')
    await page.getByRole('button', { name: /sign in/i }).click()

    // Still signed out — the join CTA remains.
    await expect(page.getByRole('link', { name: 'Join' })).toBeVisible()
  })
})
