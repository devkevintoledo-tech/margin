# 2. Target Audience

Primary audience:

* Adult readers
* People who participate in online communities
* Readers who enjoy discussing and debating books
* Readers interested in fiction and nonfiction
* People who use Reddit, Letterboxd, Discord, forums, etc.
* People who care about having a recognizable reading identity

The visual design should **lean masculine without explicitly excluding anyone**.

Do NOT create a stereotypical "men's book site."

Instead, achieve a male-leaning aesthetic through:

* Darker colors
* Strong typography
* Editorial layouts
* High contrast
* Minimal decoration
* Technical precision
* Dense information
* Dramatic book imagery
* Strong opinions and discussion

---

# 3. Brand Personality

The product should feel:

* Intelligent
* Confident
* Modern
* Slightly underground
* Editorial
* Opinionated
* Mature
* Minimal
* Sophisticated
* Community-driven

It should NOT feel:

* Cozy
* Cute
* Pastel
* Corporate
* Generic SaaS
* Academic/institutional
* Like an online bookstore
* Like Goodreads with a dark theme

The interface should feel like **a community/publication hybrid**.

---

# 4. Visual Direction

## Overall aesthetic

Use a:

> **Dark editorial + community platform + gaming plataform**

design language.

Think:

* Premium magazine
* Reddit community
* Letterboxd
* Modern gaming/tech platform
* Independent literary publication

Avoid:

* Beige paper textures
* Coffee cups
* Leaves
* Plants
* Decorative bookshelves
* Handwritten fonts
* Excessive rounded cards
* Excessive gradients
* "Cozy reading" imagery

---

# 5. Color System

Default theme should be dark.

Suggested starting palette:

```text
Background:       #0D0D0D
Surface:          #151515
Surface Raised:   #1C1C1C
Border:           #292929

Primary Text:     #E8E5DF
Secondary Text:   #96928C
Muted Text:       #66635F

Accent:           [CHOOSE]
Accent Hover:     [CHOOSE]
Success:          [CHOOSE]
Warning:          [CHOOSE]
Danger:           [CHOOSE]
```

The accent color should be distinctive.

Accent colors:
* Cobalt blue
* Amber

# 6. Typography

Typography is a major part of the identity.

Use a strong modern sans-serif for the interface.

font:

* Space Grotesk

For book titles or editorial moments, optionally use a serif:

* Bree Serif

### Typography rules

Large headlines should be confident and editorial.

Example:

> BOOKS WORTH
> FIGHTING ABOUT.

Avoid making everything small and dense like traditional Reddit.

Use large typography to establish hierarchy.

---

# 7. Layout Philosophy

The application should feel **dense but organized**.

Do not make every piece of content into a floating rounded card.

Use:

* Strong grid systems
* Borders
* Dividers
* Large whitespace where appropriate
* Typography
* Editorial columns
* Full-width sections

Cards should be used selectively.

The interface should look good at:

* Desktop
* Tablet
* Mobile

Desktop is the primary experience.

---

# 8. Primary Navigation

Recommended navigation:

```text
Home
Discover
Communities
Library
Profile
```

Additional global actions:

```text
Search
Create
Notifications
User menu
```

Potential desktop header:

```text
MARGIN//

Home    Discover    Communities    Library

                         Search    + Create    Notifications    Avatar
```

**TODO: Replace "MARGIN" with final product name if necessary.**

---

# 9. Home Page

The homepage should NOT simply be:

```text
post
post
post
post
```

Instead, make it feel like a **living publication/community feed**.

Suggested sections:

1. Hero / featured discussion
2. Trending discussions
3. Recent discussions
4. Popular books
5. People to follow
6. Recommended books
7. Recent reading activity

Example hero:

```text
THE BOOKS PEOPLE ARE
ARGUING ABOUT

[Large book cover]

"Is Dune actually overrated?"

1,284 comments
```

The homepage should immediately communicate:

> **People are here talking about books.**

---

# 10. Discussion System

Discussion is one of the most important parts of the product.

Posts can include:

* Questions
* Reviews
* Recommendations
* Opinions
* Essays
* Reading updates
* Book theories
* Comparisons
* Quotes
* News
* Polls

Each post should show:

```text
Community
Author
Time
Title
Content
Book(s) referenced
Votes
Comments
Save
Share
```

Example:

```text
r/scifi

Alex · 3h ago

Dune is much better on the second read.

The first time I focused on the plot.
The second time I realized...

↑ 842     💬 129     🔖 Save
```

---

# 11. "Takes" Feature

Strongly consider making **TAKES** a first-class product feature.

A Take is a short, opinionated statement about a book.

Example:

> "The Hobbit is better than LOTR."

> "Dune gets better every time you reread it."

> "Most 500-page fantasy books should be 300 pages."

> "Audiobooks absolutely count as reading."

Users can respond:

```text
AGREE
DISAGREE
```

or use voting:

```text
↑ 1,284
↓ 742
```

**TODO: Decide final interaction model.**

The goal is to make opinions highly shareable and create conversations.

---

# 12. Book Pages

A book page should be more than metadata.

It should function as the **community hub for that book**.

Example:

```text
[BOOK COVER]

DUNE
Frank Herbert

★★★★½
128k readers

Science Fiction · Politics · Epic

[ + ADD TO LIBRARY ]
[ START READING ]

ABOUT

...

DISCUSSIONS

1,284 discussions

[Discussion]
[Discussion]
[Discussion]

REVIEWS

...

POPULAR TAKES

...
```

Important:

The book itself should be a first-class object throughout the application.

---

# 13. Book Covers

Book covers should be visually important.

Avoid tiny Goodreads-style thumbnails wherever possible.

Use large covers for:

* Featured books
* Book pages
* Recommendations
* Currently reading
* Discovery
* Profiles

Book covers should provide much of the visual color of the application.

Optional enhancement:

Extract dominant colors from book covers and use them subtly for:

* Background glow
* Border
* Accent
* Hover states

Do this subtly.

Do not create rainbow-colored interfaces.

---

# 14. Reviews

Reviews should feel like social posts rather than Amazon reviews.

Example:

```text
Maya                         4.5 ★

The ending completely broke me.

📖 Finished 2 days ago

[Spoiler protected content]

↑ 238     💬 41     🔖
```

Reviews can optionally include reactions:

```text
😭 Emotional
🤯 Mind-blowing
❤️ Loved it
🤔 Thought-provoking
```

**TODO: Finalize review reaction system.**

---

# 15. Reading Progress

Users should be able to track books they are currently reading.

Example:

```text
CURRENTLY READING

The Way of Kings
Brandon Sanderson

██████████████░░░░ 67%

721 / 1,001 pages

[Update Progress]
```

Users should be able to:

* Start reading
* Update progress
* Finish
* Pause
* Abandon / DNF
* Add to TBR

Reading progress can appear in the social feed.

Example:

> Sarah is 67% through *The Way of Kings*

Potentially:

> "Kaladin is finally getting interesting."

---

# 16. Spoilers

Spoilers must be treated as a core product problem.

Potential spoiler states:

```text
[SPOILER]

Click to reveal
```

Posts and comments should optionally contain spoiler tags.

Reading progress can potentially determine what spoiler warnings are shown.

**TODO: Define exact spoiler system.**

---

# 17. Communities

Communities are Reddit-inspired.

Examples:

```text
/books
/fantasy
/scifi
/romance
/horror
/mystery
/history
/philosophy
/biography
```

But the interface should be more modern than Reddit.

Community page:

```text
r/fantasy

128k readers

[Join]

ABOUT

...

HOT
NEW
TOP
```

Posts underneath.

---

# 18. Discovery

Discovery should be more visual than the home feed.

Potential sections:

### Trending Discussions

### Popular Books

### Recommended For You

### Because You Read...

### Rising Books

### Popular Authors

### Communities You May Like

### Recently Discussed

Use large book covers and editorial layouts.

---

# 19. Discovery Categories

Do not restrict discovery to traditional bookstore genres.

Use two layers.

## Genres

```text
Fantasy
Science Fiction
Literary Fiction
Mystery
Crime
Horror
Romance
Historical
Biography
History
Philosophy
Science
Economics
Psychology
Politics
```

## Themes / Moods

```text
Dark
Epic
Weird
Philosophical
Political
Mind-bending
Violent
Emotional
Fast-paced
Slow burn
Unreliable narrator
Big ideas
```

Themes can be particularly useful for recommendations.

---

# 20. Library

The user's library should contain:

```text
Currently Reading
Want to Read
Read
Paused
DNF
```

Potential views:

* Grid
* List
* Cover wall

Users should be able to filter by:

* Genre
* Author
* Rating
* Date read
* Status

---

# 21. Profile

The profile should represent **reader identity**, not just statistics.

Example:

```text
KEVIN

READING

47 books this year

CURRENTLY READING

[cover] [cover] [cover]

FAVORITE GENRES

Fantasy       ███████████████
History       ███████████
Sci-Fi        █████████
Philosophy    ██████

MOST DISCUSSED

01  Dune
02  Blood Meridian
03  The Road

RECENT TAKES

"The sequel is better."

"Everyone should read this."

"10/10 but I'll never read it again."
```

Potential profile information:

* Books read
* Current books
* Favorite genres
* Favorite authors
* Reviews
* Takes
* Discussion history
* Reading streak
* Reading statistics
* Followers
* Following

---

# 22. Taste Identity

A major goal should be helping users communicate:

> **"This is what kind of reader I am."**

Avoid reducing identity to:

> "I read 52 books this year."

Instead communicate:

> "Dark stories. Big ideas. Unreliable narrators."

Potential automatically generated taste profile:

```text
YOUR TASTE

Dark
Epic
Philosophical
Character-driven
Long books
Unreliable narrators
```

This can become an important social feature.

---

# 23. Social Features

Users should be able to:

* Follow users
* Follow communities
* Follow authors
* Follow books
* Comment
* Vote
* Save
* Share
* Mention users
* React
* Post reviews
* Post Takes
* See reading activity

The product should emphasize **conversation over follower counts**.

---

# 24. Voting

Use Reddit-inspired voting but consider making it feel more modern.

Possible:

```text
↑ 842
↓
```

or:

```text
842 ↑
```

Avoid making voting visually dominate every post.

The content should remain the focus.

---

# 25. Components

Create a reusable component system.

Important components:

```text
Header
Sidebar
MobileNav
BookCard
BookCover
BookHero
DiscussionCard
DiscussionList
Post
Comment
CommentThread
VoteControl
TakeCard
ReviewCard
CommunityCard
UserCard
ReadingProgress
LibraryGrid
GenreTag
SpoilerBlock
SearchBar
SearchResults
NotificationItem
ProfileHeader
StatsPanel
```

Components should share consistent spacing, typography, borders, and interaction patterns.

---

# 26. Interaction Design

Animations should be subtle and fast.

Use animation for:

* Hover
* Vote
* Save
* Expand/collapse
* Page transitions
* Modal opening
* Spoiler reveal

Avoid:

* Excessive bouncing
* Excessive parallax
* Long transitions
* Gratuitous animations

The interface should feel **fast**.

---

# 27. Responsive Design

Desktop:

* Multi-column layouts
* Sidebar
* Large book covers
* Dense information

Tablet:

* Reduced sidebar
* Two-column layouts

Mobile:

* Bottom navigation
* Single-column feed
* Horizontal scrolling book shelves
* Large touch targets
* Collapsible metadata

Do not simply shrink the desktop UI.

Design mobile layouts intentionally.

---

# 28. Search

Search should be a major feature.

Search across:

* Books
* Authors
* Users
* Communities
* Discussions

Example:

```text
Search "Dune"

BOOKS

[Dune]
Frank Herbert

[Dune Messiah]
Frank Herbert

COMMUNITIES

r/dune

DISCUSSIONS

"Why does everyone misunderstand Paul?"
```

---

# 29. Things to Avoid

Do NOT make the application look like:

* Goodreads
* Amazon Books
* Pinterest
* A generic SaaS dashboard
* A cozy reading journal
* A pastel social network
* An online bookstore
* A literal Reddit clone

Specifically avoid excessive:

* Beige
* Pastel pink
* Soft illustrations
* Floral imagery
* Rounded-everything cards
* Huge pill buttons
* Excessive shadows
* Generic gradients

---

# 30. Design Principle

When choosing between two design options, prioritize:

1. Strong identity
2. Readability
3. Content
4. Conversation
5. Book discovery
6. User taste
7. Visual polish

Do not sacrifice usability simply to make the product look "cool."

---

# 31. Product Differentiation

The product should ultimately feel like:

> **Reddit for readers, but designed from scratch rather than cosmetically reskinned.**

The key differences should be:

### Reddit

Community-first.

### Goodreads

Library/tracking-first.

### Letterboxd

Taste/review-first.

### This product

**Conversation + taste + discovery + reading identity.**

Books are the shared object connecting all four.

---

# 32. Brand / Naming Direction

Current placeholder:

> **MARGIN**

Potential alternatives:

```text
Margin
Spine
Afterword
The Stack
Dog-Eared
Underlined
The Index
Chapter
Hardcover
Read//
```

The name should feel:

* Short
* Memorable
* Editorial
* Modern
* Not overly "cute"
* Easy to use as a brand

**TODO: Finalize name.**

---

# 33. Initial MVP

Do not build everything at once.

The first version should prioritize:

### Authentication

* Sign up
* Login
* Profile

### Books

* Search books
* Book pages
* Add to library
* Reading status

### Communities

* Browse communities
* Join communities
* Community pages

### Social

* Create posts
* Comment
* Vote
* Save
* Follow users

### Reviews

* Review a book
* Rating
* Review feed

### Discovery

* Trending books
* Trending discussions
* Recommended books

### Library

* Currently reading
* Want to read
* Read

---

# 34. Future Features

Potential future additions:

* Takes
* Reading challenges
* Reading streaks
* Taste matching
* Book clubs
* Group reads
* Reading rooms
* Author AMAs
* Quotes
* Highlighting
* Book annotations
* Audiobook tracking
* Kindle/import integrations
* Goodreads import
* StoryGraph import
* AI recommendations
* Personalized discovery
* Spoiler-aware feeds
* Reading statistics
* User-generated lists

---

# 35. AI Coding Agent Instructions

When implementing this application:

### Prioritize the design system first.

Do not build dozens of pages with inconsistent styling.

First establish:

* Typography
* Colors
* Spacing
* Buttons
* Inputs
* Cards
* Borders
* Navigation
* Book cards
* Post cards
* User avatars
* Tags
* Icons

Then build pages from those components.

### Maintain visual consistency.

Do not introduce random:

* Colors
* Border radii
* Shadows
* Font sizes
* Button styles

Every new component should follow the established design system.

### Prefer CSS/design tokens.

Centralize:

```text
colors
spacing
radius
typography
breakpoints
shadows
transitions
```

### Do not overuse cards.

Use editorial layouts, dividers, whitespace, and typography in addition to cards.

### Make the interface feel intentional.

Avoid placeholder-looking UI.

Even mock data should look realistic.

Use realistic:

* Book titles
* Authors
* Discussion titles
* User names
* Review content
* Community names
* Reading statistics

---

# 36. Final Design Test

Before considering a page complete, ask:

### Does it look like Goodreads?

If yes → redesign it.

### Does it look like a generic SaaS dashboard?

If yes → redesign it.

### Does it look like Reddit with a different color?

If yes → redesign it.

### Does it feel like a modern online publication/community for readers?

If yes → continue.

### Does the book content remain visually important?

If no → redesign it.

### Does the UI communicate personality and taste?

If no → improve it.

### Would someone recognize the product from a screenshot without seeing the logo?

That should eventually be **yes**.

---

# 37. Core Design Statement

The final product should feel like:

> **A dark, editorial, highly social home for people who care about books.**
>
> Not a digital bookshelf.
>
> Not a bookstore.
>
> Not Goodreads 2.0.
>
> **A place to discover books and argue about them.**

