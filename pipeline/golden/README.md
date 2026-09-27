# Golden set

`series.yaml` lists widely read series with their expected members (OL work
ids) in reading order. `publish` refuses to write a release unless at least
95% of entries have exactly the expected membership and 95% exactly the
expected order.

## Adding an entry

1. Run a build to at least `extract` (`python -m pipeline run --to extract`).
2. For a series Wikidata knows, draft it: `python -m pipeline golden-draft Q45875`.
   The draft comes from Wikidata's own ordinals, never from the pipeline's
   grouping — a golden set drawn from the output would only test itself.
3. Verify every member and the order against an outside source (the author's
   or publisher's series list, or the Wikipedia series article). Fix ids from
   <https://openlibrary.org/search?q=…>. Record the source in `verified_by`.
4. For a series Wikidata does not know, write the entry by hand the same way.

```yaml
- name: A Song of Ice and Fire
  verified_by: "https://georgerrmartin.com/… (checked 2026-10-02)"
  members: [OL257943W, OL257945W, OL257944W, OL2617213W, OL8479867W]
```

Order is what the series page shows: `position`, then first publication year,
then title. A member missing from the catalog, an extra member, or a wrong
order each fail the entry; the report lists every failure.

## Target coverage (~150 series)

Fantasy: A Song of Ice and Fire · The Lord of the Rings · Harry Potter · The
Wheel of Time · Mistborn · The Stormlight Archive · The Kingkiller Chronicle ·
Discworld · The Chronicles of Narnia · Earthsea · The Witcher · The First Law ·
The Broken Earth · The Dark Tower · Malazan Book of the Fallen · The Farseer
Trilogy · The Liveship Traders · Shadow and Bone · Six of Crows · A Court of
Thorns and Roses · Throne of Glass · Gentleman Bastard · The Poppy War · His
Dark Materials · The Inheritance Cycle · The Sword of Truth · The Belgariad ·
The Dresden Files · Shannara · Dragonlance Chronicles · The Black Company ·
Wayward Children · The Locked Tomb · The Green Bone Saga · Kushiel's Legacy ·
Codex Alera · The Riyria Revelations · The Night Angel Trilogy

Science fiction: Dune · Foundation · The Expanse · Remembrance of Earth's Past
· Red Rising · Hyperion Cantos · Ender's Saga · The Hitchhiker's Guide to the
Galaxy · The Murderbot Diaries · Imperial Radch · Culture · Revelation Space ·
Old Man's War · Wayfarers · Children of Time · Robot series · Rendezvous with
Rama · Vorkosigan Saga · Honor Harrington · The Interdependency · Bobiverse ·
Silo · The Space Trilogy · Xenogenesis · Commonwealth Saga

Young adult and children's: The Hunger Games · Divergent · The Maze Runner ·
Percy Jackson and the Olympians · The Heroes of Olympus · The Kane Chronicles ·
Twilight · The Mortal Instruments · A Series of Unfortunate Events · Diary of
a Wimpy Kid · The Chronicles of Prydain · Artemis Fowl · Alex Rider · The
Selection · Red Queen · Shatter Me · Miss Peregrine's Peculiar Children ·
Keeper of the Lost Cities · Wings of Fire · Warriors · The Giver Quartet ·
Anne of Green Gables · Little House · Redwall · The Raven Cycle · Lockwood &
Co. · Arc of a Scythe · Uglies · Legend · The 5th Wave · The Illuminae Files ·
Leviathan · The Lunar Chronicles · Graceling Realm

Romance: Bridgerton · Outlander · Fifty Shades · The Kiss Quotient · Off-Campus
· Ice Planet Barbarians · Virgin River · Chicago Stars · Rosemary Beach ·
Crossfire · The Hathaways · Wallflowers · Psy-Changeling · Black Dagger
Brotherhood · Twisted · Beautiful Disaster · After · The Brown Sisters ·
Bromance Book Club · Scoundrels (Loretta Chase)

Mystery and thriller: Jack Reacher · Millennium · Harry Bosch · Alex Cross ·
Hercule Poirot · Miss Marple · Sherlock Holmes · Cormoran Strike · Chief
Inspector Gamache · Harry Hole · Dublin Murder Squad · Robert Langdon · Jason
Bourne · Stephanie Plum · Kinsey Millhone · Lincoln Rhyme · Jack Ryan · Mitch
Rapp · Thursday Murder Club · Dirk Pitt · Kay Scarpetta · Rizzoli & Isles ·
Temperance Brennan · Lord Peter Wimsey · Maigret · Inspector Rebus · Department
Q

Classics and literary: In Search of Lost Time · The Forsyte Saga · The
Alexandria Quartet · Neapolitan Novels · Wolf Hall trilogy · Chronicles of
Barsetshire · Palliser novels · Leatherstocking Tales · Rabbit Angstrom · The
Border Trilogy · Gormenghast · The Raj Quartet · Aubrey–Maturin · Horatio
Hornblower · Poldark · The Cairo Trilogy · A Dance to the Music of Time ·
Earth's Children · The Cazalet Chronicles · Lonesome Dove · The Saxon Stories ·
Sharpe · Kingsbridge · The Century Trilogy
