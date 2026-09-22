# Visual Identity — Decision Record

**Date:** 2026-09-22
**Source brief:** [`new-instructions.md`](./new-instructions.md) (sections referenced below as §N)
**Status:** Tier 1 implemented. Tiers 2–4 recorded, not built.

The brief describes the product the code was already heading toward: dark,
sharp-cornered, hairline-bordered, editorial. This record says what was adopted,
what was deferred, what was rejected, and why — so the next person doesn't
re-litigate it from the brief alone.

---

## 1. Decisions

| Question | Decision | Rationale |
| --- | --- | --- |
| Accent color (§5 left it `[CHOOSE]`) | **Cobalt blue** | Every book site is warm/beige. Cobalt reads "community/tech platform, not bookstore" and matches §4's gaming reference. Retires the previous burnt amber, which was muddy against `#0D0D0D`. |
| Star ratings & reviews (§12, §14) | **Rejected** | Directly contradicts `margin_spec.md` ("No inflated reviews"; ratings listed out of scope for v1) and the homepage hero ("No star ratings. No sanitized reviews."). Discussion is the differentiator; a rating system moves the product toward Goodreads. Google's `Book.average_rating` is likewise not surfaced. |
| Serif (§6 proposed Bree Serif) | **Playfair Display retained** | Bree is a rounded, friendly slab — it reads *cozier* than Playfair, fighting §3's explicit "should NOT feel cozy". Playfair is already loaded, high-contrast, and magazine-like. |
| UI sans (§6) | **Space Grotesk adopted** | Replaces Inter. Geometric and slightly technical — carries most of the new identity at zero structural cost. |
| Product name (§8, §32) | **Renamed to MARGIN** | Applied across code, infra, DB, specs and agent definitions. Wordmark is `MARGIN//`. |

### Typographic rule

**Serif is reserved for works.** Book titles and thread titles are Playfair.
Everything structural — navigation, section headings, genre names, metadata,
buttons, page headlines — is Space Grotesk. This is what keeps the serif from
becoming decoration.

### Color rules

Tokens live in `frontend/src/index.css` (`:root`) and are mapped to semantic
Tailwind utilities in `frontend/tailwind.config.js`. Contrast is measured
against `bg` `#0D0D0D`:

| Token | Hex | Contrast | Use |
| --- | --- | --- | --- |
| `accent` | `#2B5FE3` | 3.6:1 | Fills, rules, focus borders. White text on it passes 5.5:1. |
| `accent-hover` | `#3A6DF0` | — | Fill hover only. White text 4.5:1. |
| `accent-ink` | `#6E9BFF` | 7.2:1 | Accent-colored **text** on dark. **Never a fill.** |
| `ink` | `#E8E5DF` | 14.5:1 | Body and headline copy. |
| `ink-dim` | `#96928C` | 6.3:1 | Secondary copy, descriptions. |
| `ink-muted` | `#66635F` | 3.3:1 | **Decorative/non-essential text only** — never body copy. |

The three-blue split exists because a single cobalt can't be both a legible fill
and legible text on near-black. Using `accent` as text, or `accent-ink` as a
fill, breaks AA.

---

## 2. What was adopted (Tier 1 — built)

- **§5 Dark-first palette as named tokens.** Previously one token (`accent`) and
  raw `zinc-*` classes across ~25 files. Now every color is semantic.
- **§6 Space Grotesk + large editorial headlines.** New `display-sm/display/display-lg`
  type scale; hero and page headings now use it.
- **§7 Dense but organized.** Kept the existing zero-radius, hairline-border,
  shared-grid approach. Cards remain the exception, not the default.
- **§13 Large covers.** Book page cover up from `w-44` to `w-56`; cover grids
  react on the frame, never by dimming the art.
- **§24 Voting de-emphasized.** Extracted `VoteControl` (`rail` + `inline`
  variants) from duplicated markup in `Post` and `ThreadCard`.
- **§25 Component vocabulary.** `.btn-primary`, `.btn-secondary`, `.btn-ghost`,
  `.input`, `.label`, `.panel`, `.eyebrow`, `.rule`, `.alert-*` in an
  `@layer components` block; new `AuthLayout` shares the four credential screens.
- **§26 Fast, subtle motion.** `duration-fast` (120ms) / `duration-base` (180ms)
  tokens; nothing longer.
- **§29/§30/§36 Anti-patterns and design tests.** Folded into `CLAUDE.md` so they
  bind future work rather than sitting in a doc nothing reads.

Incidental fixes made along the way: `PostComposer`, `Book` and `Genre` now use
`errorMessage()` instead of hand-reading `error.response.data.message` (a
`CLAUDE.md` convention they were violating), and three `<a href>` in-app links
became `<Link>`.

---

## 3. Deferred — needs backend that doesn't exist (Tier 2)

These are product features, not styling. Tracked in `ROADMAP.md`.

| § | Item | Blocker |
| --- | --- | --- |
| 8 | Primary nav (Home / Discover / Communities / Library) | Only Home and Search exist as routes. Dead nav links were deliberately not added. |
| 9, 18 | Homepage & discovery sections (trending, rising, recommended) | No trending or recommendation endpoints. *Roadmap Phase 3.* |
| 10 | Post types (polls, essays, quotes) | `Post.content` is plain text with no type discriminator. |
| 11 | **Takes** | Fully greenfield: new model, endpoints, feed. The strongest idea in the brief and the clearest differentiator vs. Goodreads/Letterboxd — deserves its own design pass. |
| 15 | Reading progress, Paused/DNF | `Shelf` has a 3-value status enum and no progress column. `Book.page_count` already exists, so the math is free. *Roadmap Phase 4.* |
| 16 | Spoilers | *Roadmap Phase 4; explicitly out of scope for v1 in the spec.* |
| 17 | Communities (join, member counts, Hot/New/Top) | `genres` are seed-only, non-joinable, single-FK. Closest existing concept, biggest gap. |
| 19 | Themes/moods taxonomy | Schema-significant: `Book.genre_id` is a single nullable FK; moods need many-to-many. |
| 21, 22 | Profile as taste identity | Visual treatment landed (real shelf counts). Taste bars and "most discussed" need aggregate queries. |
| 23 | Follows, notifications, activity feed | *Roadmap Phase 2.* Note "follow authors" is harder than it looks — `author` is a `String(500)` on `Book`, there is no author entity. |
| 24 | Downvotes / vote toggling | `upvotes` is an increment-only `Integer`. Needs a `votes` table. *Roadmap Phase 1.* |
| 27 | Mobile bottom nav, horizontal shelves | Depends on §8 nav existing first. |
| 28 | Search across users/communities/discussions | Search is Google Books only. *Roadmap Phase 3 (Postgres FTS).* |

---

## 4. Not actionable (Tier 4)

- **§33 Initial MVP** — describes work already shipped (auth, book search, book
  pages, shelves, posts, comments, profiles). Aimed at a greenfield project.
- **§34 Future features** — overlaps `ROADMAP.md` Phases 2–6.
- **§35 "even mock data should look realistic"** — non-issue; data is live Google
  Books. Applies only to empty-state copy.
- **§2/§3/§31** — positioning, not instructions.

---

## 5. Open questions the brief left unresolved

The brief carries five `TODO`s. Three are now answered above (accent, name,
serif). Two remain and are **not** decided here:

1. **§11** — the Takes interaction model (AGREE/DISAGREE vs. up/down voting).
2. **§14** — the review reaction system. Moot while §14 is rejected; revisit only
   if the no-ratings decision is reversed.
