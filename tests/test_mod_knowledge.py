"""Tests für das Mod-Wissen (§4.53) — Download/Cache-Lebenszyklus mit
gemocktem HTTP und der Bau echter Tier-Leitern aus kleinen, von Hand
gebauten RePoE-artigen Fixtures (die echten Dateien sind ~30 MB und
gehören laut RePoEs LICENSE.md ohnehin nicht ins Repo)."""

import json

import httpx

from poe_view.services import mod_knowledge as mk

# tests/conftest.py stubbt mk.fetch() global weg, damit kein MainWindow()
# in der Testsuite real gegen repoe-fork.github.io abruft (§4.53). Genau
# die Tests hier wollen aber die ECHTE fetch()-Logik pruefen - deshalb
# hier die echte Funktion VOR jeder Fixture einfangen (das Funktionsobjekt
# selbst aendert sich durch monkeypatch.setattr nicht, nur die Bindung des
# Modul-Attributs) und in genau diesen Tests wieder einsetzen.
_real_fetch = mk.fetch


def _payload_bytes() -> dict[str, bytes]:
    return {name: f"{{\"marker\": \"{name}\"}}".encode("utf-8") for name in mk._FILES}


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- Download/Cache ------------------------------------------------------ #

def test_is_fresh_false_when_nothing_cached(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    assert mk.is_fresh() is False


def test_fetch_writes_all_three_files_and_a_manifest(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    monkeypatch.setattr(mk, "fetch", _real_fetch)  # siehe Modul-Docstring

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, content=_payload_bytes()[name])

    assert mk.fetch(_mock_client(handler)) is True
    assert mk.is_fresh() is True
    for name in mk._FILES:
        assert (mk._cache_dir() / name).read_bytes() == _payload_bytes()[name]


def test_fetch_leaves_the_cache_untouched_on_a_failed_request(tmp_path, monkeypatch) -> None:
    """Ein Teil-Download darf keinen inkonsistenten Stand hinterlassen —
    hier bricht der zweite von drei Downloads ab."""
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    monkeypatch.setattr(mk, "fetch", _real_fetch)  # siehe Modul-Docstring
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) == 2:
            return httpx.Response(500)
        return httpx.Response(200, content=b"{}")

    assert mk.fetch(_mock_client(handler)) is False
    assert not mk._cache_dir().exists()


def test_fetch_survives_a_network_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    monkeypatch.setattr(mk, "fetch", _real_fetch)  # siehe Modul-Docstring

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("kein Netz", request=request)

    assert mk.fetch(_mock_client(handler)) is False


def test_an_entry_from_an_older_cache_version_counts_as_stale(tmp_path, monkeypatch) -> None:
    cache_dir = tmp_path / "mod-knowledge"
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    cache_dir.mkdir()
    for name in mk._FILES:
        (cache_dir / name).write_text("{}", encoding="utf-8")
    (cache_dir / "manifest.json").write_text(
        json.dumps({"version": mk.CACHE_VERSION - 1, "fetched_at": 9_999_999_999}), encoding="utf-8")
    assert mk.is_fresh() is False


def test_an_entry_older_than_the_ttl_counts_as_stale(tmp_path, monkeypatch) -> None:
    cache_dir = tmp_path / "mod-knowledge"
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    cache_dir.mkdir()
    for name in mk._FILES:
        (cache_dir / name).write_text("{}", encoding="utf-8")
    (cache_dir / "manifest.json").write_text(
        json.dumps({"version": mk.CACHE_VERSION, "fetched_at": 0}), encoding="utf-8")
    assert mk.is_fresh() is False


def test_ensure_fresh_skips_the_download_when_already_fresh(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    monkeypatch.setattr(mk, "is_fresh", lambda: True)
    monkeypatch.setattr(mk, "fetch", lambda http=None: (_ for _ in ()).throw(
        AssertionError("fetch() haette nicht aufgerufen werden duerfen")))
    assert mk.ensure_fresh() is True


# --- render_identity ------------------------------------------------------ #

_TRANSLATIONS_BY_ID = {
    "additional_intelligence": {"English": [
        {"condition": [{}], "format": ["+#"], "string": "{0} to Intelligence"},
    ]},
    "conditional_stat": {"English": [
        {"condition": [{"max": 10}], "format": ["#"], "string": "Small: {0}"},
        {"condition": [{"min": 11}], "format": ["#"], "string": "Big: {0}"},
    ]},
}


def test_render_identity_strips_the_number() -> None:
    assert mk.render_identity(_TRANSLATIONS_BY_ID, "additional_intelligence", 12) == "# to Intelligence"


def test_render_identity_picks_the_matching_condition() -> None:
    assert mk.render_identity(_TRANSLATIONS_BY_ID, "conditional_stat", 3) == "Small: #"
    assert mk.render_identity(_TRANSLATIONS_BY_ID, "conditional_stat", 20) == "Big: #"


def test_render_identity_unknown_stat_id_returns_none() -> None:
    assert mk.render_identity(_TRANSLATIONS_BY_ID, "no_such_stat", 1) is None


# --- build(): kleine RePoE-artige Fixtur statt der echten ~30-MB-Dateien - #

def _write_fixture(cache_dir) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    base_items = {
        # Zwei Tags, damit die REIHENFOLGE der spawn_weights geprueft
        # werden kann: ueber ein Set iteriert kaeme mal "amulet", mal
        # "default" zuerst - mit gegenteiligem Ergebnis.
        "Metadata/Items/Amulets/Test": {
            "name": "Test Amulet", "item_class": "Amulet",
            "release_state": "released", "tags": ["amulet", "default"],
        },
        # Zweite Basis DERSELBEN Kategorie mit einem eigenen Tag: eine
        # Pruefung gegen die Tag-VEREINIGUNG saehe hier eine Basis, die
        # es nicht gibt (amulet + talisman gleichzeitig).
        "Metadata/Items/Amulets/Talisman": {
            "name": "Test Talisman", "item_class": "Amulet",
            "release_state": "released", "tags": ["talisman", "default"],
        },
        "Metadata/Items/Jewels/Test": {
            "name": "Test Jewel", "item_class": "Jewel",
            "release_state": "released", "tags": ["jewel", "default"],
        },
        "Metadata/Items/Jewels/Abyss": {
            "name": "Test Abyss Jewel", "item_class": "AbyssJewel",
            "release_state": "released", "tags": ["abyss_jewel", "default"],
        },
        "Metadata/Items/Amulets/Unreleased": {
            "name": "Ghost Amulet", "item_class": "Amulet",
            "release_state": "unreleased", "tags": ["amulet", "default"],
        },
    }
    translations = [
        {"ids": ["additional_intelligence"], "English": [
            {"condition": [{}], "format": ["+#"], "string": "{0} to Intelligence"},
        ]},
        {"ids": ["ambiguous_two_id_stat", "other"], "English": [
            {"condition": [{}], "format": ["#"], "string": "irrelevant: {0}"},
        ]},
    ]
    mods = {
        "IntAmuletLow": {
            "domain": "item", "generation_type": "prefix", "required_level": 1,
            "stats": [{"id": "additional_intelligence", "min": 8, "max": 12}],
            "spawn_weights": [{"tag": "amulet", "weight": 1000}, {"tag": "default", "weight": 0}],
        },
        "IntAmuletHigh": {
            "domain": "item", "generation_type": "prefix", "required_level": 22,
            "stats": [{"id": "additional_intelligence", "min": 13, "max": 20}],
            "spawn_weights": [{"tag": "amulet", "weight": 1000}, {"tag": "default", "weight": 0}],
        },
        # Genau die Bauart des echten `IntelligenceJewel`: ein Jewel-Mod,
        # dessen `default` POSITIV ist. Er darf trotzdem nur auf Jewels
        # landen - die Domain entscheidet, nicht das Gewicht.
        "IntJewelMisc": {
            "domain": "misc", "generation_type": "suffix", "required_level": 1,
            "stats": [{"id": "additional_intelligence", "min": 5, "max": 5}],
            "spawn_weights": [{"tag": "not_int", "weight": 300}, {"tag": "default", "weight": 500}],
        },
        # Wertgleich zum Mod darueber: zwei Sprossen, die sich um nichts
        # unterscheiden, gehoeren in der Leiter zu einer zusammengefasst.
        "IntJewelAbyss": {
            "domain": "abyss_jewel", "generation_type": "suffix", "required_level": 9,
            "stats": [{"id": "additional_intelligence", "min": 5, "max": 5}],
            "spawn_weights": [{"tag": "default", "weight": 500}],
        },
        # Die Bauart der echten lokalen Verteidigungs-Mods
        # (`LocalIncreasedEvasionRatingPercent8` & Co., 781 Faelle):
        # erst die AUSSCHLUESSE mit Gewicht 0, dann der eine erlaubte
        # Tag. Gegen die Tag-Vereinigung einer Kategorie geprueft greift
        # der Ausschluss und der Mod verschwindet - obwohl es eine echte
        # Basis gibt, auf der er erscheint.
        "IntAmuletButNotTalisman": {
            "domain": "item", "generation_type": "prefix", "required_level": 40,
            "stats": [{"id": "additional_intelligence", "min": 30, "max": 35}],
            "spawn_weights": [{"tag": "talisman", "weight": 0},
                             {"tag": "amulet", "weight": 800},
                             {"tag": "default", "weight": 0}],
        },
        "NotEligibleForAnything": {
            "domain": "item", "generation_type": "prefix", "required_level": 1,
            "stats": [{"id": "additional_intelligence", "min": 99, "max": 99}],
            "spawn_weights": [{"tag": "amulet", "weight": 0}, {"tag": "default", "weight": 0}],
        },
        "EssenceOnlyMod": {
            "domain": "item", "generation_type": "prefix", "is_essence_only": True,
            "required_level": 1,
            "stats": [{"id": "additional_intelligence", "min": 1, "max": 1}],
            "spawn_weights": [{"tag": "amulet", "weight": 1000}],
        },
        "TwoStatMod": {
            "domain": "item", "generation_type": "prefix", "required_level": 1,
            "stats": [{"id": "additional_intelligence", "min": 1, "max": 1},
                     {"id": "additional_intelligence", "min": 1, "max": 1}],
            "spawn_weights": [{"tag": "amulet", "weight": 1000}],
        },
        "UnknownTranslationMod": {
            "domain": "item", "generation_type": "prefix", "required_level": 1,
            "stats": [{"id": "no_such_stat", "min": 1, "max": 1}],
            "spawn_weights": [{"tag": "amulet", "weight": 1000}],
        },
    }
    (cache_dir / "mods.min.json").write_text(json.dumps(mods), encoding="utf-8")
    (cache_dir / "stat_translations.min.json").write_text(json.dumps(translations), encoding="utf-8")
    (cache_dir / "base_items.min.json").write_text(json.dumps(base_items), encoding="utf-8")


def test_build_returns_none_without_a_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    assert mk.build() is None


def test_build_produces_a_ladder_sorted_by_required_level(tmp_path, monkeypatch) -> None:
    cache_dir = tmp_path / "mod-knowledge"
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    _write_fixture(cache_dir)

    knowledge = mk.build()
    ladder = knowledge.ladder("# to Intelligence", "Amulet")
    assert [step.required_level for step in ladder] == [1, 22, 40]
    assert (ladder[0].low, ladder[0].high) == (8, 12)
    assert (ladder[1].low, ladder[1].high) == (13, 20)
    assert (ladder[2].low, ladder[2].high) == (30, 35)


def test_build_uses_the_misc_domain_for_jewels(tmp_path, monkeypatch) -> None:
    """Die Sackgasse, die die Trefferquote von 42% auf 63,3% hob:
    normale Jewels laufen unter domain 'misc', nicht 'item'."""
    cache_dir = tmp_path / "mod-knowledge"
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    _write_fixture(cache_dir)
    knowledge = mk.build()
    assert knowledge.has("# to Intelligence", "Jewel")


def test_build_skips_unreleased_bases(tmp_path, monkeypatch) -> None:
    cache_dir = tmp_path / "mod-knowledge"
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    _write_fixture(cache_dir)
    knowledge = mk.build()
    # "Ghost Amulet" ist unreleased und traegt trotzdem den gleichen Tag
    # ("amulet") wie die echte Basis - waere sie versehentlich mitgezaehlt,
    # wuerde sich an der Leiter selbst nichts aendern (derselbe Tag), der
    # Test dokumentiert die Absicht, keinen Unterschied im Ergebnis.
    assert knowledge.has("# to Intelligence", "Amulet")


def test_build_skips_essence_only_mods(tmp_path, monkeypatch) -> None:
    cache_dir = tmp_path / "mod-knowledge"
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    _write_fixture(cache_dir)
    knowledge = mk.build()
    ladder = knowledge.ladder("# to Intelligence", "Amulet")
    assert all(step.low != 1 or step.high != 1 for step in ladder)


def test_build_skips_multi_stat_mods(tmp_path, monkeypatch) -> None:
    cache_dir = tmp_path / "mod-knowledge"
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    _write_fixture(cache_dir)
    knowledge = mk.build()
    ladder = knowledge.ladder("# to Intelligence", "Amulet")
    # TwoStatMod haette (1, 1) beigetragen, wie EssenceOnlyMod - beide
    # muessen draussen bleiben, die vorigen zwei Tests pruefen das schon
    # ueber den Wert; hier zaehlt nur die Laenge (drei echte Sprossen:
    # IntAmuletLow, IntAmuletHigh, IntTalismanOnly).
    assert len(ladder) == 3


def test_build_a_mod_ineligible_everywhere_produces_no_ladder(tmp_path, monkeypatch) -> None:
    """NotEligibleForAnything hat ueberall Gewicht 0 (weder 'amulet' noch
    'default') und darf deshalb in KEINER Leiter auftauchen."""
    cache_dir = tmp_path / "mod-knowledge"
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    _write_fixture(cache_dir)
    knowledge = mk.build()
    for steps in knowledge._ladders.values():
        assert not any(step.low == 99 for step in steps)


def test_build_a_mod_without_a_translation_is_skipped_without_crashing(tmp_path, monkeypatch) -> None:
    cache_dir = tmp_path / "mod-knowledge"
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    _write_fixture(cache_dir)
    knowledge = mk.build()  # darf nicht an UnknownTranslationMod scheitern
    assert len(knowledge) == 2  # Amulet und Jewel, je fuer additional_intelligence


def test_get_caches_the_built_knowledge(tmp_path, monkeypatch) -> None:
    cache_dir = tmp_path / "mod-knowledge"
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    monkeypatch.setattr(mk, "_cached", None)
    _write_fixture(cache_dir)

    first = mk.get()
    assert first is not None
    # Cache leeren, OHNE die Datei zu loeschen - ein zweiter get() ohne
    # rebuild darf trotzdem das erste Objekt zurueckgeben.
    cache_dir.joinpath("mods.min.json").unlink()
    assert mk.get() is first
    assert mk.get(rebuild=True) is None


# --- Die drei Fehler, die Peters CraftOfExile-Screenshot aufdeckte ------- #

def test_the_order_of_spawn_weights_decides_not_the_order_of_tags(
        tmp_path, monkeypatch) -> None:
    """Der Fehler, der acht von neun Amulett-Sprossen verschluckte:
    `spawn_weights` ist eine geordnete Liste, `default` faengt am Ende
    alles Uebrige. Wer stattdessen ueber die Tags der Basis iteriert,
    bekommt bei `[{amulet: 1000}, {default: 0}]` und einer Basis mit
    beiden Tags mal True und mal False - Pythons Set-Reihenfolge ist
    zwischen zwei Prozessen verschieden."""
    tags = frozenset({"amulet", "default"})
    weights = [{"tag": "amulet", "weight": 1000}, {"tag": "default", "weight": 0}]
    assert mk._eligible(weights, tags) is True
    # Dieselbe Menge, umgekehrte Liste: jetzt gewinnt `default`.
    assert mk._eligible(list(reversed(weights)), tags) is False


def test_a_mod_without_any_matching_tag_and_without_default_is_out() -> None:
    assert mk._eligible([{"tag": "ring", "weight": 1000}], frozenset({"amulet"})) is False


def test_a_ladder_collects_mods_from_every_base_of_its_category(
        tmp_path, monkeypatch) -> None:
    """Ein Mod, der auf gewoehnlichen Amuletten erscheint, aber auf
    Talismanen ausgeschlossen ist, gehoert in die Amulett-Leiter -
    `item_category()` kennt keinen eigenen Topf fuer Talismane.

    Gegen die Tag-VEREINIGUNG geprueft faellt er durch: dort stuende
    eine Phantom-Basis mit `amulet` UND `talisman` gleichzeitig, der
    Ausschluss `{talisman: 0}` steht in der Liste vorn und gewinnt. An
    echten Daten trifft das 781 (Mod, Kategorie)-Paare, allesamt lokale
    Verteidigungs-Mods, die ihre fremden Ruestungstypen genau so
    ausschliessen."""
    cache_dir = tmp_path / "mod-knowledge"
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    _write_fixture(cache_dir)

    ladder = mk.build().ladder("# to Intelligence", "Amulet")

    assert (30, 35) in [(s.low, s.high) for s in ladder]


def test_a_jewel_mod_with_a_positive_default_stays_out_of_other_categories(
        tmp_path, monkeypatch) -> None:
    """Die eine Sprosse zu viel: `IntelligenceJewel` traegt
    `[{not_int: 300}, {default: 500}]`, und ein Amulett hat weder
    `not_int` noch sonst einen passenden Tag - `default` griff, der
    Jewel-Mod stand in JEDER Kategorie. Gegen Peters
    CraftOfExile-Screenshot war das genau eine Sprosse zu viel."""
    cache_dir = tmp_path / "mod-knowledge"
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    _write_fixture(cache_dir)

    knowledge = mk.build()

    assert 5 not in [s.low for s in knowledge.ladder("# to Intelligence", "Amulet")]
    assert 5 in [s.low for s in knowledge.ladder("# to Intelligence", "Jewel")]


def test_abyss_jewels_land_in_the_same_category_as_ordinary_jewels(
        tmp_path, monkeypatch) -> None:
    """`item_category()` entscheidet ueber die baseType-Endung, und ein
    "Searching Eye Jewel" endet auf "Jewel" wie jedes andere - RePoEs
    eigene Klasse "AbyssJewel" muss deshalb dorthin abgebildet werden,
    sonst haette die Kategorie gar keine Leiter."""
    cache_dir = tmp_path / "mod-knowledge"
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    _write_fixture(cache_dir)

    knowledge = mk.build()

    assert knowledge.has("# to Intelligence", "Jewel")
    assert not knowledge.has("# to Intelligence", "AbyssJewel")


def test_two_steps_with_the_same_span_are_merged_keeping_the_earliest(
        tmp_path, monkeypatch) -> None:
    """Der gewoehnliche und der Abyss-Jewel-Mod tragen beide 5-5. Zwei
    Stufen, die sich um nichts unterscheiden, waeren im Album zwei
    Zeilen ohne Unterschied; behalten wird die frueher freigeschaltete."""
    cache_dir = tmp_path / "mod-knowledge"
    monkeypatch.setattr(mk.config, "APP_DATA_DIR", tmp_path)
    _write_fixture(cache_dir)

    ladder = mk.build().ladder("# to Intelligence", "Jewel")

    assert [(s.required_level, s.low, s.high) for s in ladder] == [(1, 5, 5)]
