import json
import types
import unittest

import price_check
import urllib.parse

from price_check import SHORTEST_THUMB, CopiedItem, best_unit, build_price_index, find_price, format_change, read_copied_item, spark_curve, thumb_place, trade_search_url, view_for_thumb

CURRENCY = """Item Class: Stackable Currency
Rarity: Currency
Chaos Orb
--------
Stack Size: 1,234/5,000
--------
Removes a random modifier and augments a Rare item with a new random modifier
"""
RUSSIAN_CURRENCY = """Класс предмета: Валюта
Редкость: Валюта
Сфера хаоса
--------
Размер стопки: 12/20
"""
RARE = """Item Class: Helmets
Rarity: Rare
Doom Crown
Ancestral Tiara
--------
Item Level: 82
"""
UNIQUE = """Item Class: Helmets
Rarity: Unique
Some Legend
Ancestral Tiara
--------
Item Level: 82
"""
GEM = """Item Class: Uncut Skill Gems
Rarity: Currency
Uncut Skill Gem
--------
Level: 20
"""
PRICES = {"Chaos Orb": 0.1, "Uncut Skill Gem (Level 20)": 3.0, "Exalted Orb": 0.0014}
INDEX = build_price_index(PRICES, lambda name: {"Chaos Orb": "Сфера хаоса"}.get(name, name))


class PanelFitTests(unittest.TestCase):
    def test_a_small_screen_keeps_the_buttons_on_it(self):
        self.assertEqual(price_check.mod_rows_that_fit(768, 40), 3)
        self.assertEqual(price_check.mod_rows_that_fit(1080, 40), 11)
        self.assertEqual(price_check.mod_rows_that_fit(600, 40), 3)
        for screen in (768, 900, 1080, 1440):
            self.assertLessEqual(price_check.PANEL_FIXED_HEIGHT + price_check.mod_rows_that_fit(screen, 40) * 40, screen)


class ModWordsTests(unittest.TestCase):
    class Font:
        def __init__(self, width):
            self.width = width

        def measure(self, text):
            return len(text) * self.width

        def metrics(self, _):
            return 13

    def draw(self, text, left, room):
        drawn = []
        canvas = types.SimpleNamespace(create_text=lambda x, y, text, **_: drawn.append((x, y, text)))
        panel = price_check.TradeSearchPanel.__new__(price_check.TradeSearchPanel)
        panel.fonts = (self.Font(7), self.Font(8))
        panel._draw_mod_words(canvas, left, 0, text, room, "mod0")
        return drawn

    def test_the_space_after_a_number_stays(self):
        drawn = self.draw("Добавляет от 9 до 15 физического урона", 9, 1000)
        self.assertEqual("".join(text for _, _, text in drawn), "Добавляет от 9 до 15 физического урона")
        self.assertIn("9 ", [text for _, _, text in drawn])

    def test_words_wrap_before_the_ranges_even_after_a_tier_badge(self):
        left, room = 43, 200
        for x, _, text in self.draw("Добавляет от 9 до 15 физического урона к атакам", left, room):
            self.assertLessEqual(x + len(text.rstrip()) * 8, left + room, text)


class UnitTests(unittest.TestCase):
    RATES = (700, 10)

    def test_the_player_rule(self):
        self.assertEqual(best_unit(5, *self.RATES)[1], "Divine Orb")
        self.assertEqual(best_unit(0.2, *self.RATES), (2, "Chaos Orb"))  # about 0.1 Divine reads in Chaos
        self.assertEqual(best_unit(0.01, *self.RATES), (7, "Exalted Orb"))  # about 0.01 reads in Exalted

    def test_an_orb_is_not_priced_in_itself(self):
        self.assertEqual(best_unit(1, *self.RATES, "Divine Orb"), (700, "Exalted Orb"))
        self.assertEqual(best_unit(0.1, *self.RATES, "Chaos Orb"), (70, "Exalted Orb"))
        self.assertEqual(best_unit(1 / 700, *self.RATES, "Exalted Orb")[1], "Chaos Orb")

    def test_without_rates_it_stays_in_divine(self):
        self.assertEqual(best_unit(0.01, None, None), (0.01, "Divine Orb"))
        self.assertEqual(best_unit(0.2, 700, None), (140, "Exalted Orb"))


class ScrollbarTests(unittest.TestCase):
    def test_a_long_list_keeps_a_handle_that_can_be_grabbed(self):
        top, bottom = thumb_place(0, 0.02, 500)
        self.assertEqual((top, bottom), (0, SHORTEST_THUMB))

    def test_the_handle_reaches_the_end(self):
        self.assertAlmostEqual(thumb_place(0.98, 1.0, 500)[1], 500)

    def test_dragging_is_the_reverse_of_placing(self):
        for first in (0, 0.2, 0.5, 0.98):
            top, _ = thumb_place(first, first + 0.02, 500)
            self.assertAlmostEqual(view_for_thumb(top, 0.02, 500), first)

    def test_dragging_past_the_ends_stops_there(self):
        self.assertEqual(view_for_thumb(-50, 0.02, 500), 0)
        self.assertAlmostEqual(view_for_thumb(5000, 0.02, 500), 0.98)

    def test_a_short_list_fills_the_track(self):
        self.assertEqual(thumb_place(0, 1, 500), (0, 500))
        self.assertEqual(view_for_thumb(10, 1, 500), 0)


class TrendTests(unittest.TestCase):
    def test_no_curve_without_two_prices(self):
        self.assertEqual(spark_curve(None, 96, 28), [])
        self.assertEqual(spark_curve([1, None], 96, 28), [])

    def test_the_higher_price_is_nearer_the_top(self):
        curve = spark_curve([1, None, 3], 96, 28)
        self.assertEqual((curve[0], curve[-1]), ((3, 25), (93, 3)))

    def test_a_flat_price_runs_through_the_middle(self):
        self.assertEqual({y for _, y in spark_curve([2, 2, 2], 96, 28)}, {14})

    def test_the_curve_is_fine_and_never_swings_past_the_real_prices(self):
        curve = spark_curve([1, 5, 2, 9, 9, 0, 3], 200, 30)
        self.assertGreater(len(curve), 50)
        self.assertTrue(all(3 - 1e-9 <= y <= 27 + 1e-9 for _, y in curve))
        self.assertEqual([x for x, _ in curve], sorted(x for x, _ in curve))

    def test_change_text(self):
        self.assertEqual(format_change(7.84), ("▲", "7.8%"))
        self.assertEqual(format_change(-47.2), ("▼", "47%"))
        self.assertEqual(format_change(603.0), ("▲", "603%"))
        self.assertEqual(format_change(-0.04), ("", "0%"))


class ReadingTests(unittest.TestCase):
    def test_reads_stack_with_separators(self):
        item = read_copied_item(CURRENCY.replace("\n", "\r\n"))
        self.assertEqual((item.rarity, item.lines, item.stack), ("Currency", ("Chaos Orb",), 1234))

    def test_reads_russian_client(self):
        item = read_copied_item(RUSSIAN_CURRENCY)
        self.assertEqual((item.rarity, item.lines, item.stack), ("Валюта", ("Сфера хаоса",), 12))

    def test_item_without_stack_counts_as_one(self):
        item = read_copied_item(RARE)
        self.assertEqual((item.stack, item.lines), (1, ("Doom Crown", "Ancestral Tiara")))

    def test_other_text_is_not_an_item(self):
        self.assertIsNone(read_copied_item("just some text"))
        self.assertIsNone(read_copied_item(""))


class PriceTests(unittest.TestCase):
    def test_finds_price_in_both_languages(self):
        for text, stack in ((CURRENCY, 1234), (RUSSIAN_CURRENCY, 12)):
            match = find_price(read_copied_item(text), PRICES, INDEX)
            self.assertEqual((match.name, match.each, match.stack), ("Chaos Orb", 0.1, stack))

    def test_gem_level_zero_or_odd_finds_nothing_wrong(self):
        self.assertIsNone(find_price(CopiedItem("", ("Нет такого",), 1, 3), PRICES, INDEX))

    def test_a_russian_gem_finds_its_level_as_the_price_list_writes_it(self):
        prices = {"Uncut Skill Gem (Level 20)": 3.0}
        index = build_price_index(prices, lambda name: "Неогранённый камень умения (уровень 20)")
        item = CopiedItem("Обычный", ("Неогранённый камень умения",), 1, 20)
        self.assertEqual(find_price(item, prices, index).name, "Uncut Skill Gem (Level 20)")

    def test_a_tablet_finds_the_price_of_its_rarity_in_either_language(self):
        prices = {"Temple Tablet (Normal)": 0.05, "Temple Tablet (Magic)": 0.2, "Temple Tablet (Rare)": 0.76, "Abyss Tablet (Rare)": 0.74}
        russian = {"Temple Tablet (Normal)": "Скрижаль храма (обычная)", "Temple Tablet (Magic)": "Скрижаль храма (магическая)", "Temple Tablet (Rare)": "Скрижаль храма (редкая)", "Abyss Tablet (Rare)": "Скрижаль бездны (редкая)"}
        index = build_price_index(prices, russian.get)
        self.assertEqual(find_price(CopiedItem("Rare", ("Doom Sigil", "Temple Tablet"), 1, None), prices, index).name, "Temple Tablet (Rare)")
        self.assertEqual(find_price(CopiedItem("Magic", ("Expanding Temple Tablet of the Seer",), 1, None), prices, index).name, "Temple Tablet (Magic)")
        self.assertEqual(find_price(CopiedItem("Обычный", ("Скрижаль храма",), 1, None), prices, index).name, "Temple Tablet (Normal)")
        self.assertEqual(find_price(CopiedItem("Редкий", ("Гибельная печать", "Скрижаль бездны"), 1, None), prices, index).name, "Abyss Tablet (Rare)")
        self.assertIsNone(find_price(CopiedItem("Rare", ("Doom Loop", "Ruby Ring"), 1, None), prices, index))
        self.assertIsNone(find_price(CopiedItem("Magic", ("Abyss Tablet of Haste",), 1, None), prices, index))  # no magic price of it: no guess from another rarity

    def test_gem_uses_its_level(self):
        self.assertEqual(find_price(read_copied_item(GEM), PRICES, INDEX).name, "Uncut Skill Gem (Level 20)")

    def test_equipment_has_no_price_here(self):
        self.assertIsNone(find_price(read_copied_item(RARE), PRICES, INDEX))


class TradeLinkTests(unittest.TestCase):
    BASES = {"ancestral tiara": "Ancestral Tiara", "фамильная тиара": "Ancestral Tiara", "tiara": "Tiara"}

    def query(self, url):
        return json.loads(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["q"][0])

    def test_rare_uses_english_base_and_longest_match(self):
        url = trade_search_url(read_copied_item(RARE), "Forbidden Rites", self.BASES)
        self.assertTrue(url.startswith("https://www.pathofexile.com/trade2/search/poe2/Forbidden%20Rites?q="))
        query = self.query(url)["query"]
        self.assertEqual(query["type"], "Ancestral Tiara")
        self.assertEqual(query["filters"]["type_filters"]["filters"]["rarity"]["option"], "nonunique")

    def test_unique_filter_and_russian_item(self):
        self.assertEqual(self.query(trade_search_url(read_copied_item(UNIQUE), "L", self.BASES))["query"]["filters"]["type_filters"]["filters"]["rarity"]["option"], "unique")
        russian = RARE.replace("Item Class: Helmets", "Класс предмета: Шлемы").replace("Rarity: Rare", "Редкость: Редкий").replace("Ancestral Tiara", "Фамильная тиара")
        self.assertEqual(self.query(trade_search_url(read_copied_item(russian), "L", self.BASES))["query"]["type"], "Ancestral Tiara")

    def test_unknown_base_opens_the_plain_search(self):
        url = trade_search_url(read_copied_item(RARE.replace("Ancestral Tiara", "Stone Helm")), "L", self.BASES)
        self.assertEqual(url, "https://www.pathofexile.com/trade2/search/poe2/L")


if __name__ == "__main__":
    unittest.main()
