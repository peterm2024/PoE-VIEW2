"""Hilfe-Fenster: erklärt die Oberfläche an einer Stelle (Peter,
2026-08-03: "Punkt 5 wäre eine kleine Hilfe-Funktion", nach dem
Spielertest, der mehrere selbsterklärungsbedürftige Stellen zutage
gefördert hatte — unbeschriftete Farbfilter, `#2 (0, 0)` in der
Positionsspalte, die Pfeile im Verlauf, die leere Wertspalte in
SSF-Ligen).

**Texte auf Englisch**, wie die gesamte Oberfläche und die README —
Kommentare und Projektdoku bleiben deutsch (bewusste Trennung, siehe
README/ARCHITEKTUR). Ein Hilfetext auf Deutsch in einer englischen
Oberfläche wäre für die Zielgruppe wertlos.

Aufbau bewusst schlicht: Themenliste links, Text rechts, keine
Navigation, keine Suche. Der Inhalt steht als HTML in ``TOPICS`` und ist
damit an einer Stelle pflegbar. Farben kommen aus ``theme.RARITY_COLORS``
statt aus fest eingetippten Werten — sonst liefe die Legende der
Typ-Filter beim nächsten Farbwechsel aus dem Ruder.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
                               QListWidget, QSplitter, QTextBrowser,
                               QVBoxLayout, QWidget)

from poe_view import __version__, config
from poe_view.ui.theme import (LED_OFFLINE, LED_ONLINE, LED_UNKNOWN,
                               RARITY_COLORS, ROW_CHANGED_COLOR,
                               ROW_GEM_LEVELED_COLOR)


def _icon_src() -> str:
    """Das Anwendungssymbol als ``file:``-Adresse fürs ``<img>`` im
    About-Text. Qts Rich Text braucht eine echte URL, kein Windows-Pfad
    (Backslashes und ein ``C:`` am Anfang landen sonst als relativer
    Pfad im Nichts). Fehlt die Datei — in der gepackten .exe wäre das
    ein vergessener ``datas``-Eintrag —, bleibt die Adresse leer und Qt
    zeigt gar nichts an statt eines kaputten Bildrahmens."""
    if not config.APP_ICON_PNG.exists():
        return ""
    return QUrl.fromLocalFile(str(config.APP_ICON_PNG)).toString()


def _swatch(colour: str, label: str, glyph: str = "&#9632;") -> str:
    """Farbfleck + Name — bildet die Typ-Filter-Kästchen der Toolbar nach,
    damit die Zuordnung Farbe → Bedeutung ohne Raten möglich ist.

    ``glyph`` gibt die Form vor: voreingestellt das Quadrat der
    Filter-Kästchen, für die runde Verbindungs-LED (§4.41) der Punkt. Eine
    Legende, die anders aussieht als das Erklärte, kostet den Leser einen
    zweiten Blick."""
    return (f'<tr><td><span style="color:{colour};">{glyph}</span></td>'
            f'<td>&nbsp;{label}</td></tr>')


_TYPE_LEGEND = "<table>" + "".join(
    _swatch(RARITY_COLORS.get(key, "#cc66aa"), name) for key, name in (
        (0, "Normal"), (1, "Magic"), (2, "Rare"), (3, "Unique"), (4, "Gem"),
        (5, "Currency"), (6, "Divination Card"),
        (None, "Other — quest items, relics, anything without its own category"),
    )) + "</table>"


# Legende der Charakter-Refresh-Hervorhebung (§4.20/§4.33). Dieselben
# Konstanten wie die Tabelle selbst — eine Farbe, die hier fest
# hingeschrieben wäre, liefe beim nächsten Theme-Wechsel auseinander.
_REFRESH_LEGEND = "<table>" + "".join((
    _swatch(ROW_CHANGED_COLOR, "New or changed since the last refresh"),
    _swatch(ROW_GEM_LEVELED_COLOR, "A socketed gem gained a level"),
)) + "</table>"


# Die Verbindungs-LED der Statuszeile (§4.41). Drei Zustände, und der
# graue ist der erklärungsbedürftigste: Er heißt NICHT "kaputt".
_LED_GLYPH = "&#9679;"

_CONNECTION_LEGEND = "<table>" + "".join((
    _swatch(LED_ONLINE, "Connected — what you see came from GGG just now",
            _LED_GLYPH),
    _swatch(LED_OFFLINE, "GGG unreachable: maintenance, or no network. "
                         "The tool keeps working from its cache", _LED_GLYPH),
    _swatch(LED_UNKNOWN, "Nothing asked yet — not logged in, or no request "
                         "has run so far", _LED_GLYPH),
)) + "</table>"


TOPICS: tuple[tuple[str, str], ...] = (
    ("Getting started", f"""
<h3>Getting started</h3>
<p>Click <b>Log in</b> in the toolbar. Your browser opens the official
Path of Exile sign-in page. PoE-VIEW2 never sees your password: it
receives only an access token, which is kept in the Windows Credential
Manager.</p>
<p>Two things on that page look more alarming than they are. It asks you
to authorize <b>PoE-VIEW</b>, without the "2" — that is this tool: the
first PoE-VIEW was a LabVIEW program, this one is the rewrite in Python,
and the registration with GGG came along from the older one. And a red
box tells you GGG cannot verify that the request came from PoE-VIEW:
every application without a client secret gets it, because a desktop
program has nowhere to keep a secret, and it says nothing about your
login going wrong. The permissions the page lists are all read-only; the
API offers this tool no way to change anything on your account.</p>
<p>Pick a league in the second toolbar row, then click a stash tab or a
character on the left. The league you picked last comes back the next
time you start. Tabs are fetched when you first open them, not
all at once — that keeps the tool inside the API rate limit.</p>
<p>Once data has been loaded it stays available offline. If the API is
unreachable, or during GGG maintenance, you keep browsing the last known
state; the stash tree marks this with 📴.</p>
<p>The dot at the right-hand end of the status bar says which of those
you are looking at:</p>
{_CONNECTION_LEGEND}
<p>GGG announce their maintenance windows in advance, and they are
usually short — a quarter of an hour is typical. The dot goes back to
green by itself, without a restart, as soon as a request succeeds
again.</p>
"""),
    ("The item table", """
<h3>The item table</h3>
<p><b>Position</b> looks like <code>#2 (0, 0)</code>. The
<code>#2</code> is the tab's number in your stash, the pair in brackets
is the item's grid coordinate inside that tab. The tab number matters
when several tabs share the same name.</p>
<p><b>iLvl</b> is the item level (relevant for crafting),
<b>Req.Lvl</b> the character level required to equip it. <b>Stack</b> is
filled only for stackable items.</p>
<p><b>Columns</b> can be shown, hidden and reordered — either in
Settings, or quickly via right-click on a column header.</p>
<p><b>Column filters</b> also live in that right-click menu. They accept
comparisons, so <code>&gt;=20</code> on Quality or <code>&lt;45</code>
on iLvl work as expected. A filtered column is marked with 🔍. While you
type, the field completes what you have started from the values actually
present in that column — press Return or Tab to take the suggestion.</p>
<p><b>📌 Pin</b> is the quick way to the same thing: right-click an item
and pick it to filter that column down to exactly the value you clicked
on. Right-clicking <code>MainInventory</code> in the Tab column leaves
only items from there.</p>
"""),
    ("Type filters", """
<h3>Type filters</h3>
<p>The coloured boxes next to the league selector filter by item
rarity or category:</p>
""" + _TYPE_LEGEND + """
<p>Three gestures: a plain <b>click</b> shows only that type,
<b>Ctrl+click</b> adds or removes one type, and <b>Ctrl+Shift+click</b>
or a <b>double-click</b> brings all types back.</p>
"""),
    ("Searching", """
<h3>Searching</h3>
<p>The search field always searches <b>all loaded tabs and characters of
the league at once</b>, no matter which tab is open. The Tab column then
shows where each hit came from. Clear the field to return to the tab you
had selected.</p>
<p>Type <code>*</code> to list the entire league — useful before an
export.</p>
<p><b>Several keywords, separated by spaces, must all match</b> — the
same rule as the game's own stash search. <code>life resistance</code>
finds items carrying both, even though the two words never stand next to
each other in the text. Each further word narrows the result down.</p>
<p>To search for a phrase that contains a space, put it in
<b>quotation marks</b>: <code>"maximum life"</code> no longer matches an
item that merely has maximum mana and some life regeneration.</p>
<p><b>Regular expressions</b> are on by default (the <code>.*</code>
toggle), matching how Path of Exile's own stash search behaves. Socket
patterns copied from sites like poe.re therefore work unchanged, for
example <code>r-r-g|r-g-r|g-r-r</code>. Each keyword is its own pattern,
so a regex that contains a space belongs in quotation marks. Turn the
toggle off for plain text search.</p>
<p>Searched is everything the item says about itself: name, base, rarity,
sockets, all its mods and properties, the tab it sits in — and the names
of the <b>gems socketed into it</b>.</p>
<p>Two shorthands from the game work as well: <code>ilvl:84</code> finds
item level exactly 84, <code>tier:16</code> map tier exactly 16. Both
combine with everything else (<code>ilvl:84 ring</code>). For ranges use
a column filter instead — right-click a column header and type
<code>&gt;=84</code>.</p>
<p><b>Ctrl+F</b> jumps to the search field and selects what is in it, so
you can start typing over it straight away.</p>
<p>In very large leagues the search waits until you pause typing before
it filters, instead of rebuilding the table on every keystroke.</p>
"""),
    ("Keeping data fresh", f"""
<h3>Keeping data fresh</h3>
<p>The <b>Mode</b> dropdown decides what happens in the background. All
modes share the same rate-limit budget and leave room for your clicks:</p>
<ul>
<li><b>Auto</b> — keeps the open tab or character current and gradually
fills in the rest of the stash. The default.</li>
<li><b>Single</b> — refreshes only what you have selected, on a steady
clock.</li>
<li><b>Stash</b> — cycles through the whole league continuously,
non-empty tabs first.</li>
<li><b>Pause</b> — no background requests at all. Clicks and
"Load All Tabs" still work and get the full budget.</li>
</ul>
<p>Above the tree, <b>Hide empty</b> takes tabs that are known to hold
no items out of the list. Tabs that were never loaded stay — an empty
count column means unknown, not empty. This only changes the view: every
tab keeps being refreshed in the background, so one reappears the moment
you put something in it.</p>
<p>GGG's API publishes new character data almost only after a zone
change, a second or two later. PoE-VIEW2 can watch the game's own
<code>Client.txt</code> for that moment — and for vendor trades and
identifying, which occasionally publish too — and refresh right then,
instead of on a fixed clock. Off by default,
switch it on under <i>Settings &gt; Zone Refresh</i>. The toolbar then
shows the zone last detected. A burst of events in quick succession is
capped at four refreshes, so it never eats into the request budget your
own clicks need.</p>
<p>After a character refresh the table marks what moved:</p>
{_REFRESH_LEGEND}
<p>An item that left the inventory stays visible for one more cycle,
greyed out and <s>struck through</s>, then disappears.</p>
<p>Equipment lights up more often than you might expect, because a
socketed gem gaining a level counts as a change to the item holding it —
that is what the green is for. Gem <i>experience</i>, which ticks up
constantly while you play, is ignored, as are flask charges.</p>
<p>The status bar tells you how that is going. <b>Updated 14:23:05</b> is
when the table was last rebuilt; if <b>unchanged for 12m</b> appears next
to it, data kept arriving but stayed identical — almost always the
API holding back a new stash state rather than a fault. Change zone in
the game and it will catch up.</p>
"""),
    ("Load All Tabs", """
<h3>Load All Tabs</h3>
<p>Fetches every stash tab of the current league, one after another.
With a large stash this takes a while: the rate limit allows only a
handful of requests per minute, and the tool deliberately stays below
it.</p>
<p>The progress window shows two different counts, and they rarely
match:</p>
<ul>
<li><b>tab x of y</b> — your stash tabs, the ones you see in the game.</li>
<li><b>x of y requests</b> — the actual calls to the API. This is what
the progress bar tracks and what the remaining time is based on.</li>
</ul>
<p>The reason they differ: a map or unique stash is a single tab in your
stash, but holds up to several hundred sections, and each one needs its
own request. The window breaks the total down for you, so the numbers
add up in front of you rather than looking like a contradiction. It also
means the tab counter can sit still for a long while — that is the tool
working through one big tab, not a hang.</p>
<p>Remove-only tabs are fetched too. They can only shrink, never grow,
but this button is the one you press when you want everything.</p>
<p>You can close the window at any time; loading stops, and everything
fetched so far is kept.</p>
"""),
    ("Item values", """
<h3>Item values</h3>
<p>The <b>Value</b> column shows prices from
<a href="https://poe.ninja">poe.ninja</a>, in chaos or divine depending
on the amount. The status bar adds up everything currently visible, so
filtering or searching narrows the total accordingly.</p>
<p>The table starts sorted by value, cheapest first — items without a
known price group with the cheap ones, since both are usually not worth
keeping.</p>
<p><b>Why the Value column stays empty in SSF leagues:</b> poe.ninja
derives prices from trading activity, and Solo Self-Found leagues have
none, so they are not tracked at all. The status bar says <b>No prices
for this league</b> when that is the case. It is a limit of the data
source, not a fault in PoE-VIEW2 — there is nothing to fix or
configure.</p>
<p>Prices are community data, not official, and are cached for up to six
hours. Next to the total the status bar names how old the current set
is — <b>poe.ninja 2 h ago</b> — so you can tell a genuinely cheap item
from a stale price. Hover it for the exact time it was fetched.</p>
"""),
    ("Levelling", """
<h3>Levelling</h3>
<p>Open a character and the panel to the right of the item detail shows
level, total experience and how fast you are gaining it.</p>
<p><b>The rate is measured per area, over the time you spent in it</b> —
not against the clock. Standing in your hideout does not drag it down,
and a break does not make it decay: it simply stays where it was. GGG
only publish experience when you leave an area, so the number can never
be fresher than your last zone change; if it is more than a minute old,
that is written next to it.</p>
<p><b>Watched stack sizes</b> fill the right-hand side of this panel,
beside the level, the rate and the gem bars. Right-click any
item in the table and pick <i>Watch stack size</i>; its total across every
loaded stash tab and character of this league then stays in view, whatever
you are looking at. Right-click it again to stop. A <b>≥</b> in front of a
number means some tabs of this league have not been loaded yet, so there
may be more than it says. An item you own none of shows <b>0</b> rather
than disappearing — that is the answer you were looking for.
<b>Drag a row</b> to move it: the list stays in the order you put it in,
across restarts, and is never re-sorted by amount behind your back.</p>
<p>Above the graph, <b>one narrow bar per socketed gem</b> shows its
<b>level</b> as the filled height, coloured by the attribute it needs.
Read the strip as a profile of the character: the short bars are the
gems lagging behind. Hover for the name, level and progress.</p>
<p>The thin <b>yellow line</b> inside a bar is the progress towards the
next level, read across the whole height of the bar.</p>
<p>A <b>solid bar in a vivid colour</b> — red, green, blue or white —
means the gem is finished: level 20, or 21 if it is corrupted, or
whatever its own maximum is. Nothing left to do there.</p>
<p>A <b>yellow cap</b> on top means the opposite — the bar is full but the
gem is below its maximum. Gems never level up on their own, so that is
free character power sitting unclaimed until you click it.</p>
<p>The graph below covers the <b>last three hours</b>, one bar per
finished area:</p>
<ul>
<li>The <b>width</b> is how long you were in there, so a long map looks
different from a quick trial.</li>
<li><b>Gaps are real.</b> Where nothing is drawn, no experience was
made — town, stash, a break.</li>
<li>A <b>red bar below the line</b> is an area that cost you experience
on balance. Dying does that from act 5 onwards.</li>
<li>A <b>dark green block behind several bars</b> means they are the
same map: you left it and came back. Its height is the rate for the map
as a whole, so you can see what the trip outside cost.</li>
<li>The <b>bar in front of a mod line</b> comes from your <b>mod
collection</b>: it shows where this roll sits between the worst and the
best you have ever seen of that mod, on items of the same rarity and
league. A full bar is the best you know of, an empty one the worst — and
those two ends are exact, a roll just short of the record never fills the
bar completely. A <b>dimmed</b> bar means the comparison had to fall back
on your permanent stash, because the item's own league has too few
sightings yet. <b>No bar</b> means there is nothing to compare: the mod
has only ever shown one value, or fewer than five sightings. <b>✦</b>
means the mod is new to your collection. The collection fills itself from
everything that passes through your stash — it says what YOU have seen,
not what the game allows. Temporary leagues are kept apart, since mod
values change between them; Standard and the other permanent leagues
share one pot, because they hold items rolled in every league there ever
was. The <b>Mods</b> toolbar button opens the whole collection as an
<b>album of cards</b> — every mod a card with its range and how often it
was seen, a <b>golden frame</b> around the ones seen exactly once (the
singles of the collection) and a <b>✦</b> on this session's new finds.
Sort the cards by name, newest finds, most seen or singles first; the
<b>Show table</b> button flips to a sortable list of the same mods.
Search and the filters (text, kind, league, rarity) work in both views,
and the <b>Range</b> column shows the lowest and highest value ever seen
for whichever of those you have selected (everything, if you have not
narrowed it down), followed by how many of that mod's tiers you have
already rolled — <b>6/8</b> means two tiers are still missing from your
collection. That counter needs the game data below, and it steps aside
as soon as you filter by league or rarity, because the tier record is
kept across all of them. Rarity includes a <b>Corrupted</b> group of its own:
a corrupted item's mods are counted apart from an uncorrupted one's, even
at the same rarity, since some corruption outcomes roll from an entirely
different table. Click a mod to see every rarity and league it has ever
shown up on, in full — and its <b>tiers</b>, one row per tier.

<p>Where PoE-VIEW2 knows the real ladder, the table is headed <b>Tiers,
straight from game data</b>: every tier the game can roll, T1 at the
top, with the item level that unlocks it, how often you have seen it and
your best roll. <b>The tiers you have never rolled are listed too, and
left empty</b> — those are the gaps in your album, and the line beneath
counts them up (<i>6 of 8 tiers collected</i>). A roll that belongs to
no tier at all gets its own <i>beyond the ladder</i> row: crafted,
essence and influenced mods roll from tables of their own.</p>

<p>For a mod whose ladder is not known, the table falls back to
<b>tier bands</b> worked out from item level: a tier cannot appear below
the level that unlocks it, so the lowest level a value ever showed up on
marks where the boundaries are. Those bands are labelled as
<b>% of the seen span</b> rather than tier numbers, since numbers would
invite comparison with the real ladder while this is still a guess.
Upper bounds are proven, lower bounds assume tiers meet without gaps. If
a mod shows a reason instead of bands, that is usually because every
sighting came from high-level maps, where nearly all tiers are already
unlocked — levelling through the campaign is what tells them apart.</p>

<p>The game data behind all this is fetched in the background when the
program starts and kept locally for a week. Until it arrives — on a
first start without a connection, say — every mod falls back to the
estimated bands.</p></li>
<li>The <b>average line</b> is your rate over the stretch you are
currently in: since your last level-up, or since a break of more than
half an hour, whichever came later, and never more than the three hours
on screen. That stretch is drawn as a <b>solid green line</b>, its
length is written next to the number, and outside it the line thins to a
dashed one — there it is only a yardstick for the older bars, not a
measurement.</li>
</ul>
<p><b>Closing the program does not empty the graph.</b> Finished sections
are stored per account and drawn again next time, as long as they still
fall inside the three-hour window. What does start over is the
measurement itself: the first rate after a restart needs two
publications again, because a baseline carried across a break would turn
whatever you levelled meanwhile into one absurd number.</p>
"""),
    ("Item history", """
<h3>Item history</h3>
<p>The collapsible panel below the table logs the last 120 items that
moved through the inventory of <b>any</b> of your characters — a quick
way to check what you just stashed, sold or traded. It follows every
character, not only the one on screen.</p>
<p>The Event column uses three symbols:</p>
<ul>
<li><b>↑</b> — the item appeared</li>
<li><b>↓</b> — the item is gone</li>
<li><b>±</b> — the quantity changed; the Stack column then carries the
difference, for example <code>53 (+3)</code></li>
</ul>
<p>Stash tabs are deliberately not covered: the history is about what
passes through your hands while playing.</p>
"""),
    ("The rate-limit bar", """
<h3>The rate-limit bar</h3>
<p>GGG allows only a limited number of API requests per time window and
locks the account out temporarily when that is exceeded. PoE-VIEW2
tracks every rule the API reports and paces itself to stay below the
limit — the bar at the bottom shows what it currently knows.</p>
<p>Each bar is one rule, labelled like <code>28/60 · 300 s</code>: 28 of
60 permitted requests used within a 300-second window. Green means
plenty of room, the colour shifts as it fills up.</p>
<p>You do not need to watch this. It is there so that unusual waiting
times are explainable rather than mysterious, and it is genuinely useful
during a long "Load All Tabs" run.</p>
"""),
    ("Your data", """
<h3>Your data</h3>
<p>Everything PoE-VIEW2 stores stays on your computer, under
<code>%LOCALAPPDATA%\\PoE-VIEW2</code>: the loaded stash and character
data, the icon cache, prices, the experience graph's history, your
settings and the log file. Nothing is sent anywhere except to the
servers listed in the README.</p>
<p><b>Each account keeps its own data file</b>, so switching accounts
never mixes them up, and switching back brings your previous state with
it.</p>
<p><b>Log out</b> (in the account button) removes only the locally
stored token. It does not revoke the authorisation on GGG's side — do
that in your GGG account settings if you want it gone completely. Your
loaded data is kept either way.</p>
<p><b>A second window on the same account runs read-only</b>, and the
status bar says so. Only one window may fetch and save, otherwise the
two would write over each other and share the same request budget. The
read-only one still browses everything already loaded — search, filters,
item details, CSV export. Log in there with a different account and it
becomes fully usable; accounts never get in each other's way.</p>
<p><b>A backup is written at every start</b>, before the new session can
change anything, into the <code>backups</code> sub-folder. Each one is
named after the moment it was taken and is compressed to about a tenth of
the original size. Backups are kept for 24 hours; the most recent one is
never removed, however old it is. Nothing is written when the data has
not changed since the last backup.</p>
<p>To go back to an earlier state: close PoE-VIEW2, unpack the backup you
want with any archive program, rename the result to match the cache file
next to the <code>backups</code> folder, and replace it.</p>
<p>There is deliberately no delete or restore function inside the
program. Both are one click away from destroying data that took hours of
requests to gather — in Explorer you see exactly what you are doing.</p>
"""),

    ("Path of Exile 2", """
<h3>Path of Exile 2</h3>
<p>PoE-VIEW2 reads Path of Exile 1. There is no PoE2 support, and this
is not a temporary gap in the tool.</p>
<p>GGG's API selects the game with a <code>realm</code> parameter. Its
documentation allows <code>poe2</code> on the character and league
endpoints but not on the stash endpoints, and stash tabs are the heart
of this program — so a PoE2 mode would be missing its main half.</p>
<p>Measured on 15 August 2026, it is emptier than that. Asking for
<code>realm=poe2</code>, asking for nothing, and asking for a realm that
does not exist all return byte-identical Path of Exile 1 data. The
parameter is not being evaluated at all, so the API cannot even tell you
whether your account has PoE2 characters.</p>
<p>You can check this yourself at any time: open the account menu next
to your name and pick <b>PoE2 raw data</b>. It runs the same request
three ways, compares the checksums and writes its verdict in plain words
above the raw JSON. Nothing from it enters the table, the cache or the
value column.</p>
<p>The dump is also written to <code>poe2-probe.txt</code> next to the
other local files, since a full character is too long to read in one
screen. It contains your account and character names, so look before
you pass it on.</p>
"""),
    ("About PoE-VIEW2", f"""
<h3>About PoE-VIEW2</h3>
<p><img src="{_icon_src()}" width="64" height="64" style="float: left"
   align="left">
<b>Version {__version__}</b> — a desktop viewer for Path of Exile
stash tabs and characters, built on the official GGG API.</p>
<p><b>{config.DISCLAIMER}</b> It is likewise not affiliated with or
endorsed by poe.ninja, whose publicly available price data the optional
value display builds on.</p>
<p>PoE-VIEW2 is free software under the MIT licence. Source code, issue
tracker and releases:
<a href="https://github.com/peterm2024/PoE-VIEW2">github.com/peterm2024/PoE-VIEW2</a></p>
"""),
)


class HelpDialog(QDialog):
    """Themenliste links, Text rechts. Bewusst nicht modal aufgebaut wie
    ein Assistent — man soll nachschlagen und weiterarbeiten können."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PoE-VIEW2 — Help")
        self.resize(760, 560)

        self._topics = QListWidget()
        self._topics.addItems([title for title, _ in TOPICS])
        self._topics.setMaximumWidth(200)

        self._text = QTextBrowser()
        self._text.setOpenExternalLinks(True)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._topics)
        splitter.addWidget(self._text)
        splitter.setStretchFactor(1, 1)

        row = QHBoxLayout()
        row.addWidget(splitter)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(buttons)

        self._topics.currentRowChanged.connect(self._show_topic)
        self._topics.setCurrentRow(0)

    def _show_topic(self, row: int) -> None:
        if 0 <= row < len(TOPICS):
            self._text.setHtml(TOPICS[row][1])
