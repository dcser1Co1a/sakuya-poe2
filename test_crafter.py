import base64
import io
import json
import re
import http.client
import queue
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from PIL import Image

import numpy as np
from PIL import ImageColor

import sakura
import tray
import crafter
from crafter import (
    FRACTURE_MIN_ILVL,
    HIT,
    NEW_BASE,
    NONE,
    LOCKED_JUNK,
    OTHER_SECTION,
    PRICE_KINDS,
    WRONG_TIER,
    Action,
    Database,
    Essence,
    Mod,
    Page,
    Planner,
    State,
    apply_league,
    build_bases,
    cheaper_goals,
    clean_text,
    describe_change,
    explain_action,
    extract_mods_view,
    format_cost,
    format_price,
    hotkey_from_event,
    hotkey_label,
    hotkey_problem,
    icon_path_from_ninja,
    league_candidates,
    league_is_due,
    make_icon,
    make_template,
    make_want,
    matches_search,
    merge_overview,
    merge_route,
    name_key,
    now_text,
    price_section,
    price_source,
    prices_in_exalted,
    read_prices,
    sections_due,
    tab_icon_item,
    update_prices_once,
    write_json,
    normalize_essences,
    normalize_mod,
    normalize_page,
    parse_item,
    read_names,
    resolve_weights,
    state_of_mods,
    validate_wants,
)


def make_mod(name, side, group, level, weight, template=None):
    template = template or group
    return Mod(name, side, level, (group,), weight, True, f"{template} {name}", template)


def build_page():
    return Page("Test", [
        make_mod("Good1", "prefix", "Damage", 80, 100),
        make_mod("Good2", "prefix", "Damage", 50, 300),
        make_mod("Good3", "prefix", "Damage", 1, 600),
        make_mod("Other", "prefix", "Other", 1, 1000),
        make_mod("Light", "prefix", "Light", 30, 500),
        make_mod("Speed", "suffix", "Speed", 1, 1000),
        make_mod("Res", "suffix", "Res", 60, 1000),
    ])


def want(page, template, tier=None, ilvl=82):
    ladder = next(l for l in page.ladders if l.template == template)
    return make_want(ladder, tier, ilvl)


EMPTY = State("normal", (NONE,), 0, 0)
PRICES = {"Orb of Transmutation": 1, "Orb of Augmentation": 1, "Regal Orb": 1, "Exalted Orb": 1, "Chaos Orb": 10,
          "Orb of Annulment": 20, "Omen of Sinistral Exaltation": 5, "Omen of Dextral Exaltation": 5}


class DataTests(unittest.TestCase):
    def test_extract_and_normalize(self):
        raw = {"Name": "Dazzling", "Level": "60", "ModGenerationTypeID": "1", "ModFamilyList": ["F"], "DropChance": "1000",
               "str": "<span class='mod-value'>+(61<span class=\"ndash\">—</span>73)</span> to <a href='x'>Energy Shield</a>"}
        mod = normalize_mod(extract_mods_view("x new ModsView(" + json.dumps({"normal": [raw]}) + "); y")["normal"][0])
        self.assertEqual((mod["text"], mod["template"]), ("+(61-73) to Energy Shield", "+# to Energy Shield"))
        self.assertEqual((mod["side"], mod["level"], mod["weight"]), ("prefix", 60, 1000))

    def test_changed_layout_is_reported(self):
        with self.assertRaises(ValueError):
            extract_mods_view("<html></html>")

    def test_template_and_text(self):
        self.assertEqual(make_template("Adds (1-2) to (4-5) Physical Damage"), "Adds # to # Physical Damage")
        self.assertEqual(clean_text("A<br>B"), "A / B")

    def test_bases_match_comma_separated_tags(self):
        pages = {"S": {"item_class": "Shield", "tag": "str_armour,str_shield"}, "B": {"item_class": "Bow", "tag": None}}
        common = {"domain": "item", "release_state": "released"}
        raw = {"a": {**common, "name": "Shield", "item_class": "Shield", "tags": ["str_shield"]},
               "b": {**common, "name": "Bow", "item_class": "Bow", "tags": []},
               "c": {**common, "release_state": "legacy", "name": "Old", "item_class": "Bow", "tags": []},
               "d": {**common, "name": "Ring", "item_class": "Ring", "tags": []},
               "e": {**common, "name": "[DNT] Bow", "item_class": "Bow", "tags": []}}
        self.assertEqual(set(build_bases(raw, pages)), {"Shield", "Bow"})

    def test_newest_league_comes_first_even_if_not_indexed(self):
        state = {"economyLeagues": [
            {"name": "Standard", "indexed": True, "hardcore": False},
            {"name": "Forbidden Rites", "indexed": False, "hardcore": False},
            {"name": "HC Forbidden Rites", "indexed": False, "hardcore": True},
            {"name": "Runes of Aldur", "indexed": True, "hardcore": False}]}
        self.assertEqual(league_candidates(state), ["Forbidden Rites", "Runes of Aldur", "Standard"])

    OVERVIEW = {"core": {"primary": "divine", "rates": {"exalted": 500}, "items": [{"id": "divine", "name": "Divine Orb"}]},
                "items": [{"id": "chaos", "name": "Chaos Orb"}],
                "lines": [{"id": "divine", "primaryValue": 1}, {"id": "chaos", "primaryValue": 0.1}]}

    def test_prices_follow_the_divine_rate(self):
        stored = merge_overview({"league": "L"}, self.OVERVIEW, "Currency")
        self.assertEqual(stored["exalted_per_divine"], 500)
        self.assertAlmostEqual(stored["prices_in_divine"]["Chaos Orb"], 0.1)
        self.assertAlmostEqual(prices_in_exalted(stored)["Chaos Orb"], 50)
        # The Exalted price moves with the rate while the Divine price stays.
        moved = merge_overview(stored, {**self.OVERVIEW, "core": {**self.OVERVIEW["core"], "rates": {"exalted": 700}}}, "Currency")
        self.assertAlmostEqual(prices_in_exalted(moved)["Chaos Orb"], 70)

    def test_other_primary_currency_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "не в Divine"):
            merge_overview({"league": "L"}, {**self.OVERVIEW, "core": {**self.OVERVIEW["core"], "primary": "chaos"}}, "Currency")

    def test_empty_league_is_skipped(self):
        stored = merge_overview({"league": "New"}, {"core": {"primary": "divine"}, "items": [], "lines": []}, "Currency")
        self.assertIsNone(stored["league"])
        self.assertTrue(league_is_due(stored))
        state = {"economyLeagues": [{"name": "New", "hardcore": False}, {"name": "Old", "hardcore": False}]}
        self.assertEqual(apply_league({**stored, "league_checked": now_text()}, state)["league"], "Old")

    def test_old_price_file_is_converted(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(crafter, "PRICES_PATH", Path(folder) / "prices.json"):
            write_json(crafter.PRICES_PATH, {"exalted_per_divine": 500, "prices_in_exalted": {"Chaos Orb": 50}})
            self.assertAlmostEqual(read_prices()["prices_in_divine"]["Chaos Orb"], 0.1)

    def test_icon_path_comes_from_ninja_link(self):
        link = "/gen/image/WzI1LDE0LHsiZiI6IjJESXRlbXMvQ3VycmVuY3kvQ3VycmVuY3lNb2RWYWx1ZXMiLCJzY2FsZSI6MSwicmVhbG0iOiJwb2UyIn1d/2986e220b3/CurrencyModValues.png"
        self.assertEqual(icon_path_from_ninja(link), "Art/2DItems/Currency/CurrencyModValues")
        self.assertEqual(icon_path_from_ninja(""), "")
        self.assertEqual(icon_path_from_ninja("/gen/image/not-base64/x/y.png"), "")

    def test_icon_is_a_small_square_png(self):
        source = io.BytesIO()
        Image.new("RGBA", (212, 100), (255, 0, 0, 255)).save(source, "PNG")
        result = Image.open(io.BytesIO(base64.b64decode(make_icon(source.getvalue()))))
        self.assertEqual((result.format, result.size), ("PNG", (48, 48)))

    def test_chaos_rate_and_details_are_stored(self):
        overview = {**self.OVERVIEW, "core": {**self.OVERVIEW["core"], "rates": {"exalted": 500, "chaos": 10}}}
        overview = {**overview, "lines": [{"id": "chaos", "primaryValue": 0.1, "volumePrimaryValue": 7, "sparkline": {"totalChange": -5.0, "data": [1, 2]}}]}
        stored = merge_overview({"league": "L"}, overview, "Currency")
        self.assertEqual(stored["chaos_per_divine"], 10)
        self.assertEqual(stored["changes"]["Chaos Orb"], -5.0)
        self.assertEqual(stored["sparklines"]["Chaos Orb"], [1, 2])
        self.assertEqual(stored["volumes"]["Chaos Orb"], 7)
        self.assertEqual(stored["kinds"]["Chaos Orb"], "Currency")

    def test_price_sections_and_format(self):
        stored = {"kinds": {"Mirror of Kalandra": "Currency", "Head of the King": "Ritual"}}
        self.assertEqual(price_section("Mirror of Kalandra", stored), "Currency")
        self.assertEqual(price_section("Omen of Light", stored), "Ritual")
        self.assertEqual(price_section("Greater Essence of Ice", stored), "Essences")
        self.assertEqual(price_section("Head of the King", stored), "Ritual")
        currency = {"kinds": {"Chaos Orb": "Currency", "Hinekora's Lock": "Currency"}}
        self.assertEqual(price_section("Chaos Orb", currency), "Currency")
        self.assertEqual(price_section("Hinekora's Lock", currency), OTHER_SECTION)
        self.assertEqual(price_section("Vaal Siphoner", {}), OTHER_SECTION)
        self.assertEqual((price_source(OTHER_SECTION), price_source("Runes")), ("Currency", "Runes"))
        self.assertEqual(format_price(6169), "6 169")
        self.assertEqual(format_price(8.74), "8.74")
        self.assertEqual(format_price(1.0), "1")
        self.assertEqual(format_price(0.1013), "0.101")

    def test_update_runs_once_an_hour(self):
        self.assertEqual(sections_due({}), list(PRICE_KINDS))
        fresh = {"league": "L", "league_checked": now_text(), "updated": {kind: now_text() for kind in PRICE_KINDS}}
        self.assertEqual(sections_due(fresh), [])
        old = (datetime.now() - timedelta(minutes=61)).isoformat(timespec="seconds")
        stale = {**fresh, "updated": {**fresh["updated"], "Abyss": old, "Runes": old}}
        self.assertEqual(sections_due(stale), ["Abyss", "Runes"])  # the others were refreshed moments ago
        self.assertEqual(sections_due(stale, ("Abyss", "Currency")), ["Abyss"])  # and only the wanted ones count

    def test_a_pause_after_an_error_survives_restart(self):
        self.assertTrue(crafter.updates_paused({"retry_after": (datetime.now() + timedelta(minutes=30)).isoformat(timespec="seconds")}))
        self.assertFalse(crafter.updates_paused({"retry_after": (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds")}))
        self.assertFalse(crafter.updates_paused({}))

    def interest(self):
        self.now = 0.0
        return crafter.UpdateInterest(lambda: self.now)

    ALL_LOADED = {kind: "2026-11-02T00:00:00" for kind in PRICE_KINDS}

    def test_in_use_means_only_the_sections_crafting_needs(self):
        self.assertCountEqual(self.interest().wanted_sections(self.ALL_LOADED), crafter.CORE_SECTIONS)

    def test_a_section_never_loaded_is_fetched_once(self):
        loaded = {kind: stamp for kind, stamp in self.ALL_LOADED.items() if kind != "Runes"}
        self.assertIn("Runes", self.interest().wanted_sections(loaded))

    def test_what_is_on_screen_or_was_just_priced_is_wanted(self):
        interest = self.interest()
        interest.show(["Abyss", crafter.UNIQUE_KINDS[0]])
        interest.use("Runes")
        wanted = interest.wanted_sections(self.ALL_LOADED)
        self.assertIn("Abyss", wanted)
        self.assertIn("Runes", wanted)
        self.assertEqual(interest.wanted_uniques(), [crafter.UNIQUE_KINDS[0]])
        self.now += crafter.RECENT_USE_SECONDS + 1
        self.assertNotIn("Runes", interest.wanted_sections(self.ALL_LOADED))

    def test_nothing_is_asked_for_once_the_player_has_left(self):
        interest = self.interest()
        interest.show(["Abyss", crafter.UNIQUE_KINDS[0]])
        self.now += crafter.ACTIVE_SECONDS + 1
        self.assertEqual(interest.wanted_sections({}), [])
        self.assertEqual(interest.wanted_uniques(), [])
        interest.mark_active()
        self.assertTrue(interest.wake.is_set())
        self.assertIn("Currency", interest.wanted_sections(self.ALL_LOADED))

    def test_unchanged_data_is_not_sent_again(self):
        stored = {"league": "L", "league_checked": now_text(), "leagues": [{"name": "L", "hardcore": False}], "prices_in_divine": {"A": 1}, "etags": {"Runes": "old"}}
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(crafter, "PRICES_PATH", Path(folder) / "prices.json"), \
                mock.patch.object(crafter, "fetch_overview", return_value=(None, "old")) as fetch, mock.patch.object(crafter.time, "sleep"):
            result = update_prices_once(stored, mock.Mock(), ["Runes"])
        self.assertEqual(fetch.call_args.args[1], "old")
        self.assertEqual(result["prices_in_divine"], {"A": 1})
        self.assertIn("Runes", result["updated"])
        self.assertEqual(sections_due(result, ["Runes"]), [])

    def test_one_update_asks_each_section_once_without_retries(self):
        stored = {"league": "L", "league_checked": now_text(), "leagues": [{"name": "L", "hardcore": False}]}
        changed = mock.Mock()
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(crafter, "PRICES_PATH", Path(folder) / "prices.json"), \
                mock.patch.object(crafter, "fetch_overview", return_value=(self.OVERVIEW, "tag")) as fetch, mock.patch.object(crafter.time, "sleep") as sleep:
            result = update_prices_once(stored, changed)
        self.assertEqual(fetch.call_count, len(PRICE_KINDS))
        self.assertEqual(result["etags"]["Runes"], "tag")
        self.assertEqual({call.args[0].split("type=")[1] for call in fetch.call_args_list}, set(PRICE_KINDS))
        self.assertEqual(sleep.call_count, len(PRICE_KINDS))
        self.assertEqual(sections_due(result), [])
        self.assertEqual(changed.call_count, len(PRICE_KINDS))

    def test_tab_icons(self):
        stored = {"prices_in_divine": {"Rune A": 1, "Rune B": 2}, "kinds": {"Rune A": "Runes", "Rune B": "Runes"}, "volumes": {"Rune A": 50, "Rune B": 5}}
        self.assertEqual(tab_icon_item("Currency", stored), "Exalted Orb")
        self.assertEqual(tab_icon_item("Runes", stored), "Rune A")
        self.assertIsNone(tab_icon_item("Idols", stored))


class RussianDataTests(unittest.TestCase):
    RAW = {"Name": "of the Pupil", "Level": "1", "ModGenerationTypeID": "2", "ModFamilyList": ["Int"], "DropChance": "1000", "str": "+(5-8) to Intelligence"}
    OPT = {"ItemClassesCode": "Helmet", "tags": "int_armour"}

    def test_page_uses_russian_when_aligned(self):
        ru = {**self.RAW, "Name": "ученика", "str": "+(5-8) к интеллекту"}
        mod = normalize_page({"normal": [self.RAW], "opt": self.OPT}, {"normal": [ru]})["mods"][0]
        self.assertEqual((mod["ru_name"], mod["ru_text"]), ("ученика", "+(5-8) к интеллекту"))
        self.assertEqual(resolve_weights([mod])[0].shown_text, "+(5-8) к интеллекту")

    def test_essences_skip_random_results(self):
        entry = {"Level": "46", "ModGenerationTypeID": "1", "str": "x"}
        raw = [{**entry, "Name": "Body", "ModFamilyList": ["Life"]},
               {**entry, "Name": "Enhancement", "ModFamilyList": ["Def"]}, {**entry, "Name": "Enhancement", "ModFamilyList": ["Def"]},
               {**entry, "Name": "Infinite", "ModFamilyList": ["Str"]}, {**entry, "Name": "Infinite", "ModFamilyList": ["Dex"]}]
        ru = [{**e, "Name": "Тело" if e["Name"] == "Body" else e["Name"]} for e in raw]
        result = normalize_essences(raw, ru)
        self.assertEqual([e["name"] for e in result], ["Body", "Enhancement"])
        self.assertEqual((result[0]["ru_name"], result[0]["level"]), ("Тело", 46))

    def test_misaligned_page_falls_back_to_english(self):
        ru = {**self.RAW, "Level": "9", "Name": "чужой"}
        self.assertEqual(normalize_page({"normal": [self.RAW], "opt": self.OPT}, {"normal": [ru]})["mods"][0]["ru_name"], "of the Pupil")

    def test_read_names_uses_link_targets(self):
        html_text = '<a class="x" href="Ancestral_Tiara"><img src="a"/></a><a class="x" href="Ancestral_Tiara">Фамильная тиара</a>'
        self.assertEqual(read_names(html_text), {"ancestral tiara": "Фамильная тиара"})

    def test_read_names_skips_icons_inside_links(self):
        html_text = '<a href="Exalted_Orb"><img src="a"/>Сфера возвышения</a><a href="Exalted_Orb">другое</a>'
        self.assertEqual(read_names(html_text), {"exalted orb": "Сфера возвышения"})

    def test_read_names_ignores_apostrophes(self):
        html_text = '<a href="Scouts_Vest">Жилет</a><a href="Hexer%27s_Robe">Роба</a><a href="Sage&#039;s_Robe">Мантия</a><a href="#tab">Вкладка</a>'
        names = read_names(html_text)
        self.assertEqual({name_key("Scout's Vest"), name_key("Hexer's Robe"), name_key("Sage's Robe")}, set(names))
        self.assertEqual(names[name_key("Scout's Vest")], "Жилет")

    def test_grammatical_forms(self):
        forms = "<if:MS>{Светящийся}<elif:FS>{Светящаяся}<elif:NS>{Светящееся}"
        self.assertEqual(clean_text(forms + " щит"), "Светящийся щит")
        page = Page("P", [Mod("Radiating", "prefix", 1, ("G",), 1000, True, "t", "t", forms, "р")])
        self.assertIs(page.find_mod("prefix", "светящаяся"), page.mods[0])

    def test_find_mod_ignores_case_in_both_languages(self):
        page = Page("P", [Mod("of the Pupil", "suffix", 1, ("Int",), 1000, True, "t", "t", "ученика", "р")])
        self.assertIs(page.find_mod("suffix", "Ученика"), page.mods[0])
        self.assertIs(page.find_mod("suffix", "OF THE PUPIL"), page.mods[0])
        self.assertIsNone(page.find_mod("prefix", "ученика"))


class PageTests(unittest.TestCase):
    def test_tiers_and_pool(self):
        page = build_page()
        ladder = next(l for l in page.ladders if l.template == "Damage")
        self.assertEqual([m.name for m in ladder.mods], ["Good1", "Good2", "Good3"])
        self.assertEqual({m.name for m in page.pool(40)}, {"Good3", "Other", "Light", "Speed"})

    def test_floor_keeps_top_tier_of_low_modifier(self):
        self.assertEqual({m.name for m in build_page().pool(82, 50)}, {"Good1", "Good2", "Other", "Light", "Speed", "Res"})


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.page = build_page()

    def test_matches_analytic_cost(self):
        page = Page("P", [make_mod("Want", "prefix", "Want", 1, 100), make_mod("Junk", "prefix", "Junk", 1, 300)])
        plan = Planner(page, 82, [want(page, "Want")], {"Orb of Transmutation": 1, "Orb of Annulment": 100, NEW_BASE: 1}).solve(EMPTY)
        # Roll with 25% success, take a new base on a miss: V = 1 + 0.75 * (1 + V) = 7.
        self.assertAlmostEqual(plan.values[EMPTY], 7, places=4)
        self.assertAlmostEqual(plan.usage[NEW_BASE], 3, places=4)
        self.assertNotIn("Orb of Annulment", plan.usage)

    def test_annulment_is_not_offered_on_magic_items(self):
        planner = Planner(self.page, 82, [want(self.page, "Speed")], {**PRICES})
        magic = State("magic", (NONE,), 1, 0)
        self.assertEqual(planner.outcomes(magic, Action("annulment")), {})
        self.assertTrue(planner.outcomes(magic._replace(rarity="rare"), Action("annulment")))

    def test_essence_guarantees_wanted_mod(self):
        page = Page("P", [make_mod("Want", "prefix", "Want", 10, 100), make_mod("Junk", "prefix", "Junk", 1, 300)],
                     [Essence("Essence of Want", "prefix", 10, ("Want",))])
        planner = Planner(page, 82, [want(page, "Want")], {"Orb of Transmutation": 1, "Essence of Want": 2})
        plan = planner.solve(EMPTY)
        # Transmute hits 25% of the time, otherwise the essence finishes the item: 1 + 0.75 * 2.
        self.assertAlmostEqual(plan.values[EMPTY], 2.5, places=4)
        self.assertEqual(plan.policy[State("magic", (NONE,), 1, 0)].essence, "Essence of Want")

    def test_weak_or_unpriced_essence_gives_no_hit(self):
        page = Page("P", [make_mod("Top", "prefix", "Want", 80, 100, "Want"), make_mod("Low", "prefix", "Want", 1, 900, "Want")],
                     [Essence("Weak", "prefix", 40, ("Want",)), Essence("Free", "prefix", 80, ("Want",))])
        planner = Planner(page, 82, [want(page, "Want", 1)], {"Orb of Transmutation": 1, "Weak": 1})
        self.assertEqual(planner.essences, {"Weak": (0, WRONG_TIER)})

    def test_without_new_base_full_item_uses_chaos(self):
        prices = {"Orb of Transmutation": 1, "Orb of Augmentation": 1, "Regal Orb": 1, "Exalted Orb": 1, "Chaos Orb": 10, "Orb of Annulment": 50}
        planner = Planner(self.page, 82, [want(self.page, "Speed")], prices)
        plan = planner.solve(EMPTY)
        full = State("rare", (NONE,), 3, 3)
        self.assertEqual(plan.policy[full].currency, "chaos")
        self.assertNotIn(NEW_BASE, plan.usage)

    FRACTURE_PRICES = {**PRICES, "Fracturing Orb": 5}

    def fracture_planner(self):
        return Planner(self.page, 82, [want(self.page, "Damage"), want(self.page, "Speed")], self.FRACTURE_PRICES)

    def test_fracture_locks_a_random_mod_with_real_odds(self):
        planner = self.fracture_planner()
        outcomes = planner.outcomes(State("rare", (HIT, HIT), 1, 1), planner.fracture)
        self.assertAlmostEqual(outcomes[State("rare", (HIT, HIT), 1, 1, 0)], 0.25)
        self.assertAlmostEqual(outcomes[State("rare", (HIT, HIT), 1, 1, LOCKED_JUNK["prefix"])], 0.25)
        self.assertAlmostEqual(sum(outcomes.values()), 1)

    def test_a_desecrated_mod_counts_for_the_fracture_but_is_never_locked(self):
        from crafter import DESECRATED_JUNK, UNLOCKED
        planner = self.fracture_planner()
        junk_desecrated = State("rare", (HIT, HIT), 1, 1, UNLOCKED, DESECRATED_JUNK["prefix"])
        outcomes = planner.outcomes(junk_desecrated, planner.fracture)
        self.assertAlmostEqual(sum(outcomes.values()), 1)
        self.assertNotIn(junk_desecrated._replace(locked=LOCKED_JUNK["prefix"]), outcomes)
        self.assertAlmostEqual(outcomes[junk_desecrated._replace(locked=0)], 1 / 3)
        wanted_desecrated = State("rare", (HIT, HIT), 1, 1, UNLOCKED, 1)
        outcomes = planner.outcomes(wanted_desecrated, planner.fracture)
        self.assertAlmostEqual(sum(outcomes.values()), 1)
        self.assertNotIn(wanted_desecrated._replace(locked=0), outcomes)
        self.assertAlmostEqual(outcomes[wanted_desecrated._replace(locked=1)], 1 / 3)

    def test_the_sparse_solve_agrees_with_the_dense_one(self):
        import crafter
        rng = np.random.default_rng(5)
        count = 300
        rows, columns, chances = [], [], []
        for row in range(count):
            targets = rng.choice(count, size=4, replace=False)
            weights = rng.random(4)
            weights = weights / weights.sum() * 0.97  # every state leaves the chain a little, as a goal ends it
            rows += [row] * 4
            columns += list(targets)
            chances += list(weights)
        rows, columns, chances = np.array(rows), np.array(columns), np.array(chances)
        totals = rng.random(count) * 10
        matrix = np.eye(count)
        np.subtract.at(matrix, (rows, columns), chances)
        expected = np.linalg.solve(matrix, totals)
        np.testing.assert_allclose(crafter.solve_chain(rows, columns, chances, totals), expected, rtol=1e-8)
        np.testing.assert_allclose(crafter.solve_chain(rows, columns, chances, totals, expected * 0.9), expected, rtol=1e-8)

    def test_a_large_layer_gives_the_same_plan_sparse(self):
        import crafter
        wants = [want(self.page, "Damage"), want(self.page, "Speed")]
        start = State("normal", (NONE, NONE), 0, 0)
        dense = Planner(self.page, 82, wants, self.FRACTURE_PRICES).solve(start)
        with mock.patch.object(crafter, "DENSE_SOLVE_LIMIT", 1):
            sparse = Planner(self.page, 82, wants, self.FRACTURE_PRICES).solve(start)
        self.assertAlmostEqual(sparse.values[start], dense.values[start], places=6)
        self.assertEqual(sparse.policy, dense.policy)
        for name, count in dense.usage.items():
            self.assertAlmostEqual(sparse.usage[name], count, places=6)

    def test_the_lock_uses_the_best_of_each_orb_result(self):
        planner = self.fracture_planner()
        a, b, c, d = (State("rare", (status, NONE), 1, 1) for status in (HIT, WRONG_TIER, NONE, NONE))
        d = d._replace(junk_prefix=2)
        values = {a: 0.0, b: 50.0, c: 10.0, d: 100.0}
        orb_one, orb_two = Action("chaos"), Action("exalted")
        with mock.patch.object(planner, "cost", lambda action: {orb_one: 1.0, orb_two: 2.0}[action]):
            expected, spent, going, used, orb_cost = planner._best_preview([(orb_one, {a: 0.5, d: 0.5}), (orb_two, {c: 0.5, b: 0.5})], values.get)
        # orb one hits a (total 1) half the time; otherwise orb two gives c (12) or b (52), and b loses to d (101) never: 52 < 101
        self.assertAlmostEqual(going[a], 0.5)
        self.assertAlmostEqual(going[c], 0.25)
        self.assertAlmostEqual(going[b], 0.25)
        self.assertNotIn(d, going)
        self.assertAlmostEqual(spent, 0.5 * 1 + 0.5 * 2)
        self.assertAlmostEqual(expected, 0.25 * 10 + 0.25 * 50)
        self.assertAlmostEqual(used[orb_one], 0.5)
        self.assertAlmostEqual(orb_cost[c], 2.0)

    def test_the_lock_is_used_only_where_it_pays(self):
        from crafter import Plan
        wants = [want(self.page, "Damage"), want(self.page, "Speed")]
        start = State("normal", (NONE, NONE), 0, 0)
        prices = {**self.FRACTURE_PRICES, "Chaos Orb": 3, "Greater Chaos Orb": 4, "Exalted Orb": 2, "Greater Exalted Orb": 3, "Orb of Annulment": 4}
        without = Planner(self.page, 82, wants, prices).solve(start)
        dear = Planner(self.page, 82, wants, {**prices, "Hinekora's Lock": 10 ** 6})
        self.assertIsNotNone(dear.lock)
        dear_plan = dear.solve(start)
        self.assertNotIn("Hinekora's Lock", dear_plan.usage)
        self.assertAlmostEqual(dear_plan.values[start], without.values[start], places=6)
        cheap = Planner(self.page, 82, wants, {**prices, "Hinekora's Lock": 0.01})
        plan = cheap.solve(start)
        self.assertIn("Hinekora's Lock", plan.usage)
        self.assertLess(plan.values[start], without.values[start])
        for state, action in plan.policy.items():
            if action.family == "lock":
                outcomes = cheap.outcomes(state, action)
                self.assertAlmostEqual(sum(outcomes.values()), 1)
        self.assertIsNone(Planner(self.page, FRACTURE_MIN_ILVL - 1, [want(self.page, "Damage", None, 40)], {**prices, "Hinekora's Lock": 0.01}).lock)
        simulation = __import__("crafter").simulate_plan(plan, runs=3000, rng=__import__("random").Random(3))
        self.assertAlmostEqual(simulation.mean, plan.values[start], delta=plan.values[start] * 0.1)
        self.assertIsInstance(plan, Plan)

    def test_fracture_is_endgame_only(self):
        wants = [want(self.page, "Damage", None, 40), want(self.page, "Speed", None, 40)]
        self.assertIsNone(Planner(self.page, FRACTURE_MIN_ILVL - 1, wants, self.FRACTURE_PRICES).fracture)
        self.assertIsNotNone(Planner(self.page, FRACTURE_MIN_ILVL, wants, self.FRACTURE_PRICES).fracture)

    def test_fracture_rules(self):
        planner = self.fracture_planner()
        action = planner.fracture
        self.assertEqual(planner.outcomes(State("rare", (HIT, NONE), 2, 0), action), {}, "needs four mods")
        self.assertEqual(planner.outcomes(State("magic", (HIT, HIT), 1, 1), action), {}, "needs a rare item")
        self.assertEqual(planner.outcomes(State("rare", (HIT, HIT), 1, 1, 0), action), {}, "only one fracture")
        self.assertEqual(planner.outcomes(State("rare", (WRONG_TIER, HIT), 1, 1), action), {}, "a wrong tier could get stuck")

    def test_locked_mod_cannot_be_removed(self):
        planner = self.fracture_planner()
        state = State("rare", (HIT, NONE), 2, 0, 0)
        for new in planner.outcomes(state, Action("annulment")):
            self.assertEqual(new.status[0], HIT)
        junk = State("rare", (NONE, NONE), 1, 0, LOCKED_JUNK["prefix"])
        self.assertEqual(planner.outcomes(junk, Action("annulment")), {})

    def test_fracture_is_chosen_only_when_it_pays(self):
        cheap = self.fracture_planner().solve(State("normal", (NONE, NONE), 0, 0))
        expensive = Planner(self.page, 82, cheap.planner.wants, {**PRICES, "Fracturing Orb": 100000}).solve(State("normal", (NONE, NONE), 0, 0))
        self.assertNotIn("Fracturing Orb", expensive.usage)
        self.assertLessEqual(cheap.values[cheap.start], expensive.values[expensive.start] + 1e-6)

    def test_layers_match_cost_and_usage(self):
        plan = self.fracture_planner().solve(State("normal", (NONE, NONE), 0, 0))
        total = sum(count * plan.planner.prices[name] for name, count in plan.usage.items())
        self.assertAlmostEqual(total, plan.values[plan.start], places=4)

    def test_unwinnable_fractured_item_is_reported(self):
        planner = self.fracture_planner()
        with self.assertRaisesRegex(ValueError, "недостижима"):
            planner.solve(State("rare", (WRONG_TIER, NONE), 0, 0, 0))
        page = Page("P", [make_mod(f"M{i}", "prefix", f"G{i}", 1, 1000) for i in range(3)] + [make_mod("J", "prefix", "J", 1, 1000)])
        full = Planner(page, 82, [want(page, f"G{i}") for i in range(3)], PRICES)
        with self.assertRaisesRegex(ValueError, "недостижима"):
            full.solve(State("rare", (NONE, NONE, NONE), 1, 0, LOCKED_JUNK["prefix"]))

    def test_describe_change_shows_only_the_difference(self):
        wants = [want(self.page, "Damage"), want(self.page, "Speed")]
        old = State("rare", (HIT, NONE), 2, 1)
        damage, speed = wants[0].ladder.title, wants[1].ladder.title
        self.assertEqual(describe_change(old, old._replace(status=(HIT, HIT)), wants), f"✓ {speed}")
        self.assertEqual(describe_change(old, old._replace(status=(NONE, NONE), junk_suffix=2), wants), f"пропал: {damage}  •  лишний суффикс")
        self.assertEqual(describe_change(old, old._replace(junk_prefix=1), wants), "убран лишний префикс")
        self.assertEqual(describe_change(old, old, wants), "ничего полезного")
        self.assertEqual(describe_change(old, old._replace(locked=0), wants), f"закреплён: {damage}")

    def test_route_can_start_from_current_state(self):
        plan = self.fracture_planner().solve(State("normal", (NONE, NONE), 0, 0))
        later = State("rare", (HIT, NONE), 0, 0)
        self.assertEqual(plan.route(later)[0][0], plan.policy[later])

    def test_cheaper_goals_offer_lower_tier_and_fewer_mods(self):
        wants = [want(self.page, "Damage", 1), want(self.page, "Speed")]
        planner = Planner(self.page, 82, wants, PRICES)
        start = State("normal", (NONE, NONE), 0, 0)
        cost = planner.solve(start).values[start]
        options = cheaper_goals(self.page, 82, wants, PRICES, lambda w: State("normal", (NONE,) * len(w), 0, 0), cost)
        self.assertTrue(options)
        self.assertTrue(all(option["cost"] <= cost * 0.8 for option in options))
        self.assertLessEqual(len(options), 3)
        self.assertIn("→", options[0]["label"])  # a lower tier is offered before dropping a mod

    def test_merge_route_joins_repeated_steps(self):
        one, other = Action("exalted"), Action("chaos")
        self.assertEqual(merge_route([(one, 0.1), (one, 0.3), (other, 0.2), (one, 0.0)]), [(one, 2, 0.3), (other, 1, 0.2), (one, 1, 0.0)])

    def test_explain_action(self):
        fresh = State("rare", (NONE,), 0, 0)
        self.assertIn("Только префиксы", explain_action(Action("exalted", ("Omen of Sinistral Exaltation",)), fresh))
        self.assertIn("2 случайных", explain_action(Action("exalted", ("Omen of Greater Exaltation",)), fresh))
        self.assertIn("50+", explain_action(Action("perfect_exalted"), fresh))
        self.assertIn("Закреплённый", explain_action(Action("chaos"), fresh._replace(locked=0)))
        self.assertNotIn("Закреплённый", explain_action(Action("chaos"), fresh))
        for slug in crafter.CURRENCIES:
            self.assertTrue(explain_action(Action(slug), fresh))

    MODE_PRICES = {**PRICES, "Divine Orb": 100, "Perfect Exalted Orb": 50, "Fracturing Orb": 500, "Greater Exalted Orb": 3, "Orb of Annulment": 30}

    def test_budget_mode_skips_expensive_steps_but_keeps_chaos(self):
        wants = [want(self.page, "Damage", 2), want(self.page, "Speed")]
        prices = {**self.MODE_PRICES, "Chaos Orb": 40}  # above the limit on purpose
        planner = Planner(self.page, 82, wants, prices, "budget")
        names = {action.currency for action in planner.actions}
        self.assertNotIn("perfect_exalted", names)
        self.assertNotIn("annulment", names)
        self.assertIn("chaos", names)
        self.assertIn("exalted", names)
        self.assertIsNone(planner.fracture)
        plan = planner.solve(State("normal", (NONE, NONE), 0, 0))
        self.assertTrue(plan.policy)

    def test_endgame_mode_uses_fewer_actions_and_shows_real_spending(self):
        wants = [want(self.page, "Damage", 1), want(self.page, "Speed")]
        start = State("normal", (NONE, NONE), 0, 0)
        cheap = Planner(self.page, 82, wants, self.MODE_PRICES, "budget").solve(start)
        best = Planner(self.page, 82, wants, self.MODE_PRICES, "endgame").solve(start)
        self.assertLess(best.action_count, cheap.action_count)
        spent = sum(count * self.MODE_PRICES[name] for name, count in best.usage.items())
        self.assertAlmostEqual(best.values[start], spent, places=4)

    def test_action_count_skips_omens(self):
        plan = Planner(self.page, 82, [want(self.page, "Speed")], PRICES).solve(EMPTY)
        plan.usage = {"Exalted Orb": 3.0, "Omen of Sinistral Exaltation": 2.0}
        self.assertEqual(plan.action_count, 3.0)

    def test_state_reads_fractured_mod(self):
        wants = [want(self.page, "Damage"), want(self.page, "Speed")]
        mods = {m.name: m for m in self.page.mods}
        pairs = [("prefix", mods["Good1"]), ("suffix", mods["Res"])]
        self.assertEqual(state_of_mods("rare", pairs, wants, ("prefix", mods["Good1"])).locked, 0)
        self.assertEqual(state_of_mods("rare", pairs, wants, ("suffix", mods["Res"])).locked, LOCKED_JUNK["suffix"])

    def test_higher_tier_costs_more_and_tracks_wrong_tier(self):
        planner = lambda tier: Planner(self.page, 82, [want(self.page, "Damage", tier)], PRICES).solve(EMPTY)
        self.assertGreater(planner(1).values[EMPTY], planner(None).values[EMPTY])
        self.assertTrue(any(WRONG_TIER in state.status for state in planner(1).policy))

    def test_invalid_wants(self):
        with self.assertRaisesRegex(ValueError, "уровень предмета 80"):
            want(self.page, "Damage", 1, ilvl=70)
        with self.assertRaises(ValueError):
            validate_wants([])
        page = Page("P", [make_mod("A", "prefix", "G", 1, 1000, "One"), make_mod("B", "prefix", "G", 1, 1000, "Two")])
        with self.assertRaisesRegex(ValueError, "несовместимы"):
            validate_wants([want(page, "One"), want(page, "Two")])
        page = Page("P", [make_mod(f"M{i}", "prefix", f"G{i}", 1, 1000) for i in range(4)])
        with self.assertRaisesRegex(ValueError, "префикса"):
            validate_wants([want(page, f"G{i}") for i in range(4)])

    def test_unpriced_omen_is_not_used(self):
        planner = Planner(self.page, 82, [want(self.page, "Speed")], PRICES)
        self.assertNotIn("Omen of Sinistral Annulment", planner.solve(EMPTY).usage)

    def test_progress_lowers_cost_and_goal_is_free(self):
        wants = [want(self.page, "Damage"), want(self.page, "Speed")]
        planner = Planner(self.page, 82, wants, PRICES)
        fresh = State("normal", (NONE, NONE), 0, 0)
        partial = State("rare", (HIT, NONE), 0, 0)
        self.assertLess(planner.solve(partial).values[partial], planner.solve(fresh).values[fresh])
        self.assertEqual(planner.solve(State("rare", (HIT, HIT), 0, 0)).policy, {})

    def test_attempts_count_new_bases(self):
        page = Page("P", [make_mod("Want", "prefix", "Want", 1, 100), make_mod("Junk", "prefix", "Junk", 1, 300)])
        plan = Planner(page, 82, [want(page, "Want")], {"Orb of Transmutation": 1, NEW_BASE: 1}).solve(EMPTY)
        # A 25% roll takes 4 tries on average: the first base and 3 new ones.
        self.assertAlmostEqual(plan.attempts, 4, places=4)

    def test_route_starts_with_progress_chance(self):
        plan = Planner(self.page, 82, [want(self.page, "Damage"), want(self.page, "Speed")], PRICES).solve(State("normal", (NONE, NONE), 0, 0))
        self.assertGreater(plan.route()[0][1], 0)

    def test_state_of_mods(self):
        wants = [want(self.page, "Damage", 1), want(self.page, "Speed")]
        mods = {m.name: m for m in self.page.mods}
        state = state_of_mods("rare", [("prefix", mods["Good2"]), ("suffix", mods["Speed"]), ("prefix", mods["Other"]), ("suffix", None)], wants)
        self.assertEqual(state, State("rare", (WRONG_TIER, HIT), 1, 1))


class LanguageTests(unittest.TestCase):
    def tearDown(self):
        crafter.set_language("ru")

    def test_every_interface_text_has_english(self):
        source = Path(crafter.__file__).read_text(encoding="utf-8")
        used = set(re.findall(r'\bt\("((?:[^"\\\\]|\\\\.)*)"\)', source))
        self.assertGreater(len(used), 60)
        missing = [text for text in used if text.replace("\\\\n", "\\n") not in crafter.ENGLISH and re.search("[А-Яа-я]", text)]
        self.assertEqual(missing, [])

    def test_translations_keep_their_placeholders(self):
        for russian, english in crafter.ENGLISH.items():
            self.assertEqual(sorted(re.findall(r"{(\w+)}", russian)), sorted(re.findall(r"{(\w+)}", english)), russian)

    def test_switching_changes_names_and_mods(self):
        mod = Mod("of the Pupil", "suffix", 1, ("Int",), 1000, True, "+(5-8) to Intelligence", "+# to Intelligence", "ученика", "+(5-8) к интеллекту")
        crafter.currency_names["Exalted Orb"] = "Сфера возвышения"
        db = Database({"pages": {}, "game_version": "x", "bases": {"Tiara": {"page": "H", "ru": "Тиара"}}})
        crafter.currency_names["Exalted Orb"] = "Сфера возвышения"
        self.assertEqual((mod.shown_text, crafter.show_currency("Exalted Orb"), db.show_base("Tiara")), ("+(5-8) к интеллекту", "Сфера возвышения", "Тиара"))
        crafter.set_language("en")
        self.assertEqual((mod.shown_text, crafter.show_currency("Exalted Orb"), db.show_base("Tiara")), ("+(5-8) to Intelligence", "Exalted Orb", "Tiara"))
        self.assertEqual(crafter.show_currency(NEW_BASE), "New base")
        with self.assertRaisesRegex(ValueError, "Select"):
            validate_wants([])


class HotkeyTests(unittest.TestCase):
    HOTKEYS = {"copy": {"mods": 2, "vk": 0x45}, "toggle": {"mods": 2, "vk": 0x52}, "price": {"mods": 2, "vk": 0x44}}

    def test_labels(self):
        self.assertEqual(hotkey_label({"mods": 2, "vk": 0x45}), "Ctrl+E")
        self.assertEqual(hotkey_label({"mods": 3, "vk": 0x31}), "Ctrl+Alt+1")
        self.assertEqual(hotkey_label({"mods": 4, "vk": 0x70}), "Shift+F1")

    def test_event_uses_the_key_not_the_layout(self):
        self.assertEqual(hotkey_from_event(0x0004, 0x45), {"mods": 2, "vk": 0x45})
        self.assertEqual(hotkey_from_event(0x20005, 0x44), {"mods": 7, "vk": 0x44})
        self.assertEqual(hotkey_from_event(0x0008, 0x71), {"mods": 0, "vk": 0x71})  # Num Lock does not count

    def test_problems(self):
        self.assertIsNone(hotkey_problem({"mods": 2, "vk": 0x46}, "copy", self.HOTKEYS))
        self.assertIsNone(hotkey_problem({"mods": 0, "vk": 0x71}, "copy", self.HOTKEYS))
        self.assertIsNone(hotkey_problem({"mods": 2, "vk": 0x45}, "copy", self.HOTKEYS))
        self.assertIn("Ctrl", hotkey_problem({"mods": 0, "vk": 0x44}, "copy", self.HOTKEYS))
        self.assertIn("назначено", hotkey_problem({"mods": 2, "vk": 0x52}, "copy", self.HOTKEYS))
        self.assertIn("назначено", hotkey_problem({"mods": 2, "vk": 0x44}, "copy", self.HOTKEYS))
        self.assertIn("занято", hotkey_problem({"mods": 3, "vk": 0x43}, "copy", self.HOTKEYS))
        self.assertIn("занято", hotkey_problem({"mods": 2, "vk": 0x56}, "copy", self.HOTKEYS))


class SearchTests(unittest.TestCase):
    ADDS = "Добавляет от # до # урона от огня Adds # to # Fire Damage"

    def test_ignores_short_words_and_order(self):
        self.assertTrue(matches_search("добавляет от и до", self.ADDS))
        self.assertTrue(matches_search("огня добавляет", self.ADDS))

    def test_ignores_endings_case_and_yo(self):
        self.assertTrue(matches_search("Скорость атаки", "#% увеличение скорости атаки"))
        self.assertTrue(matches_search("огнём", self.ADDS))
        self.assertTrue(matches_search("FIRE", self.ADDS))

    def test_all_words_must_match(self):
        self.assertFalse(matches_search("добавляет холод", self.ADDS))
        self.assertFalse(matches_search("xyz", self.ADDS))

    def test_empty_query_shows_everything(self):
        self.assertTrue(matches_search("", self.ADDS))
        self.assertTrue(matches_search("  и  ", self.ADDS))


class ParseItemTests(unittest.TestCase):
    def setUp(self):
        self.db = Database({"pages": {}, "game_version": "x", "bases": {
            "Ancestral Tiara": {"page": "H", "ru": "Фамильная тиара"}, "Tiara": {"page": "H", "ru": "Тиара"}}})

    RUSSIAN = """Класс предмета: Шлемы
Редкость: Редкий
Гибельный венец
Фамильная тиара
--------
Уровень предмета: 82
--------
{ Префикс "Ослепляющий" (Уровень: 1) — Защита }
+70(61-73) к максимуму энергетического щита
{ Очернённое Суффикс "ученика" (Уровень: 8) — Атрибут }
+6(5-8) к интеллекту
--------
Осквернено
"""

    def test_russian_client_item(self):
        item = parse_item(self.RUSSIAN, self.db)
        self.assertEqual((item.base, item.ilvl, item.rarity), ("Ancestral Tiara", 82, "rare"))
        self.assertEqual(item.mods, [("prefix", "Ослепляющий"), ("suffix", "ученика")])
        self.assertTrue(item.corrupted)

    def test_fractured_mod_is_read_in_both_languages(self):
        for header, expected in (('{ Fractured Prefix Modifier "Dazzling" (Tier: 1) — Defences }', ("prefix", "Dazzling")),
                                 ('{ Расколотое Суффикс "ученика" (Уровень: 1) — Атрибут }', ("suffix", "ученика"))):
            text = f"Item Class: Helmets\nRarity: Rare\nX\nTiara\n--------\nItem Level: 82\n--------\n{header}\n+1 to X"
            item = parse_item(text, self.db)
            self.assertEqual(item.fractured, expected)
            self.assertEqual(item.mods, [expected])
        self.assertIsNone(parse_item(self.RARE, self.db).fractured)

    def test_russian_magic_and_unidentified(self):
        magic = "Класс предмета: Шлемы\nРедкость: Волшебный\nСияющая фамильная тиара лисы\n--------\nУровень предмета: 40"
        self.assertEqual((parse_item(magic, self.db).base, parse_item(magic, self.db).rarity), ("Ancestral Tiara", "magic"))
        hidden = "Класс предмета: Шлемы\nРедкость: Редкий\nТиара\n--------\nНеопознано\n--------\nУровень предмета: 40"
        with self.assertRaisesRegex(ValueError, "опознайте"):
            parse_item(hidden, self.db)

    def test_find_base_accepts_both_languages(self):
        self.assertEqual(self.db.find_base("фамильная"), "Ancestral Tiara")
        self.assertEqual(self.db.find_base("Ancestral"), "Ancestral Tiara")
        self.assertEqual(self.db.show_base("Ancestral Tiara"), "Фамильная тиара")

    RARE = """Item Class: Helmets
Rarity: Rare
Doom Crown
Ancestral Tiara
--------
Quality: +20% (augmented)
Energy Shield: 300 (augmented)
--------
Item Level: 82
--------
{ Prefix Modifier "Dazzling" (Tier: 1) — Defences, Energy Shield }
+70(61-73) to maximum Energy Shield
{ Desecrated Suffix Modifier "of Amanamu" (Tier: 1) — Attribute }
+12(9-15) to Strength
"""

    def test_rare_with_advanced_mods(self):
        item = parse_item(self.RARE.replace("\n", "\r\n"), self.db)
        self.assertEqual((item.base, item.ilvl, item.rarity, item.name), ("Ancestral Tiara", 82, "rare", "Doom Crown"))
        self.assertEqual(item.mods, [("prefix", "Dazzling"), ("suffix", "of Amanamu")])
        self.assertFalse(item.corrupted)

    def test_magic_name_contains_base_and_prefers_longest(self):
        text = "Item Class: Helmets\nRarity: Magic\nShining Ancestral Tiara of the Fox\n--------\nItem Level: 40\n--------\nCorrupted"
        item = parse_item(text, self.db)
        self.assertEqual((item.base, item.rarity), ("Ancestral Tiara", "magic"))
        self.assertTrue(item.corrupted)

    def test_rejections(self):
        for text, expected in (("Предмет", "прочитать"), ("Item Class: Helmets\nRarity: Unique\nX\nY\n--------\nItem Level: 8", "нельзя"),
                               ("Item Class: Helmets\nRarity: Rare\nX\nStone Helm\n--------\nItem Level: 8", "не поддерживается"),
                               ("Item Class: Helmets\nRarity: Rare\nX\nTiara\n--------\nUnidentified\n--------\nItem Level: 8", "опознайте")):
            with self.assertRaisesRegex(ValueError, expected):
                parse_item(text, self.db)

    def test_format_cost(self):
        self.assertEqual(format_cost(1000, 500, 10), "2 Divine")
        self.assertEqual(format_cost(100, 500, 10), "2 Chaos")
        self.assertEqual(format_cost(25, 500, 10), "25 Exalted")
        self.assertEqual(format_cost(2.5, 500, 10), "2.5 Exalted")
        self.assertEqual(format_cost(0, 500, 10), "0 Exalted")
        self.assertEqual(format_cost(100, 500), "100 Exalted")  # no Chaos rate yet

    def test_format_amount(self):
        self.assertEqual(crafter.format_amount(71.53, "Exalted Orb"), "72")
        self.assertEqual(crafter.format_amount(71.53, "Divine Orb"), "71.53")
        self.assertEqual(crafter.format_amount(1234.4, "Exalted Orb"), "1 234")
        self.assertEqual(crafter.format_amount(0.0004, "Exalted Orb"), "<0.001")
        self.assertEqual(crafter.format_amount(0.998, "Exalted Orb"), "1")  # rates move a little, so one orb should still read as one
        self.assertEqual(crafter.format_amount(2.07, "Exalted Orb"), "2.1")
        self.assertEqual(crafter.format_amount(0.14, "Chaos Orb"), "0.14")

    def test_divine_price(self):
        self.assertEqual(format_price(6169), "6 169")


class OtherCopiesTests(unittest.TestCase):
    def test_only_the_old_program_is_closed(self):
        processes = [(10, 1, "PoE2Crafter.exe"), (11, 10, "PoE2Crafter.exe"),  # an old copy: its starter and the program
                     (20, 1, "PoE2Crafter.exe"), (21, 20, "poe2crafter.EXE"),  # this copy
                     (30, 1, "game.exe"), (31, 30, "game.exe"),
                     (40, 99, "PoE2Crafter.exe")]  # a program whose starter is gone
        self.assertEqual(crafter.copies_to_close(processes, 21, 20, "PoE2Crafter.exe"), [11, 40])

    def test_a_copy_under_the_old_name_counts_as_this_program(self):
        processes = [(10, 1, "PoE2Crafter.exe"), (11, 10, "PoE2Crafter.exe"), (12, 1, "SakuraForge.exe"), (13, 12, "SakuraForge.exe"), (20, 1, "Sakuya.exe"), (21, 20, "Sakuya.exe"), (30, 1, "game.exe")]
        self.assertEqual(crafter.copies_to_close(crafter.under_one_name(processes, "Sakuya.exe"), 21, 20, "Sakuya.exe"), [11, 13])

    def test_nothing_to_close_when_alone(self):
        self.assertEqual(crafter.copies_to_close([(20, 1, "a.exe"), (21, 20, "a.exe")], 21, 20, "a.exe"), [])

    def test_the_program_that_started_this_one_for_a_theme_is_closed(self):
        family = [(10, 1, "a.exe"), (11, 10, "a.exe"), (12, 11, "a.exe"), (13, 12, "a.exe")]
        self.assertEqual(crafter.copies_to_close(family, 13, 12, "a.exe"), [11])

    def test_a_long_family_of_theme_changes_leaves_only_this_one(self):
        family = [(10, 1, "a.exe"), (11, 10, "a.exe"), (12, 11, "a.exe"), (13, 12, "a.exe"), (14, 13, "a.exe"), (15, 14, "a.exe")]
        self.assertEqual(crafter.copies_to_close(family, 15, 14, "a.exe"), [11, 13])

    def test_a_starter_whose_old_program_has_ended_is_this_copy(self):
        self.assertEqual(crafter.copies_to_close([(12, 11, "a.exe"), (13, 12, "a.exe")], 13, 12, "a.exe"), [])

    def test_a_reused_process_number_cannot_hang_the_search(self):
        self.assertEqual(crafter.copies_to_close([(10, 11, "a.exe"), (11, 10, "a.exe"), (21, 20, "a.exe")], 21, 20, "a.exe"), [10, 11])


class MainWindowTests(unittest.TestCase):
    def test_the_size_is_fixed_on_an_ordinary_screen(self):
        self.assertEqual(crafter.main_window_geometry(1920, 1080), "1140x860+40+40")

    def test_a_small_screen_still_holds_the_whole_window(self):
        self.assertEqual(crafter.main_window_geometry(1024, 720), "1004x640+40+40")

    def test_it_stands_where_the_previous_copy_stood(self):
        self.assertEqual(crafter.main_window_geometry(1920, 1080, "+-1500+12"), "1140x860+-1500+12")

    def test_the_window_follows_the_pointer_from_where_it_was_taken(self):
        page = crafter.App.__new__(crafter.App)
        page.root = mock.Mock()
        page.root.winfo_x.return_value, page.root.winfo_y.return_value = 100, 50
        page._start_window_drag(mock.Mock(x_root=130, y_root=60))
        page._drag_window(mock.Mock(x_root=-70, y_root=210))
        page.root.after_idle.call_args[0][0]()
        page.root.geometry.assert_called_once_with("+-100+200")

    def test_only_the_corner_of_the_banner_hides_the_window(self):
        self.assertTrue(crafter.in_minimize_spot(1120, 10, 1140))
        self.assertFalse(crafter.in_minimize_spot(1000, 10, 1140))
        self.assertFalse(crafter.in_minimize_spot(1120, 40, 1140))

    def dragging_page(self):
        page = crafter.App.__new__(crafter.App)
        page.root, page.banner = mock.Mock(), mock.Mock()
        page.banner.winfo_width.return_value = 1140
        page.root.winfo_x.return_value, page.root.winfo_y.return_value = 100, 50
        page.root.after_idle.return_value = "idle"
        page._hide_petals, page._show_petals = mock.Mock(), mock.Mock()
        return page

    def test_many_moves_of_the_mouse_make_one_move_of_the_window(self):
        page = self.dragging_page()
        page._on_banner_press(mock.Mock(x=400, y=20, x_root=500, y_root=70))
        for step in range(50):
            page._drag_window(mock.Mock(x_root=500 + step, y_root=70))
        page.root.geometry.assert_not_called()
        page.root.after_idle.assert_called_once()
        page.root.after_idle.call_args[0][0]()
        page.root.geometry.assert_called_once_with("+149+50")

    def test_the_petals_sit_out_the_move_and_come_back(self):
        page = self.dragging_page()
        page._on_banner_press(mock.Mock(x=400, y=20, x_root=500, y_root=70))
        page._hide_petals.assert_called_once()
        page._show_petals.assert_not_called()
        page._drag_window(mock.Mock(x_root=600, y_root=90))
        page._end_window_drag(None)
        page.root.geometry.assert_called_once_with("+200+70")
        page._show_petals.assert_called_once()
        page._end_window_drag(None)
        page._show_petals.assert_called_once()

    def test_a_press_on_the_window_never_uses_the_system_move_that_crashed(self):
        import inspect
        self.assertNotIn("SendMessage", inspect.getsource(crafter.App._on_banner_press))
        self.assertFalse(hasattr(crafter.App, "_move_with_windows"))

    def test_a_press_on_the_corner_hides_without_starting_a_drag(self):
        page = crafter.App.__new__(crafter.App)
        page.root, page.banner = mock.Mock(), mock.Mock()
        page.banner.winfo_width.return_value = 1140
        page._on_banner_press(mock.Mock(x=1120, y=10, x_root=1200, y_root=50))
        page.root.withdraw.assert_called_once_with()
        page._drag_window(mock.Mock(x_root=1300, y_root=90))
        page.root.geometry.assert_not_called()

    def test_the_place_is_read_from_the_arguments(self):
        self.assertEqual(crafter.place_to_reopen(["--reopen=+-1500+12"]), "+-1500+12")

    def test_no_place_on_an_ordinary_start(self):
        self.assertIsNone(crafter.place_to_reopen([]))

    def test_a_strange_place_is_ignored(self):
        self.assertIsNone(crafter.place_to_reopen(["--reopen=1x1; bad"]))


class LoadingScreenTests(unittest.TestCase):
    def test_every_theme_has_its_own_scene(self):
        import sakura
        self.assertEqual(set(sakura.LOADING_SCENES), set(sakura.THEMES))
        pictures = [sakura.loading_background(theme) for theme in sakura.THEMES]
        self.assertTrue(all(picture.size == sakura.LOADING_SIZE for picture in pictures))
        self.assertEqual(len({picture.tobytes() for picture in pictures}), len(pictures))

    def test_a_frame_is_the_whole_screen_with_words_over_petals_and_the_bar(self):
        import sakura
        for theme in sakura.THEMES:
            screen = sakura.LoadingScreen.__new__(sakura.LoadingScreen)
            screen.theme, screen.title, screen.lines, screen.seconds = theme, "Sakuya", ("Строка один", "Вторая " * 30), 2.0
            screen._prepare()
            frame = screen.compose(1.0, 0.5)
            self.assertEqual(frame.size, sakura.LOADING_SIZE)
            self.assertEqual(frame.mode, "RGB")
            width, height = sakura.LOADING_SIZE
            self.assertEqual(frame.getpixel((10, height - 2)), screen.accent)
            self.assertNotEqual(frame.getpixel((width - 10, height - 2)), screen.accent)
            self.assertGreater(screen.picture.words.getbbox()[3], 178)  # the lines did get drawn, in Russian too
            self.assertNotEqual(screen.compose(1.0, 0.5).tobytes(), screen.compose(3.0, 0.5).tobytes())

    def test_long_lines_are_wrapped_to_fit(self):
        import sakura
        font = sakura._font(14, "segoeui.ttf", "tahoma.ttf")
        lines = sakura._wrapped("слово " * 60, font, 200)
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(font.getlength(line) <= 200 for line in lines))

    def test_a_petal_never_leaves_the_screen_for_long(self):
        import sakura
        margin = sakura.LOADING_PETAL_MARGIN
        for petal in sakura.falling_petals(sakura.LOADING_PETALS, 3):
            for moment in range(0, 600, 7):
                x, y, frame = sakura.petal_place(petal, moment / 3)
                self.assertTrue(-margin <= x <= sakura.LOADING_SIZE[0] + margin)
                self.assertTrue(-margin <= y <= sakura.LOADING_SIZE[1] + margin)
                self.assertIn(frame, range(sakura.LOADING_PETAL_FRAMES))

    def test_petals_fall_and_keep_their_place_in_time(self):
        import sakura
        petal = sakura.falling_petals(1, 1)[0]
        self.assertEqual(sakura.petal_place(petal, 1.5), sakura.petal_place(petal, 1.5))
        self.assertNotEqual(sakura.petal_place(petal, 0)[1], sakura.petal_place(petal, 1)[1])

    def test_a_petal_on_the_see_through_color_leaves_only_that_color_around_it(self):
        import sakura
        frame = sakura.petal_frames(6.0, 255, (240, 160, 190))[0]
        picture = sakura.on_paper_color(frame, "#171219")
        self.assertEqual(picture.mode, "RGB")
        self.assertEqual(picture.getpixel((0, 0)), (0x17, 0x12, 0x19))
        self.assertTrue(any(red > 200 for red, _, _ in picture.getdata()))

    def test_petals_already_above_the_main_window_stay(self):
        import sakura
        self.assertIsNone(sakura.layer_place(5, 5, True))

    def test_petals_go_under_whatever_covers_the_main_window(self):
        import sakura
        self.assertEqual(sakura.layer_place(9, 5, False), 9)
        self.assertEqual(sakura.layer_place(9, 5, True), 9)

    def test_with_nothing_above_the_main_window_petals_take_its_band(self):
        import sakura
        self.assertEqual(sakura.layer_place(None, 5, True), sakura.HWND_TOPMOST)
        self.assertEqual(sakura.layer_place(None, 5, False), sakura.HWND_TOP)

    def test_the_wave_runs_right_and_down(self):
        import sakura
        self.assertEqual(sakura.wave_delay(0, 0), 0)
        self.assertLess(sakura.wave_delay(0, 0), sakura.wave_delay(1, 0))
        self.assertLess(sakura.wave_delay(1, 0), sakura.wave_delay(2, 1))

    def test_a_card_slides_fast_then_settles_exactly_in_place(self):
        import sakura
        self.assertEqual(sakura.wave_offset(0), sakura.WAVE_SLIDE_PIXELS)
        self.assertEqual(sakura.wave_offset(1), 0)
        self.assertEqual(sakura.wave_offset(5), 0)
        moved_early = sakura.wave_offset(0) - sakura.wave_offset(0.25)
        moved_late = sakura.wave_offset(0.75) - sakura.wave_offset(1)
        self.assertGreater(moved_early, moved_late)

    def test_the_placeholder_draws_aside_to_the_right(self):
        import sakura
        self.assertEqual(sakura.wave_cover_left(10, 110, 0), 10)
        self.assertEqual(sakura.wave_cover_left(10, 110, 1), 110)
        self.assertEqual(sakura.wave_cover_left(10, 110, 9), 110)
        self.assertLess(sakura.wave_cover_left(10, 110, 0.2), sakura.wave_cover_left(10, 110, 0.6))

    def test_the_fine_timer_is_asked_for_once_and_lapses_after_the_last_frame(self):
        import sakura
        now = [100.0]
        winmm, widget = mock.Mock(), mock.MagicMock()
        root = widget._root.return_value
        with mock.patch.object(sakura, "_winmm", winmm), mock.patch.object(sakura, "_fine_timer_on", False), mock.patch.object(sakura.time, "monotonic", lambda: now[0]):
            sakura.keep_timer_fine(widget)
            sakura.keep_timer_fine(widget)
            winmm.timeBeginPeriod.assert_called_once_with(1)
            root.after.assert_called_once()
            now[0] += sakura.FINE_TIMER_SECONDS / 2
            sakura.keep_timer_fine(widget)
            now[0] += sakura.FINE_TIMER_SECONDS / 2
            sakura._fine_timer_check(root)
            winmm.timeEndPeriod.assert_not_called()
            now[0] += sakura.FINE_TIMER_SECONDS
            sakura._fine_timer_check(root)
            winmm.timeEndPeriod.assert_called_once_with(1)
            sakura.keep_timer_fine(widget)
            self.assertEqual(winmm.timeBeginPeriod.call_count, 2)

    def test_petals_sleep_while_another_program_is_in_front(self):
        import os
        import sakura
        user32 = mock.Mock()

        def owner_is(pid):
            def fill(_, pointer):
                pointer._obj.value = pid
            return fill

        with mock.patch.object(sakura, "_user32", user32):
            user32.GetForegroundWindow.return_value = 0
            self.assertFalse(sakura._another_program_in_front())
            user32.GetForegroundWindow.return_value = 77
            user32.GetWindowThreadProcessId.side_effect = owner_is(os.getpid())
            self.assertFalse(sakura._another_program_in_front())
            user32.GetWindowThreadProcessId.side_effect = owner_is(os.getpid() + 1)
            self.assertTrue(sakura._another_program_in_front())

    def test_the_next_frame_is_timed_only_after_this_one_is_on_screen(self):
        """A timer already due when a frame ends would keep Tk from redrawing, and with petals it kept update() from ever returning."""
        import sakura
        now = [0.0]
        canvas = mock.MagicMock()
        canvas.winfo_exists.return_value = True
        window = canvas.winfo_toplevel.return_value
        waiting = []
        window.after_idle.side_effect = lambda action, *values: waiting.append((action, values)) or "idle"
        wave = sakura.CardWave(canvas, [(0, 0, 90, 50, 0.0)], lambda _: None, "#111", "#222", clock=lambda: now[0])
        self.assertEqual(wave.job, "idle")
        window.after.assert_not_called()
        now[0] = 1.0
        action, values = waiting.pop()
        action(*values)
        self.assertEqual(window.after.call_args.args[0], 1)  # the frame took too long: the shortest wait, not none

        owner = mock.MagicMock()
        petals = sakura.DriftingBlossom.__new__(sakura.DriftingBlossom)
        petals.owner = owner
        petals._next_frame(sakura.time.monotonic() - 10)
        self.assertEqual(owner.after.call_args.args[0], sakura.DRIFT_LEAST_WAIT_MS)
        self.assertGreater(sakura.DRIFT_LEAST_WAIT_MS, 0)

    def test_text_stays_out_of_the_wave_until_the_card_has_nearly_arrived(self):
        import sakura
        now = [0.0]
        canvas = mock.MagicMock()
        canvas.winfo_exists.return_value = True
        canvas.winfo_toplevel.return_value.after.return_value = "job"
        canvas.winfo_toplevel.return_value.after_idle.side_effect = lambda action, *values: action(*values) or "job"
        canvas.find_withtag.return_value = (1, 2, 3)
        canvas.type.side_effect = lambda item: "text" if item == 2 else "image"
        wave = sakura.CardWave(canvas, [(0, 0, 90, 50, 0.0)], lambda _: None, "#111", "#222", clock=lambda: now[0])
        canvas.itemconfigure.assert_any_call(2, state="hidden")
        canvas.dtag.assert_any_call(2, "wave0")
        canvas.itemconfigure.reset_mock()
        now[0] = sakura.WAVE_CARD_SECONDS * sakura.WAVE_WORDS_AT / 2
        wave._tick()
        self.assertNotIn(mock.call(2, state="normal"), canvas.itemconfigure.call_args_list)
        now[0] = sakura.WAVE_CARD_SECONDS * sakura.WAVE_WORDS_AT
        wave._tick()
        canvas.itemconfigure.assert_any_call(2, state="normal")
        now[0] = sakura.WAVE_CARD_SECONDS
        wave._tick()
        self.assertEqual(canvas.itemconfigure.call_args_list.count(mock.call(2, state="normal")), 1)
        self.assertEqual(wave.moving, {})

    def test_a_card_sheet_holds_its_parts_and_a_bad_picture_does_not_stop_it(self):
        import base64
        import io
        import price_check
        from PIL import Image
        red = io.BytesIO()
        Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(red, "PNG")
        stored = base64.b64encode(red.getvalue()).decode("ascii")
        made = []
        with mock.patch.object(price_check.tk, "PhotoImage", side_effect=lambda data, format: made.append(data) or object()), \
                mock.patch.object(price_check, "_card_keeper", return_value=mock.MagicMock()), \
                mock.patch.dict(price_check._card_images, clear=True):
            first = price_check.baked_card(100, 60, 0, (5, 5, 25, 25, "#000000", "#ffffff"), ((stored, 15, 15, 1), ("not a picture", 50, 30, 1), (None, 0, 0, 1)), ([1, 3, 2], 80, 20, "#00ff00", 10, 35))
            again = price_check.baked_card(100, 60, 0, (5, 5, 25, 25, "#000000", "#ffffff"), ((stored, 15, 15, 1), ("not a picture", 50, 30, 1), (None, 0, 0, 1)), ([1, 3, 2], 80, 20, "#00ff00", 10, 35))
        self.assertIs(first, again)
        self.assertEqual(len(made), 1)
        header = b"P6 100 60 255\n"
        self.assertTrue(made[0].startswith(header))
        pixels = made[0][len(header):]
        self.assertEqual(len(pixels), 100 * 60 * 3)
        at = lambda x, y: tuple(pixels[(y * 100 + x) * 3:(y * 100 + x) * 3 + 3])
        self.assertEqual(at(15, 15), (255, 0, 0))
        self.assertEqual(at(5, 5), (255, 255, 255))
        self.assertEqual(at(7, 7), (0, 0, 0))

    def wave(self, count, now):
        import sakura
        canvas = mock.MagicMock()
        canvas.winfo_exists.return_value = True
        window = canvas.winfo_toplevel.return_value
        window.after.return_value = "job"
        window.after_idle.side_effect = lambda action, *values: action(*values) or "job"
        drawn, done = [], []
        cards = [(number * 100, 0, number * 100 + 90, 50, sakura.wave_delay(number, 0)) for number in range(count)]
        wave = sakura.CardWave(canvas, cards, drawn.append, "#111", "#222", lambda: done.append(1), clock=lambda: now[0])
        return wave, canvas, drawn, done

    def test_cards_are_drawn_at_their_moment_not_all_at_once(self):
        import sakura
        now = [0.0]
        wave, canvas, drawn, done = self.wave(3, now)
        self.assertEqual(drawn, [0])
        self.assertEqual(canvas.create_rectangle.call_args_list[0].kwargs["tags"], ("wave_wait0",))
        now[0] = sakura.wave_delay(1, 0)
        wave._tick()
        self.assertEqual(drawn, [0, 1])
        self.assertEqual(done, [])

    def test_every_card_ends_in_place_and_the_rest_may_begin(self):
        import sakura
        now = [0.0]
        wave, canvas, drawn, done = self.wave(3, now)
        for step in range(1, 80):
            now[0] = step * 0.016
            if wave.waiting or wave.moving:
                wave._tick()
        self.assertEqual(drawn, [0, 1, 2])
        self.assertEqual(done, [1])
        for number in range(3):
            total = sum(call.args[1] for call in canvas.move.call_args_list if call.args[0] == f"wave{number}")
            self.assertEqual(total, 0, number)
            canvas.delete.assert_any_call(f"wave_wait{number}")
            canvas.dtag.assert_any_call(f"wave{number}")

    def test_a_failing_card_does_not_stop_the_wave(self):
        import sakura
        now = [0.0]
        wave, canvas, drawn, done = self.wave(2, now)
        wave.draw = mock.Mock(side_effect=ValueError("bad item"))
        now[0] = sakura.wave_delay(1, 0)
        canvas.winfo_toplevel.return_value.after.reset_mock()
        with self.assertRaises(ValueError):
            wave._tick()
        canvas.winfo_toplevel.return_value.after.assert_called_once()

    def test_a_rebuilt_page_ends_the_wave_quietly(self):
        now = [0.0]
        wave, canvas, drawn, done = self.wave(2, now)
        canvas.winfo_exists.return_value = False
        wave.job = None
        now[0] = 9
        wave._tick()
        self.assertEqual(drawn, [0])
        self.assertEqual(done, [])

    def test_a_tumbling_petal_changes_its_shape(self):
        import sakura
        frames = sakura.petal_frames(6.0, 255, (240, 160, 190))
        self.assertEqual(len(frames), sakura.LOADING_PETAL_FRAMES)
        self.assertGreater(len({frame.size for frame in frames}), 1)


class ItemArtTests(unittest.TestCase):
    def test_pictures_by_name_skip_alternates_and_unfinished_items(self):
        bases = {"a": {"name": "Stoat Idol", "visual_identity": {"dds_file": "Art/Idols/Stoat.dds"}}, "b": {"name": "[DNT] Test", "visual_identity": {"dds_file": "Art/X.dds"}}, "c": {"name": "Empty"}}
        uniques = {"1": {"name": "Helbrym's Hide", "visual_identity": {"dds_file": "Art/Uniques/Hide.dds"}}, "2": {"name": "Helbrym's Hide", "is_alternate_art": True, "visual_identity": {"dds_file": "Art/Other.dds"}}}
        self.assertEqual(crafter.read_item_art(bases, uniques), {"Stoat Idol": "Art/Idols/Stoat", "Helbrym's Hide": "Art/Uniques/Hide"})

    def test_downloads_are_saved_and_shown_in_batches_not_only_at_the_end(self):
        waiting = queue.Queue()
        for number in range(crafter.ICON_SAVE_BATCH + 1):
            waiting.put(f"Art/{number}")
        icons, shown, saved = {}, [], []

        class Finished(Exception):
            pass

        def stop_when_done(_):
            if waiting.empty():
                raise Finished

        with mock.patch.object(crafter, "fetch_bytes", return_value=b"x"), mock.patch.object(crafter, "make_icon", return_value="icon"), \
                mock.patch.object(crafter, "write_json", side_effect=lambda path, value: saved.append(len(value))), mock.patch.object(crafter.time, "sleep", side_effect=stop_when_done):
            with self.assertRaises(Finished):
                crafter.run_icon_downloads(waiting, icons, lambda: shown.append(len(icons)))
        self.assertEqual(saved, [crafter.ICON_SAVE_BATCH, crafter.ICON_SAVE_BATCH + 1])
        self.assertEqual(shown, saved)

    def test_a_space_in_a_name_is_quoted(self):
        waiting = queue.Queue()
        waiting.put("Art/Uniques/The Auspex")

        class Finished(Exception):
            pass

        with mock.patch.object(crafter, "fetch_bytes", return_value=b"x") as fetched, mock.patch.object(crafter, "make_icon", return_value="icon"), \
                mock.patch.object(crafter, "write_json"), mock.patch.object(crafter.time, "sleep", side_effect=Finished):
            with self.assertRaises(Finished):
                crafter.run_icon_downloads(waiting, {}, lambda: None)
        self.assertTrue(fetched.call_args.args[0].endswith("/Art/Uniques/The%20Auspex.png"))

    def test_a_strange_answer_does_not_end_the_downloads(self):
        waiting = queue.Queue()
        waiting.put("Art/Bad")
        waiting.put("Art/Good")
        icons = {}

        class Finished(Exception):
            pass

        def stop_when_done(_):
            if waiting.empty():
                raise Finished

        with mock.patch.object(crafter, "fetch_bytes", side_effect=[http.client.InvalidURL("bad"), b"x"]), mock.patch.object(crafter, "make_icon", return_value="icon"), \
                mock.patch.object(crafter, "write_json"), mock.patch.object(crafter.time, "sleep", side_effect=stop_when_done):
            with self.assertRaises(Finished):
                crafter.run_icon_downloads(waiting, icons, lambda: None)
        self.assertEqual(icons, {"Art/Good": "icon"})

    def test_a_picture_can_come_from_a_full_address(self):
        waiting = queue.Queue()
        waiting.put("https://web.poecdn.com/gen/image/a.png")

        class Finished(Exception):
            pass

        with mock.patch.object(crafter, "fetch_bytes", return_value=b"x") as fetched, mock.patch.object(crafter, "make_icon", return_value="icon"), \
                mock.patch.object(crafter, "write_json"), mock.patch.object(crafter.time, "sleep", side_effect=Finished):
            with self.assertRaises(Finished):
                crafter.run_icon_downloads(waiting, {}, lambda: None)
        self.assertEqual(fetched.call_args.args[0], "https://web.poecdn.com/gen/image/a.png")


class SakuraTests(unittest.TestCase):
    def test_every_paper_keeps_its_tone_with_a_texture_that_shows(self):
        for name, theme in sakura.THEMES.items():
            paper = sakura.paper_pixels(400, 300, theme=name)
            self.assertEqual(paper.shape, (300, 400, 3))
            brightness = paper.mean(axis=2)
            self.assertLess(float(brightness.mean()), 190, name)  # bright paper glares over a dark game
            self.assertLess(abs(float(brightness.mean()) - sum(theme["paper"]) / 3), 15, name)
            spread = float(np.percentile(brightness, 99.5) - np.percentile(brightness, 0.5))
            self.assertGreater(spread, 5, name)  # a texture that can be seen
            self.assertLess(spread, 32, name)  # that does not get in the way of the letters on top

    def test_the_same_paper_every_time(self):
        self.assertTrue((sakura.paper_pixels(100, 80) == sakura.paper_pixels(100, 80)).all())

    def test_a_saved_theme_is_used_and_a_strange_one_is_not(self):
        with mock.patch.dict(sakura.os.environ, {"POE_CRAFTER_THEME": "sumi"}):
            self.assertEqual(sakura._chosen_theme(), "sumi")
        with mock.patch.dict(sakura.os.environ, {"POE_CRAFTER_THEME": "rainbow"}), mock.patch.object(sakura.Path, "read_text", return_value='{"theme": "washi"}'):
            self.assertEqual(sakura._chosen_theme(), sakura.DEFAULT_THEME)
        with mock.patch.dict(sakura.os.environ, {"POE_CRAFTER_THEME": ""}), mock.patch.object(sakura.Path, "read_text", return_value='{"theme": "washi"}'):
            self.assertEqual(sakura._chosen_theme(), "washi")
        with mock.patch.dict(sakura.os.environ, {"POE_CRAFTER_THEME": ""}), mock.patch.object(sakura.Path, "read_text", return_value='{"theme": "tuff"}'):
            self.assertEqual(sakura._chosen_theme(), sakura.DEFAULT_THEME)  # a theme from an older version
        with mock.patch.dict(sakura.os.environ, {"POE_CRAFTER_THEME": ""}), mock.patch.object(sakura.Path, "read_text", side_effect=OSError):
            self.assertEqual(sakura._chosen_theme(), sakura.DEFAULT_THEME)

    def test_letters_read_on_the_paper(self):
        def light(color):
            channels = [(value / 255) for value in ImageColor.getrgb(color)]
            return sum(weight * (value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4) for weight, value in zip((0.2126, 0.7152, 0.0722), channels))

        def contrast(first, second):
            high, low = sorted((light(first), light(second)), reverse=True)
            return (high + 0.05) / (low + 0.05)

        for name, theme in sakura.THEMES.items():
            self.assertGreater(contrast(theme["text"], theme["panel"]), 7, name)
            self.assertGreater(contrast(theme["soft"], theme["panel"]), 4.5, name)
            self.assertGreater(contrast(theme["muted"], theme["bg"]), 4.5, name)  # the small notes must read too
            self.assertGreater(contrast(theme["accent"], theme["panel"]), 3, name)
            self.assertGreater(contrast(theme["on_chosen"], theme["chosen"]), 4.5, name)
            self.assertGreater(contrast(theme["on_chosen"], theme["chosen_light"]), 3, name)
            self.assertGreater(contrast(theme["ink"], theme["accent"]), 4.5, name)
            self.assertGreater(contrast(theme["mod_on"], theme["mod_on_ground"]), 4.5, name)
            self.assertGreater(contrast(theme["mod_off"], theme["panel"]), 3, name)
            for color in (*theme["special"].values(), *theme["rarity"].values()):
                self.assertGreater(contrast(color, theme["panel"]), 3, (name, color))
            # Layers must not melt together, and the levels of text must differ at a glance.
            self.assertGreater(contrast(theme["panel"], theme["bg"]), 1.25, name)
            self.assertGreater(contrast(theme["sidebar"], theme["bg"]), 1.04, name)  # near black the measure hardly moves, and a line separates the two as well
            self.assertGreater(contrast(theme["raised"], theme["panel"]), 1.25, name)
            self.assertGreater(contrast(theme["border"], theme["panel"]), 1.7, name)
            self.assertGreater(contrast(theme["mod_on_ground"], theme["panel"]), 1.25, name)
            self.assertGreater(contrast(theme["text"], theme["panel"]) / contrast(theme["soft"], theme["panel"]), 1.25, name)
            self.assertLess(contrast(theme["text"], theme["bg"]), 18.5, name)  # pure white on black glares over a dark game


class TrayTests(unittest.TestCase):
    def icon(self):
        self.clicks, self.menus = [], []
        icon = tray.TrayIcon("tip", lambda: self.clicks.append(1), lambda: ())
        icon._show_menu = lambda: self.menus.append(1)
        return icon

    def test_left_click_acts_and_right_click_opens_the_menu(self):
        icon = self.icon()
        icon.handle_event(tray.WM_LBUTTONUP)
        self.assertEqual((self.clicks, self.menus), ([1], []))
        icon.handle_event(tray.WM_RBUTTONUP)
        self.assertEqual((self.clicks, self.menus), ([1], [1]))

    def test_mouse_movement_over_the_icon_does_nothing(self):
        icon = self.icon()
        icon.handle_event(0x0200)  # WM_MOUSEMOVE
        self.assertEqual((self.clicks, self.menus), ([], []))

    def test_removing_an_icon_that_was_never_added_is_harmless(self):
        self.icon().remove()


class UniqueArtTests(unittest.TestCase):
    def test_both_names_lead_to_the_unique_art(self):
        uniques = {"1": {"name": "Trenchtimbre", "visual_identity": {"dds_file": "Art/Uniques/Trenchtimbre.dds"}},
                   "2": {"name": "Trenchtimbre", "is_alternate_art": True, "visual_identity": {"dds_file": "Art/Uniques/Other.dds"}},
                   "3": {"name": "Doryani's Hand", "visual_identity": {"dds_file": "Art/Uniques/Hand.dds"}}}
        page = """<a class="UniqueItem" data-hover="x" href="/ru/Trenchtimbre"><span class="uniqueName">Траншейный звон</span> <span class="uniqueTypeLine">Шипастая дубинка</span></a>
                  <a href="/ru/Doryanis_Hand"><span class="uniqueName">Рука Дориани</span></a>
                  <a href="/ru/Unknown_Thing"><span class="uniqueName">Чужое</span></a>"""
        art = crafter.read_unique_art(uniques, page)
        self.assertEqual(art["trenchtimbre"], "Art/Uniques/Trenchtimbre")
        self.assertEqual(art["траншейный звон"], "Art/Uniques/Trenchtimbre")
        self.assertEqual(art["рука дориани"], "Art/Uniques/Hand")
        self.assertNotIn("чужое", art)


class AgeTests(unittest.TestCase):
    def test_listing_age_picks_a_readable_unit(self):
        self.assertEqual(crafter.format_age(0), crafter.t("{count} мин").format(count=1))
        self.assertEqual(crafter.format_age(0.5), crafter.t("{count} ч").format(count=12))
        self.assertEqual(crafter.format_age(1.9), crafter.t("{count} ч").format(count=45))
        self.assertEqual(crafter.format_age(5.2), crafter.t("{count} д").format(count=5))


class SupportAddressTests(unittest.TestCase):
    def test_the_wallet_address_is_a_whole_tron_address(self):
        """A Tron address carries its own checksum: one wrong letter and money sent to it is lost."""
        import hashlib
        letters = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        number = 0
        for letter in crafter.SUPPORT_ADDRESS:
            number = number * 58 + letters.index(letter)
        raw = number.to_bytes(25, "big")
        self.assertEqual(raw[0], 0x41)
        self.assertEqual(hashlib.sha256(hashlib.sha256(raw[:21]).digest()).digest()[:4], raw[21:])


if __name__ == "__main__":
    unittest.main()
