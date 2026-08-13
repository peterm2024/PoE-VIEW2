# Observed behaviour of Path of Exile

This file collects how **the game and GGG's servers behave over time** —
not how the API is shaped (that is [ggg-api.md](ggg-api.md)), and not why
PoE-VIEW2 solves something the way it does (that is
[ARCHITEKTUR.md](../ARCHITEKTUR.md)).

**In English, unlike the rest of the project documentation** (Peter,
2026-08-12). The measurements here are useful to anyone writing against
GGG's API, and the forum post links to this file; German would put a
wall in front of exactly the people it might help.

**Why keep it separate?** Because this class of knowledge ages
differently and is proven differently. You look at a JSON structure once
and you know it. Whether GGG publishes a character's experience
immediately or only on a zone change can only be established by
measuring over hours — and whoever has not measured it is guessing.
Building the XP/h display produced three wrong assumptions in a single
evening, every one of them plausible (§ *Disproven*).

**Rules for entries here:**

1. Observations only. Every entry says **what it was measured against**.
2. What could not be confirmed goes under *Unconfirmed* — not left out,
   or it will be guessed at again next time.
3. What turned out to be wrong goes under *Disproven* and is not
   deleted. A plausible wrong assumption comes back otherwise.
4. Numbers carry a date. Behaviour can change with a league.
5. **Say where it comes from.** Entries marked **[wiki]** are also
   documented publicly and carry a link; the note then says what our own
   numbers add. Everything else we measured because we could not find it
   written down — which is not the same as it not existing.

Measuring tools behind all of this: PoE's own `Client.txt` (zone
changes, trading, identifying), the application log
(`%LOCALAPPDATA%\PoE-VIEW2\logs\poe-view2.log`, carrying one line per
experience publication since 2026-08-11) and the gem XP recording
(ARCHITEKTUR.md §4.35).

---

## 1. When does the API deliver new data?

**The API shows new data essentially only after a zone change.** Asking
more often buys nothing — in a 27-minute window without a zone change
PoE-VIEW2 asked about a hundred times and got something new **once**
(2026-08-10).

Across 91 logged inventory changes (2026-08-07 to -10):

| Distance from the last zone change | Share |
|---|---|
| 0–5 s | 62 % |
| 6–30 s | 1 % |
| 31–120 s | 12 % |
| 2–10 min | 20 % |
| more than 10 min | 5 % |

The late cases are genuine stragglers: the server does publish without a
zone change eventually, but unpredictably (once +26 items after 1803
seconds and 113 requests).

**Experience only appears once a zone is left.** In every case logged so
far, an experience publication landed 1–3 seconds after a zone change.
If you want to know how much experience the current map has produced so
far, the API cannot tell you — outside the game that number does not
exist yet.

**A zone without a gain produces no publication at all.** Going from
hideout into a map does not change the experience, so there is nothing
to report. Practical consequence: every experience publication belongs
to exactly one zone in which something happened — the one just left.

### The Azurite Mine (Delve) is a blind spot

Travelling back to the vendor in Delve produces **no** entry in
`Client.txt`. Measured on 2026-08-10: between 21:21:41 and 21:49:26
there is not a single `You have entered` line for 27 minutes, while
eight vendor events occurred in that time. Anyone using the zone change
as their only trigger is blind there.

The blind spot covers **only the vendor area**, though: a portal within
the mine does write `You have entered Azurite Mine` and triggers
everything downstream (2026-08-11, 22:59:11 — new data 0.3 seconds
later).

### Vendors: neither identifying nor selling publishes reliably

| Event | New data available |
|---|---|
| `N Items identified` | in 2 of 30 cases within seconds, otherwise not |
| `Trade accepted` | never immediately; measured 17 s, 32 s, 57 s or only at the next zone change |

Evaluated across two play sessions (2026-08-10 and -11, 30 events, each
of which demonstrably triggered an immediate request): seven times new
data was there within six seconds — but **five** of those seven fell 2–4
seconds behind a zone change into the hideout, where the zone change is
at least as good an explanation. That leaves two clean cases, both on
2026-08-10 and within six minutes of each other.

That is inside the range GGG's spontaneous late publications produce
anyway (see the distribution table above). **As an effect of identifying
it is not demonstrable.** Peter suspected this first, from observation
(2026-08-12): "I identified my items at the vendor, but they still show
as unidentified — maybe only returning to base triggers it, and what we
have seen so far was coincidence, or a favourable moment."

---

## 2. `Client.txt` as an event source

Merely reading this text file is permitted by GGG (unlike reading the
running client's memory — that would be a ban risk and is out of the
question).

Counted in a real file with 81,639 lines (2026-08-10):

| Line | Count | Meaning |
|---|---|---|
| `: You have entered <zone>.` | 3829 | zone change |
| `: Trade accepted.` | 1028 | selling to an NPC **and** player trading |
| `: N Items identified` | 821 | plural |
| `: 1 Item identified` | 78 | its own spelling, easy to miss |
| `: Trade cancelled.` | 60 | nothing changed |
| `: You have killed N.N monsters.` | 204 | |
| `: You have received an Atlas Skill Point.` | 146 | |
| `: <character> (<class>) is now level N` | several | level up |
| `: Reached level N in H:MM:SS` | 73 | with play time |
| `: You have received a Passive Skill Point.` | 41 | |
| `: Your Stash Tab with the Unique Affinity does not have enough space for this item.` | 31 | |
| `: Item on cursor destroyed.` | 27 | |

Format of a line:
`2026/08/01 21:44:37 15181671 cffb0658 [INFO Client 18604] : You have entered The Coast.`

Not in the file: anything about experience points below a level up,
loot, currency, or the contents of the stash.

---

## 3. Character experience

- `character.experience` is the **cumulative total**, not the progress
  within the current level. Observed magnitudes: level 87 ≈ 1.63
  billion, level 89 ≈ 1.80 billion.
- It arrives **in bursts**: over one hour of play (231 sample points,
  2026-08-10) only **8 of 230** steps had any gain at all, spaced from
  one and a half to seventeen minutes apart.
- Magnitude for an established level 89 character: 40–163 million XP/h
  depending on the zone, measured over the time spent in that zone
  (2026-08-11). A trial or a short town run sits well below a full map.
- **It can go down.** First observed on 2026-08-13 at 01:32:24: a
  242-second zone came back at **−6,189,392** for a level 90 character,
  i.e. −92.1 million XP/h. Dying costs experience in PoE from act 5
  onwards; until this point that was common knowledge we had never seen
  in our own data.

  **The number is a net figure and says nothing about the penalty
  itself.** Whatever was killed in those four minutes is already
  subtracted from it. A death penalty of 10 % of the level's
  requirement would be roughly 16 million at level 90, so this section
  earned about 10 million and lost more — but that is arithmetic on one
  observation, not a measurement. Isolating the penalty would need a
  publication with no kills in it at all.

---

## 4. Socketed gems

**Every socketed gem gains exactly the same amount.** [wiki] Over one
hour of play and eight publications the gain was identical to the unit
for every active gem (12,187,472 XP, 2026-08-10). A single gem therefore
stands in for all of them — as long as it stays socketed and is not at
its cap. The [PoE wiki](https://www.poewiki.net/wiki/Gem) states the
same and adds the number we could not derive ourselves: gems get **10 %
of the character's experience, calculated before any level penalties**,
and the number of socketed gems makes no difference.

**Gems in the swapped-out weapon set too.** [wiki] Cross-checked over 21
publications (2026-08-11): every continuously socketed gem stood at
33,501,737 XP of gain — those in `Weapon2` and `Offhand2` exactly like
those in the active set. Also documented on the
[wiki](https://pathofexile.fandom.com/wiki/Weapon_swap), which is worth
knowing before "measuring" it: the obvious counter-assumption ("the
inactive set gets nothing") is simply false.

### The gem/character ratio measures the experience penalty

This one falls out of the wiki's wording. If gems get 10 % of the
experience **before** penalties, while `character.experience` only ever
shows the amount **after** them, then the ratio between the two says how
hard the character is currently being penalised:

    penalty ≈ 10 % ÷ (gem gain ÷ character gain)

Measured against one real session (2026-08-11/12, one row per
publication):

| Time | Zone | gem/character | implied penalty |
|---|---|---|---|
| 21:58–22:40 | maps | 18.5 % (constant to five digits) | 54 % |
| 22:59–23:15 | maps | 21.1 % | 47 % |
| 23:25–23:32 | maps | 18.5 % | 54 % |
| 00:00–00:18 | The Fathomless Depths (per the zone log) | **1030–1840 %** | **≈ 1 %** |

The three points in the last row carried tiny character gains (+1670,
+61, +5625), so their spread says little; what matters is the order of
magnitude. There the gems gained **roughly ten times what the character
gained**
— which is exactly what the rule predicts once the penalty crushes the
character's share to about a hundredth while the gems keep their full
10 %. The constant comes from the wiki, the variation from our data, and
the two fit; neither alone would have shown this. Still filed under
*Unconfirmed* below, because a single session cannot establish the 10 %
independently.

Differing **levels of progress** between gems come purely from history:

- A gem that was **taken out** gets nothing. `Summon Skitterbots` was
  out for ten minutes and afterwards was short exactly the 1,066,352 XP
  of the one burst in that window.
- A **freshly socketed** gem only takes what fits below its cap.
  `Ice Nova`, newly inserted, took only 147,967 out of a burst of
  1,066,352.

**Gems do not level up by themselves.** A full experience bar means
"waiting for the click", and until then the experience is frozen. That
is how you deliberately keep gems at level 1.

**Fields of a socketed gem** (raw, no Pydantic model of its own):

- `additionalProperties` → an `Experience` entry with
  `values[0][0] = "66921722/212046017"` and `progress` (0…1).
- `nextLevelRequirements` appears **only** when the bar is full, and
  lists the requirements of the next level — **regardless of whether
  they are met**. The field alone therefore does not say whether a gem
  is stuck.
- `requirements` lists the requirements of the **current** level.
- `properties` → `Level`, `Quality` (as with items, `values[0][0]`).

**Whether a gem is really blocked can only be decided via the
attributes** — and the character endpoint does not provide them. What
does help: whatever the character is WEARING, it necessarily meets, so
the `requirements` of the equipped items give a safe lower bound. That
bound proves "met", never "not met" — on a real character the bounds
were Str ≥ 151 / Int ≥ 131 / Dex ≥ 108 while the actual values were
280 / 145 / 114 (passive tree and jewels).

One real blocked case observed (2026-08-11): a Vaal Blade Vortex at
level 12 requires `Level 53; Dex 119` for its next level, with 114 Dex
actually available.

---

## 5. Items

- **The experience of socketed gems is part of the item data.** A
  socketable piece of equipment therefore looks "changed" on almost
  every request while playing: between two requests only twelve seconds
  apart, 25 of 29 gems had new values. Anyone comparing items to display
  changes has to strip the experience first.
- **Item IDs stay stable**, across zone changes too — an obvious
  counter-assumption that the logs disproved.
- **An item's `requirements` are the maximum over the item itself and
  its socketed gems.** Entries originating from the gems carry
  `"suffix": "(gem)"`. Example (2026-08-11): a wand showing
  `Level 68 (gem) / Str 66 (gem) / Dex 87 (gem) / Int 95 (gem)` — each
  number the highest of the three gems in it; a sceptre next to it shows
  `Str 95` and `Int 131` **without** the suffix, which is the weapon
  itself. Consequence: a gem level-up changes not only `socketedItems`
  but possibly the `requirements` of the item holding it.
- **Flasks change constantly while playing.** `properties` contains
  `Currently has {0} Charges`, and the value moves with every use. An
  item comparison therefore regularly considers flasks "changed" (four
  times in one evening, 2026-08-11) — the same kind of noise as gem
  experience, just rarer.
- **Equipped gear does not change otherwise.** Over twenty minutes of
  play, rings, amulet and belt showed not a single differing field.
- **The item text the game copies can be reconstructed from the API —
  except for the mod details.** Compared line by line on 2026-08-12: an
  export built purely from API fields matched the game's own Ctrl+C
  output exactly in every header section (item class, rarity, both name
  lines, properties with their `(augmented)` marks, requirements,
  sockets, item level). Two things worth knowing:
  - The requirements in that block include the ones raised by **socketed
    gems** — the game shows the combined value, and so does the API.
  - The game client has an option called **Advanced mod descriptions**.
    With it enabled, the copied text carries the affix name, tier and
    value range per mod (`35(33-38)% increased Armour and Energy
    Shield`). **The API never provides any of that** — checked against a
    47 MB stash cache, not one item carries an "extended" field with
    tags, tier or range. A text built from the API therefore cannot
    satisfy a tool that requires the advanced format, no matter how well
    the rest is reconstructed.

---

## 6. Maintenance: one outage, two different status codes

Measured on 2026-08-13 from 01:03:41 to 01:17:41 — 22 request cycles, 40
seconds apart, each cycle asking one character endpoint and one stash
endpoint about 170 ms apart:

| Endpoint | Answers during the outage |
|---|---|
| `/character/<name>` | 22 × `503 Service Unavailable` |
| `/stash/<league>/<id>` | **19 × `400 Bad Request`**, 3 × `503` |

The 400 carries GGG's error envelope:

```json
{"error": {"code": 2, "message": "Invalid query; League not found"}}
```

**The league existed the whole time.** At 01:18:21 the very same URL,
same league, same stash id, returned 200 with data. Nothing about the
request had changed; the servers had come back.

So during maintenance the stash endpoint blames the request rather than
the server, and picks a message that points at the caller's league.
Anyone deciding "the server is down" from the status code alone will
read most of an outage as an application bug of their own. That is
exactly what PoE-VIEW2 did: it wrote 19 stack traces into its log and
pushed 19 error messages over its own offline banner, each one telling
Peter that a league he was looking at did not exist.

Two things worth carrying over if you build on this:

- **Match on the message, not on the code.** Code 2 is GGG's general
  "Invalid query" and would equally cover a request that really is
  malformed — a wrong sub-stash path, say. Treating code 2 as "server is
  down" would swallow your own bugs.
- **The switch is not consistent even within one outage.** Three cycles
  in the middle (01:07:01–01:08:21) answered 503 on the stash endpoint
  as well, before it went back to 400.

**The outage itself lasted fourteen minutes — and GGG had announced
fifteen.** They announce maintenance ahead of time with a duration, and
for this one the announcement was accurate to within a minute (Peter,
2026-08-13: "GGG announce the maintenance, in this case they wrote 15
minutes. I think it varies"). So the duration is knowable in advance,
but only by a human reading the announcement; nothing in the API says
"back in ten minutes". Treat the fourteen minutes as one instance of a
per-event figure, not as a typical length.

---

## 7. Unconfirmed

What was looked for and **not** found. Do not read as "does not exist",
read as "not demonstrable with these means".

- **A switch that turns off a gem's experience gain.** Not to be found
  in the raw data nor in the public documentation. What looks like it is
  fully explained by the two known cases: gem taken out, or bar full and
  not clicked.
- **The exact formula for the experience penalty** by character level
  and zone level. That one exists is known. What we can now do is
  *measure the current penalty* from the gem/character ratio (§4) — but
  that rests on the wiki's 10 %, which our own data cannot confirm
  independently. Deriving it would need a character low enough to have
  no penalty at all, where the ratio should read exactly 10 %.
- **The size of the death penalty.** That experience is lost on death is
  no longer unconfirmed — see §3, first observed 2026-08-13. How *much*
  still is: what the API publishes per zone is the net of everything
  earned and everything lost there, and the two cannot be separated from
  outside. The widely quoted "10 % of the current level's requirement"
  is consistent with our one observation but not established by it.

---

## 8. Disproven

Plausible assumptions that turned out to be wrong. They are here so they
do not come back.

- **"GGG hands out new item IDs on zone changes."** Would have been the
  most convenient explanation for items wrongly detected as new. The
  pattern that would require (a simultaneous arrival and departure of
  the same magnitude) does not occur once in the logs.
- **"The order of `socketedItems` is unstable between requests."**
  Sounded compelling, because Pydantic's list comparison reacts to it.
  Across 47 consecutive sample points the order was stable **without
  exception**. The real cause was gem experience.
- **"Gems gain different amounts of experience depending on how often
  the skill is used."** Concluded from a single snapshot in which the
  gems stood at very different levels of progress. But a snapshot shows
  stocks, and the question was about increments — those are identical.
- **"Identifying at a vendor publishes immediately."** Concluded from
  two direct hits on 2026-08-10, where new data was there 0.4 seconds
  after the `Items identified` line, having been requested 35 and 9
  times in vain before that. Recalculated two days later across 30
  events: 7 hits, 5 of them in the slipstream of a zone change, so 2
  clean ones out of 30. That is the background rate of late
  publications, not an effect. **The lesson is not "identifying does
  nothing" but "two hits are not a sample"** — the claim stood in the
  documentation for four days because nobody asked about the misses.
- **"If equipment still lights up after stripping gem experience, some
  of the bug is left."** On 2026-08-11 the weapon and the shield hand
  were the only equipped items lighting up. Comparing every single
  highlight of that evening against the gem recording showed: **all** of
  them went back to a genuine gem level-up or a socket change. Freshly
  socketed low-level gems level up every few minutes and make their item
  light up on almost every zone change — it looks like the old bug, but
  it is the correct display.
- **"At publication time the character is in the zone it has just
  returned to."** Usually yes, but not always: the publication can
  arrive when the character is long since in the next zone. Basing a
  time measurement on that gives denominators of a few seconds and rates
  in the billions.
- **"A 4xx from GGG is always our own fault."** A reasonable rule, and
  the one PoE-VIEW2 was built on: 5xx means the server, 4xx means the
  request. The maintenance window of 2026-08-13 broke it — see §6. Most
  of that outage arrived as HTTP 400.

---

## 9. What PoE-VIEW2 makes of it

Signposts only — the reasoning lives in each place:

| Observation | Implementation |
|---|---|
| Data arrives on a zone change | zone watcher, ARCHITEKTUR.md §ZoneWatcher |
| Delve is blind, vendors publish | vendor trigger, §4.36 |
| Gem experience sits inside the item data | `_stable_item_dump`, §4.33 |
| Flask charges fluctuate constantly | `_VOLATILE_ITEM_PROPERTIES`, §4.33 |
| A gem level-up changes the whole item | green highlight, §4.33 |
| Experience arrives in bursts, zone by zone | XP/h over dwell time, §4.34 |
| Gem states, attribute lower bound | gem recording, §4.35 |
| Maintenance answers 400 as well | offline detection, §4.12 |
