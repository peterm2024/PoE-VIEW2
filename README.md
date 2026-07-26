# PoE-VIEW2

[![Release](https://img.shields.io/github/v/release/peterm2024/PoE-VIEW2?label=Release)](https://github.com/peterm2024/PoE-VIEW2/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A desktop tool for **Path of Exile**. It displays characters and stash
tabs through the official GGG API, searches them league-wide across all
tabs, and keeps the data up to date automatically without exhausting the
API rate limit. If the GGG API is unreachable, PoE-VIEW2 keeps working
from the local cache.

Login runs via OAuth2 directly against `api.pathofexile.com`. PoE-VIEW2
never sees your password, and no third party is involved. The access
token is stored in the Windows Credential Manager.

## Screenshots

*Both screenshots show synthetic demo data, not a real account.*

League-wide search with `*`: stash tabs and characters appear together
in one table, with the Tab column showing where each item came from.
Type filters are above, the rate-limit dashboard below.

![League-wide search across tabs and characters](docs/screenshots/uebersicht.png)

A single stash tab with an item selected; its mods are shown in the
detail panel below.

![Single tab with a selected item and its mods](docs/screenshots/item-details.png)

## Features

- **OAuth2 login (PKCE)** against the official GGG API. The access
  token is stored in the Windows Credential Manager, not in plain text
  on disk.
- **Stash tree** with folders; special tabs (map and unique stash) are
  automatically grouped by section or category.
- **Item table** with icon, source tab, position (tab number and grid
  coordinate, distinguishing tabs with the same name), name, type,
  level, quality, stack size, item level, requirements (level, Str,
  Dex, Int), and mods.
- **Column filters** via right-click on a column header, supporting
  comparison expressions such as `>=20` for quality or `<45` for item
  level.
- **League-wide search** across all loaded tabs and characters at once.
  `*` as the search text lists the entire holdings, useful for
  exporting a whole league.
- **Type filters** for Normal, Magic, Rare, Unique, Gem, Currency,
  Divination Card, and Other, shown as color-coded checkboxes next to
  the league selector.
- **Character view**: equipment and inventory appear in the same table
  as stash items and are just as searchable and filterable.
- **CSV export** of the currently visible, filtered items.
- **Automatic background refresh**: keeps the open tab or displayed
  character up to date and gradually reloads the remaining tabs,
  without spending the rate-limit budget reserved for manual requests.
- **Offline mode**: during GGG maintenance or a lost connection, the
  app shows the last known state from the cache, clearly marked as such
  (📴).
- **Rate-limit dashboard** with rules, current usage, and active locks.
- **Raw data viewer** per stash tab, showing the unmodified API
  response.

## Download (Windows, no Python required)

The [releases page](https://github.com/peterm2024/PoE-VIEW2/releases)
provides a ready-to-run `PoE-VIEW2.exe` for every version. Download and
run it — no installation or configuration needed. On first launch,
clicking "Log in" opens the GGG sign-in flow in your browser.

Windows SmartScreen warns about an "unknown publisher" for unsigned
applications. This affects any application without code signing and
can be confirmed via "More info" and "Run anyway".

## Tech stack

- Python 3.12+, [PySide6](https://doc.qt.io/qtforpython/) (GUI),
  [httpx](https://www.python-httpx.org/) (HTTP),
  [pydantic v2](https://docs.pydantic.dev/) (data models),
  [keyring](https://pypi.org/project/keyring/) (token storage)
- OAuth2 with PKCE against the official GGG API (no client secret
  required)

## Setup from source

```bash
git clone https://github.com/peterm2024/PoE-VIEW2.git
cd PoE-VIEW2
python -m venv .venv
.venv\Scripts\activate          # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

A `.env` file is not required; the client ID and contact address have
working defaults. If you fork PoE-VIEW2 and distribute it yourself, you
should override both (`.env.example` serves as a template):

- **`POE_CLIENT_ID`** — defaults to `poeview`, a public client ID
  registered with GGG. You can register your own at
  <https://www.pathofexile.com/developer/docs/authorization>; the
  redirect port `64338` must then match the redirect URI registered
  there.
- **`POE_CONTACT_EMAIL`** — the contact address sent in the User-Agent
  header. Per the [GGG documentation](https://www.pathofexile.com/developer/docs),
  it identifies the application, not the individual user, and should
  point to your own address if you distribute your own build.

On first launch, the login button opens the default browser for the
GGG sign-in. After that, the session stays valid until the token
expires; GGG determines the token's lifetime.

To build your own `.exe`, see [RELEASING.md](RELEASING.md).

## Tests

```bash
pytest
```

The test suite covers data models, the API client, the rate limiter,
the worker, and the UI logic. It requires no network access.

## Documentation

- [CHANGELOG.md](CHANGELOG.md) — changes per version.
- [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md) — application structure
  and the reasoning behind design decisions (in German).
- [docs/api-notes/ggg-api.md](docs/api-notes/ggg-api.md) — observed
  behavior of the GGG API, including deviations from the official
  documentation (in German).
- [FALLSTRICKE_UND_WORKAROUNDS.md](FALLSTRICKE_UND_WORKAROUNDS.md) —
  solved technical hurdles with cause and fix (in German).

## Status

PoE-VIEW2 is in daily use. Login, stash and character views, search,
filters, CSV export, auto-refresh, and offline mode all work. The
project is developed by a single person and makes no claim to
completeness compared to the official PoE website. Bug reports and
pull requests are welcome.

## License

[MIT](LICENSE)

## Disclaimer

This product isn't affiliated with or endorsed by **Grinding Gear Games**
in any way.
