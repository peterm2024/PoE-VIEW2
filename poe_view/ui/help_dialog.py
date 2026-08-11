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
from poe_view.ui.theme import (RARITY_COLORS, ROW_CHANGED_COLOR,
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


def _swatch(colour: str, label: str) -> str:
    """Farbfleck + Name — bildet die Typ-Filter-Kästchen der Toolbar nach,
    damit die Zuordnung Farbe → Bedeutung ohne Raten möglich ist."""
    return (f'<tr><td><span style="color:{colour};">&#9632;</span></td>'
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


TOPICS: tuple[tuple[str, str], ...] = (
    ("Getting started", """
<h3>Getting started</h3>
<p>Click <b>Log in</b> in the toolbar. Your browser opens the official
Path of Exile sign-in page. PoE-VIEW2 never sees your password: it
receives only an access token, which is kept in the Windows Credential
Manager.</p>
<p>Pick a league in the second toolbar row, then click a stash tab or a
character on the left. Tabs are fetched when you first open them, not
all at once — that keeps the tool inside the API rate limit.</p>
<p>Once data has been loaded it stays available offline. If the API is
unreachable, or during GGG maintenance, you keep browsing the last known
state; the stash tree marks this with 📴.</p>
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
<p><b>Regular expressions</b> are on by default (the <code>.*</code>
toggle), matching how Path of Exile's own stash search behaves. Socket
patterns copied from sites like poe.re therefore work unchanged, for
example <code>r-r-g|r-g-r|g-r-r</code>. Turn the toggle off for plain
text search.</p>
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
<p>GGG's API tends to publish new stash contents only after something
happens in the game — changing zone, selling to a vendor, identifying
items. PoE-VIEW2 can watch the game's own <code>Client.txt</code> for
those moments and refresh at exactly the right time — off by default,
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
hours.</p>
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
data, the icon cache, prices, your settings and the log file. Nothing is
sent anywhere except to the servers listed in the README.</p>
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
<p>The application identifies itself to GGG's API as
<code>{config.CLIENT_ID}</code> with the contact address
<code>{config.CONTACT_EMAIL}</code>, as their developer documentation
requires.</p>
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
