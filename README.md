# PoE-VIEW2

Ein Community-Tool für **Path of Exile**: liest über die offizielle GGG-API
Accounts, Charaktere und Stash-Tabs aus und stellt sie übersichtlich dar —
mit striktem, sichtbarem Rate-Limit-Management.

PoE-VIEW2 ist die **Python-Referenzimplementierung** des LabVIEW-Projekts
*PoE-VIEW*. Architektur und Code sind bewusst so dokumentiert, dass sie sich
später nach LabVIEW (zurück-)portieren lassen — siehe
[docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md), insbesondere die
Mapping-Tabelle *Python ↔ LabVIEW*.

Gelöste technische Hürden und Workarounds werden laufend in
[FALLSTRICKE_UND_WORKAROUNDS.md](FALLSTRICKE_UND_WORKAROUNDS.md) festgehalten.

## Status

🚧 In Entwicklung — aktuell: Architektur-/Konzeptphase (siehe Roadmap in der
[Architektur-Doku](docs/ARCHITEKTUR.md#8-roadmap--meilensteine)).

## Tech-Stack

- Python 3.12+, PySide6 (GUI), httpx (HTTP), pydantic v2 (Datenmodelle)
- OAuth2 mit PKCE gegen die GGG-API, Token im Windows Credential Manager

## Setup (geplant)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # eigene Client-ID & Kontakt-E-Mail eintragen
python main.py
```

Für die GGG-API wird eine eigene OAuth-Client-Registrierung benötigt:
<https://www.pathofexile.com/developer/docs/authorization>

## Disclaimer

This product isn't affiliated with or endorsed by **Grinding Gear Games**
in any way.
