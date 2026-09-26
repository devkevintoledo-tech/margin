import { expect, test } from '@playwright/test'

// Runs against the live stack and the real Open Library, so a cold database
// exercises the ingest path; a warm one exercises the local index. Both must
// produce the same first result.
test.describe('search relevance and covers', () => {
  test('puts the canonical work first and gives every result a cover', async ({ page }) => {
    await page.goto('/search?q=red%20rising')

    const results = page.locator('a[href^="/series/"]')
    await expect(results.first()).toBeVisible({ timeout: 30_000 })

    await expect(results.first()).toContainText('Red Rising')
    // Case-insensitive: the tile lowercases the author in CSS, so the DOM
    // still carries "Pierce Brown".
    await expect(results.first()).toContainText(/pierce brown/i)

    // Covers are loading="lazy", so an off-screen one is never fetched and
    // reports naturalWidth 0. Scroll the whole list through the viewport and
    // let every image settle before judging any of it.
    await page.evaluate(async () => {
      for (let y = 0; y < document.body.scrollHeight; y += window.innerHeight) {
        window.scrollTo(0, y)
        await new Promise((resolve) => setTimeout(resolve, 100))
      }
    })

    const images = results.locator('img')
    await expect
      .poll(() => images.evaluateAll((els) => els.every((img) => img.complete)), {
        timeout: 15_000,
      })
      .toBe(true)

    // Every result shows real art or the serif-title fallback, which removes
    // the img entirely — never a broken image, and never Google's "image not
    // available" placeholder, a fixed 128x174 asset. A bare width floor would
    // be wrong here: Open Library serves genuinely small covers for thin
    // scans (128x190 for "Dragon rises, red bird flies"), so only the
    // placeholder's exact geometry identifies it.
    const sizes = await images.evaluateAll((els) =>
      els.map((img) => [img.naturalWidth, img.naturalHeight]),
    )
    for (const [width, height] of sizes) {
      expect(width).toBeGreaterThan(0)
      expect(`${width}x${height}`).not.toBe('128x174')
    }
  })

  test('is fast on a repeat query, because it never leaves the database', async ({ page }) => {
    await page.goto('/search?q=red%20rising')
    await expect(page.locator('a[href^="/series/"]').first()).toBeVisible({ timeout: 30_000 })

    const started = Date.now()
    await page.goto('/search?q=red%20rising')
    await expect(page.locator('a[href^="/series/"]').first()).toBeVisible()
    expect(Date.now() - started).toBeLessThan(2_000)
  })
})
