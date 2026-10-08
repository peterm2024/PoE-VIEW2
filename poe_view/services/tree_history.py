"""Der vergebene Passiv-Baum je Charakter, mit Verlauf (§4.60).

Gespeichert wird bei jedem Charakter-Abruf, aber nur, wenn sich der Baum
geändert hat — ein Respec oder neue Punkte, nicht jeder Abruf alle paar
Sekunden. Daraus wird später die Zeitleiste ("Level 81: +Constitution").

Je Konto eine Datei ``passive-trees-<konto>.json``::

    {"version": 1,
     "characters": {
        "<name>": {"current": {...}, "history": [{...}, ...]}}}

Ein Eintrag ist ``{"at": ISO, "level": n, "ruthless": bool, "passives":
{...}}`` mit ``passives`` so, wie die API es liefert.

**Bewusst offen für mehrere Bäume je Charakter.** Peter, 2026-10-04:
"Wir müssen uns auch eine Möglichkeit überlegen für den Baum verschiedene
Konfigurationen zur Verfügung zu stellen ... eine Konfiguration für
maximale Feuerresistenz oder maximalen Burst-Damage." Benannte Bäume
kommen später als ``"configs": {"<name>": {...}}`` neben ``current`` —
dieses Format braucht dafür keinen Versionssprung.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from poe_view import config
from poe_view.services.atomic_json import write_json
from poe_view.services.csv_export import sanitize_filename

log = logging.getLogger(__name__)

VERSION = 1
# Ein Respec am Tag über eine Liga sind ein paar hundert Einträge — mehr
# hebt niemand auf, und die Datei bleibt klein.
MAX_HISTORY = 500
# Was den Baum ausmacht; ``jewel_data`` ändert sich mit jedem Jewel-Tausch,
# ist aber kein anderer Baum.
_KEYS = ("hashes", "hashes_ex", "mastery_effects", "bandit_choice",
         "pantheon_major", "pantheon_minor")


def path_for(account_name: str) -> Path:
    """Funktion statt Konstante (CLAUDE.md, "Tests")."""
    safe = sanitize_filename(account_name, fallback="account")
    return config.APP_DATA_DIR / f"passive-trees-{safe}.json"


def load(path: Path) -> dict:
    try:
        roh = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(roh, dict) or roh.get("version") != VERSION:
        return {}
    zeichen = roh.get("characters")
    return zeichen if isinstance(zeichen, dict) else {}


def save(path: Path, characters: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {"version": VERSION, "characters": characters})


def _signature(passives: dict) -> str:
    teile = {}
    for key in _KEYS:
        wert = passives.get(key)
        if key in ("hashes", "hashes_ex") and isinstance(wert, list):
            wert = sorted(wert)
        teile[key] = wert
    return json.dumps(teile, sort_keys=True, default=str)


def record(characters: dict, name: str, passives: dict, *, level: int,
           ruthless: bool, now: datetime | None = None) -> bool:
    """Den Baum eintragen; liefert, ob sich etwas geändert hat (dann muss
    gespeichert werden). Ein leeres ``passives`` (Feld fehlte) ändert
    nichts — sonst sähe ein Abruf ohne Baum aus wie ein Komplett-Respec."""
    if not passives:
        return False
    eintrag = characters.setdefault(name, {})
    alt = eintrag.get("current")
    if alt and _signature(alt.get("passives") or {}) == _signature(passives):
        # Nur der Stand drumherum (Level, Jewels) kann neu sein; dieselben
        # Knoten in anderer Reihenfolge sind keine Änderung.
        if (alt.get("level") != level
                or (alt.get("passives") or {}).get("jewel_data") != passives.get("jewel_data")):
            alt["level"] = level
            alt["passives"] = passives
            return True
        return False
    neu = {"at": (now or datetime.now()).isoformat(timespec="seconds"),
           "level": level, "ruthless": ruthless, "passives": passives}
    eintrag["current"] = neu
    verlauf = eintrag.setdefault("history", [])
    verlauf.append(dict(neu))   # eigene Kopie: "current" wird spaeter fortgeschrieben
    del verlauf[:-MAX_HISTORY]
    return True


def current(characters: dict, name: str) -> dict | None:
    eintrag = characters.get(name) or {}
    return eintrag.get("current")


# --- Benannte Konfigurationen (§4.60.1) ----------------------------------- #
#
# Peter, 2026-10-04: "eine Konfiguration für maximale Feuerresistenz oder
# maximalen Burst-Damage". Je Charakter unter "configs", ein Eintrag wie
# "current" plus "source" (woher: "current", "link", "pob", "edited",
# "copy") und, wenn gesetzt, "group" (§4.60.12: Gruppe nach Build) und
# "notes" (§4.60.13).

def configs(characters: dict, name: str) -> dict[str, dict]:
    return (characters.get(name) or {}).get("configs") or {}


def save_config(characters: dict, name: str, config_name: str, passives: dict, *,
                level: int, ruthless: bool, source: str,
                now: datetime | None = None, group: str | None = None,
                notes: str | None = None) -> None:
    """Anlegen oder überschreiben. ``group`` und ``notes``: None behält
    Gruppe bzw. Notizen einer überschriebenen Konfiguration ("Save to X"
    soll sie nicht verlieren), "" nimmt sie heraus."""
    config_name = config_name.strip()
    if not config_name:
        raise ValueError("Konfiguration ohne Namen")
    alle = characters.setdefault(name, {}).setdefault("configs", {})
    if group is None:
        group = (alle.get(config_name) or {}).get("group", "")
    if notes is None:
        notes = (alle.get(config_name) or {}).get("notes", "")
    eintrag = {"at": (now or datetime.now()).isoformat(timespec="seconds"),
               "level": level, "ruthless": ruthless, "source": source,
               "passives": passives}
    if group.strip():
        eintrag["group"] = group.strip()
    if notes.strip():
        eintrag["notes"] = notes
    alle[config_name] = eintrag


def set_notes(characters: dict, name: str, config_name: str, notes: str) -> bool:
    """Notizen einer Konfiguration (§4.60.13); True, wenn sich etwas
    änderte."""
    eintrag = configs(characters, name).get(config_name)
    if eintrag is None or eintrag.get("notes", "") == (notes if notes.strip() else ""):
        return False
    if notes.strip():
        eintrag["notes"] = notes
    else:
        eintrag.pop("notes", None)
    return True


def group_of(characters: dict, name: str, config_name: str) -> str:
    return (configs(characters, name).get(config_name) or {}).get("group", "")


def set_group(characters: dict, name: str, config_names, group: str) -> int:
    """Konfigurationen in eine Gruppe verschieben ("" = keine); gibt die
    Zahl der geänderten zurück."""
    alle, group, zahl = configs(characters, name), group.strip(), 0
    for config_name in config_names:
        eintrag = alle.get(config_name)
        if eintrag is None or eintrag.get("group", "") == group:
            continue
        if group:
            eintrag["group"] = group
        else:
            eintrag.pop("group", None)
        zahl += 1
    return zahl


def groups(characters: dict, name: str) -> list[str]:
    return sorted({e["group"] for e in configs(characters, name).values() if e.get("group")})


def delete_config(characters: dict, name: str, config_name: str) -> bool:
    return configs(characters, name).pop(config_name, None) is not None


def rename_config(characters: dict, name: str, old: str, new: str) -> bool:
    """Umbenennen; ein vorhandener Name wird nicht überschrieben."""
    alle = configs(characters, name)
    new = new.strip()
    if old not in alle or not new or new in alle:
        return False
    alle[new] = alle.pop(old)
    return True


def history(characters: dict, name: str) -> list[dict]:
    return list((characters.get(name) or {}).get("history") or ())
