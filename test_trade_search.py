import io
import json
import unittest
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from email.message import Message
from unittest import mock

import trade_search
from trade_search import ItemMod, StatFilter, build_query, build_stat_index, client_language, mods_on_by_default, normalize_stat, read_item_mods, rolled_value, split_ranges

STATS = {"result": [
    {"id": "explicit", "entries": [
        {"id": "explicit.life", "text": "# to maximum Life", "type": "explicit"},
        {"id": "explicit.es", "text": "# to maximum Energy Shield", "type": "explicit"},
        {"id": "explicit.es_local", "text": "# to maximum Energy Shield (Local)", "type": "explicit"},
        {"id": "explicit.res", "text": "#% to Cold Resistance", "type": "explicit"},
        {"id": "explicit.ru", "text": "# к максимуму здоровья", "type": "explicit"},
        {"id": "explicit.adds", "text": "Adds # to # Fire Damage", "type": "explicit"},
        {"id": "explicit.option", "text": "Allocates #", "type": "explicit", "option": {"options": []}},
    ]},
    {"id": "fractured", "entries": [{"id": "fractured.life", "text": "# to maximum Life", "type": "fractured"}]},
]}
INDEX = build_stat_index(STATS)
ITEM = """Item Class: Helmets
Rarity: Rare
Doom Crown
Ancestral Tiara
--------
Item Level: 82
--------
{ Implicit Modifier }
+12(10-15) to maximum Life
--------
{ Prefix Modifier "Dazzling" (Tier: 1) — Defences, Energy Shield }
+70(61-73) to maximum Energy Shield
{ Fractured Prefix Modifier "Stout" (Tier: 3) — Life }
+50(40-60) to maximum Life
(a hint explaining the mod)
{ Suffix Modifier "of the Yeti" (Tier: 2) — Cold }
+30(26-32)% to Cold Resistance
{ Suffix Modifier "Unknown" (Tier: 9) }
Something the site does not list
"""


def response(payload, headers=None):
    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    reply = Reply(json.dumps(payload).encode())
    reply.headers = headers or {}
    return reply


def http_error(code, headers=None):
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError("https://x", code, "error", message, io.BytesIO(b""))


class ReadingTests(unittest.TestCase):
    def test_a_note_in_any_language_joins_local_and_global_stats(self):
        entries = [{"id": "explicit.global", "text": "# к максимуму щита", "type": "explicit"}, {"id": "explicit.local", "text": "# к максимуму щита (Локальное)", "type": "explicit"}]
        index = build_stat_index({"result": [{"id": "explicit", "entries": entries}]})
        mods = read_item_mods('Редкость: Редкий\nX\nY\n--------\n{ Префикс "A" (Уровень: 1) }\n+5(4-6) к максимуму щита\n', index)
        self.assertEqual(set(mods[0].stats[0].ids), {"explicit.global", "explicit.local"})

    def test_normalize_stat(self):
        self.assertEqual(normalize_stat("+70(61-73) to maximum Energy Shield"), "# to maximum energy shield")
        self.assertEqual(normalize_stat("# to maximum Energy Shield"), "# to maximum energy shield")
        self.assertEqual(normalize_stat("+40(36-41) к максимуму [Life|здоровья]"), "# к максимуму здоровья")
        self.assertEqual(normalize_stat("Adds 10(8-12) to 20(18-26) Fire Damage"), "adds # to # fire damage")

    def test_rolled_value_ignores_the_range(self):
        self.assertEqual(rolled_value("+70(61-73) to Life"), 70)
        self.assertEqual(rolled_value("Adds 10(8-12) to 20(18-26) Fire Damage"), 15)
        self.assertIsNone(rolled_value("Cannot be frozen"))

    def test_index_joins_local_and_skips_options(self):
        self.assertEqual(INDEX["explicit"]["# to maximum energy shield"], ["explicit.es", "explicit.es_local"])
        self.assertNotIn("allocates #", INDEX["explicit"])

    def test_reads_mods_and_kinds(self):
        mods = read_item_mods(ITEM, INDEX)
        self.assertEqual([mod.tier for mod in mods], [1, 3, 2, 9])
        self.assertEqual(mods[0].stats, (StatFilter(("explicit.es", "explicit.es_local"), 70.0),))
        self.assertEqual(mods[1].stats, (StatFilter(("fractured.life",), 50.0),))  # the hint in brackets is skipped
        self.assertEqual(mods[3].stats, ())  # not on the site's list, so it cannot be searched
        self.assertNotIn("12(10-15)", " ".join(mod.label for mod in mods))  # implicit mods are not asked for

    def test_the_unscalable_note_is_not_part_of_the_mod(self):
        index = build_stat_index({"result": [{"id": "explicit", "entries": [{"id": "explicit.a", "text": "Что-то без чисел", "type": "explicit"}]}]})
        text = 'Редкость: Уникальный\nX\nY\n--------\n{ Уникальный модификатор }\nЧто-то без чисел — Неизменяемое значение\n'
        mod = read_item_mods(text, index)[0]
        self.assertEqual((mod.label, mod.stats), ("Что-то без чисел", (StatFilter(("explicit.a",), None),)))

    def test_split_ranges(self):
        self.assertEqual(split_ranges("Adds 10(8-12) to 20(18-26) Fire Damage"), ("Adds 10 to 20 Fire Damage", "8-12 · 18-26"))
        self.assertEqual(split_ranges("Cannot be frozen"), ("Cannot be frozen", ""))

    def test_russian_client(self):
        text = 'Класс предмета: Шлемы\n--------\n{ Префикс "Крепкий" (Уровень: 3) — Здоровье }\n+50(40-60) к максимуму здоровья\n'
        self.assertEqual(client_language(text), "ru")
        mod = read_item_mods(text, INDEX)[0]
        self.assertEqual((mod.tier, mod.stats), (3, (StatFilter(("explicit.ru",), 50.0),)))
        self.assertEqual(client_language(ITEM), "en")


class QueryTests(unittest.TestCase):
    MODS = [ItemMod("a", 1, (StatFilter(("explicit.es", "explicit.es_local"), 70.0),)), ItemMod("b", 2, (StatFilter(("explicit.res",), 30.0),))]

    def test_strictness_sets_minimums_and_groups_alternatives(self):
        query = build_query(None, "Ancestral Tiara", False, self.MODS, 0.9)["query"]
        self.assertEqual(query["stats"][0]["filters"], [{"id": "explicit.res", "value": {"min": 27}}])
        self.assertEqual(query["stats"][1], {"type": "count", "value": {"min": 1}, "filters": [{"id": "explicit.es", "value": {"min": 63}}, {"id": "explicit.es_local", "value": {"min": 63}}]})
        self.assertEqual(query["type"], "Ancestral Tiara")
        self.assertEqual(query["filters"]["type_filters"]["filters"]["rarity"]["option"], "nonunique")
        self.assertNotIn("name", query)

    def test_no_strictness_only_needs_the_mod(self):
        query = build_query(None, "Tiara", False, self.MODS[1:], 0)["query"]
        self.assertEqual(query["stats"][0]["filters"], [{"id": "explicit.res"}])

    def test_each_seller_counts_once(self):
        query = build_query(None, "Tiara", False, [], 0)["query"]
        self.assertEqual(query["filters"]["trade_filters"]["filters"]["collapse"]["option"], "true")

    def test_strong_and_special_mods_start_on(self):
        mods = read_item_mods(ITEM, INDEX)
        self.assertEqual([mod.tier for mod in mods_on_by_default(mods, False)], [1, 3, 2])  # the fractured T3 stays, the unlisted mod cannot
        self.assertEqual(mods_on_by_default(mods, True), [])

    def test_without_strong_mods_the_best_two_start_on(self):
        mods = [ItemMod(str(tier), tier, (StatFilter(("explicit.a",), 1.0),)) for tier in (7, 4, 5)]
        self.assertEqual([mod.tier for mod in mods_on_by_default(mods, False)], [4, 5])

    def test_unique_searches_by_name(self):
        query = build_query("Goldrim", "Felt Cap", True, [], 0)["query"]
        self.assertEqual((query["name"], query["filters"]["type_filters"]["filters"]["rarity"]["option"]), ("Goldrim", "unique"))


class EvaluationTests(unittest.TestCase):
    def mod(self, label, tier):
        return trade_search.ItemMod(label, tier, ())

    def test_a_roll_has_its_place_in_the_range(self):
        self.assertEqual(trade_search.roll_share("+60(50-70) to Life"), 0.5)
        self.assertEqual(trade_search.roll_share("+70(50-70) to Life"), 1.0)
        self.assertEqual(trade_search.roll_share("+50(50-70) to Life"), 0.0)
        self.assertEqual(trade_search.roll_share("Adds 5(4-6) to 10(8-12) Damage"), 0.5)

    def test_a_mod_with_no_range_has_no_place(self):
        self.assertIsNone(trade_search.roll_share("+1 to Level of all Spell Skills"))
        self.assertIsNone(trade_search.roll_share("+5(5-5) to Life"))

    def test_the_tier_counts_most_and_the_roll_a_little(self):
        self.assertEqual(trade_search.item_quality([self.mod("+70(50-70) to Life", 1)]), 100)
        self.assertEqual(trade_search.item_quality([self.mod("+50(50-70) to Life", 1)]), 90)
        self.assertEqual(trade_search.item_quality([self.mod("+70(50-70) to Life", 2)]), 88)
        self.assertEqual(trade_search.item_quality([self.mod("+70(50-70) to Life", 20)]), 30)

    def test_it_is_the_average_of_the_mods_with_a_tier(self):
        self.assertEqual(trade_search.item_quality([self.mod("+70(50-70) to Life", 1), self.mod("+70(50-70) to Mana", 3), self.mod("Some line", None)]), 88)
        self.assertIsNone(trade_search.item_quality([self.mod("Some line", None)]))


class AnyBaseAndCompareTests(unittest.TestCase):
    def test_a_kind_of_item_replaces_the_base(self):
        query = trade_search.build_query(None, "Ruby Ring", False, [], 0.9, "accessory.ring")["query"]
        self.assertNotIn("type", query)
        self.assertEqual(query["filters"]["type_filters"]["filters"]["category"], {"option": "accessory.ring"})
        plain = trade_search.build_query(None, "Ruby Ring", False, [], 0.9)["query"]
        self.assertEqual(plain["type"], "Ruby Ring")
        self.assertNotIn("category", plain["filters"]["type_filters"]["filters"])

    def test_each_page_has_its_kind(self):
        self.assertEqual(trade_search.trade_category("Gloves_dex_int"), "armour.gloves")
        self.assertEqual(trade_search.trade_category("Body_Armours_str"), "armour.chest")
        self.assertEqual(trade_search.trade_category("Quarterstaves"), "weapon.warstaff")
        self.assertEqual(trade_search.trade_category("Foci"), "armour.focus")
        self.assertIsNone(trade_search.trade_category("Traps"))
        self.assertIsNone(trade_search.trade_category(None))

    def item(self, *lines):
        return "Item Class: Rings\nRarity: Rare\nA\nRuby Ring\n--------\n" + "".join(f'{{ Prefix Modifier "A" (Tier: 2) }}\n{line}\n' for line in lines)

    def test_two_items_are_compared_by_their_lines(self):
        rows = trade_search.compared_lines(self.item("+60(50-69) to maximum Life", "+10(5-15) to Strength"), self.item("+70(50-79) to maximum Life", "+5(1-9) to Dexterity"))
        self.assertEqual(rows[0], ("# to maximum life", 60.0, 70.0))
        self.assertIn(("# to strength", 10.0, None), rows)
        self.assertIn(("# to dexterity", None, 5.0), rows)


class StatListTests(unittest.TestCase):
    LIST = "\n".join(json.dumps(line) for line in (
        {"ref": "# to maximum Life", "matchers": [{"string": "# to maximum Life"}], "trade": {"ids": {"explicit": ["explicit.stat_1"], "fractured": ["fractured.stat_1"]}}},
        {"ref": "#% increased Speed", "matchers": [{"string": "#% increased Speed"}, {"string": "#% reduced Speed", "negate": True}], "trade": {"ids": {"explicit": ["explicit.stat_2"]}}},
        {"ref": "Radius", "matchers": [{"string": "Upgrades Radius to Large", "value": 2}, {"string": "Upgrades Radius to Small", "value": 1}], "trade": {"option": True, "ids": {"explicit": ["explicit.stat_3"]}}},
        {"ref": "Extra", "matchers": [{"string": "Has an extra thing", "value": 1}], "trade": {"ids": {"explicit": ["explicit.stat_5"]}}},
        {"ref": "# Life (Local)", "matchers": [{"string": "# to maximum Life (Local)"}], "trade": {"ids": {"explicit": ["explicit.stat_4"]}}},
        {"ref": "no trade", "matchers": [{"string": "Nothing"}]},
    )) + "\n\n"

    def test_a_stat_reads_by_its_wording_and_kind(self):
        index = trade_search.read_stat_list(self.LIST)
        self.assertEqual(index["fractured"]["# to maximum life"], ["fractured.stat_1"])
        self.assertNotIn("nothing", index["explicit"])

    def test_local_and_global_versions_join(self):
        self.assertEqual(trade_search.read_stat_list(self.LIST)["explicit"]["# to maximum life"], ["explicit.stat_1", "explicit.stat_4"])

    def test_a_stat_read_the_other_way_round_is_left_out(self):
        index = trade_search.read_stat_list(self.LIST)["explicit"]
        self.assertIn("#% increased speed", index)
        self.assertNotIn("#% reduced speed", index)

    def test_an_option_is_written_as_the_site_writes_it(self):
        index = trade_search.read_stat_list(self.LIST)["explicit"]
        self.assertEqual(index["upgrades radius to large"], ["explicit.stat_3|2"])
        self.assertEqual(index["upgrades radius to small"], ["explicit.stat_3|1"])
        self.assertEqual(index["has an extra thing"], ["explicit.stat_5"])


class SiteLinkTests(unittest.TestCase):
    def reader(self, url):
        address, _, words = url.partition("?q=")
        return address, json.loads(urllib.parse.unquote(words))

    def test_the_whole_search_is_in_the_link(self):
        mod = trade_search.ItemMod("x", 1, (trade_search.StatFilter(("explicit.stat_1",), 100), trade_search.StatFilter(("explicit.stat_2", "explicit.stat_3"), 50)))
        query = trade_search.build_query(None, "Рубиновое кольцо", False, [mod], 0.9)
        address, read = self.reader(trade_search.trade_site_url("ru", "HC Forbidden Rites", query))
        self.assertEqual(address, "https://ru.pathofexile.com/trade2/search/poe2/HC%20Forbidden%20Rites")
        self.assertEqual(read, query)
        self.assertEqual(read["query"]["stats"][0]["filters"][0]["value"]["min"], 90)

    def test_the_language_picks_the_site(self):
        self.assertTrue(trade_search.trade_site_url("en", "L", {}).startswith("https://www.pathofexile.com/trade2/search/poe2/L?q="))
        self.assertTrue(trade_search.trade_site_url("xx", "L", {}).startswith("https://www.pathofexile.com/"))

    def test_nothing_in_the_link_can_break_it(self):
        url = trade_search.trade_site_url("en", "L", {"query": {"name": 'Hexer\'s "Robe" & co #1 ?x=1'}})
        self.assertNotIn('"', url)
        self.assertNotIn(" ", url)
        self.assertEqual(url.count("?"), 1)
        self.assertEqual(self.reader(url)[1]["query"]["name"], 'Hexer\'s "Robe" & co #1 ?x=1')

    def test_a_full_search_stays_short_enough_for_a_browser(self):
        mods = [trade_search.ItemMod("x", 1, (trade_search.StatFilter((f"explicit.stat_{number}000000000", f"explicit.stat_{number}111111111") if number == 0 else (f"explicit.stat_{number}000000000",), 100),)) for number in range(6)]
        query = trade_search.build_query(None, "Посох из очень длинного названия базы", False, mods, 0.9)
        self.assertLess(len(trade_search.trade_site_url("ru", "HC Forbidden Rites", query)), 2000)


if __name__ == "__main__":
    unittest.main()
