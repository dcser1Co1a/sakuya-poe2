import io
import json
import random
import re
import unittest
import urllib.error
from pathlib import Path

import crafter
import tools
import trade_search
from crafter import Mod, Page, Planner, State, make_want, recipe_text, simulate_plan
from tools import (
    EXCHANGE_COINS,
    SHORTEST_FRAGMENT,
    Stopwatch,
    add_bookmark,
    close_deal,
    dangerous_lines,
    danger_keys,
    exchange_rates,
    exchange_turnover,
    exclusion_search,
    fetch_exchange,
    format_time,
    is_waystone,
    journal_totals,
    make_deal,
    mod_table,
    read_amount,
    read_waystone_mods,
    shortest_fragment,
    to_exalted,
    waystone_fragments,
    waystone_template,
)

PRICES = {"exalted_per_divine": 100.0, "chaos_per_divine": 10.0}
EXALTED, CHAOS, DIVINE = EXCHANGE_COINS["Exalted Orb"], EXCHANGE_COINS["Chaos Orb"], EXCHANGE_COINS["Divine Orb"]
ITEM = "Metadata/Items/Currency/Thing"
NAMES = {ITEM: "Thing", EXALTED: "Exalted Orb", CHAOS: "Chaos Orb", DIVINE: "Divine Orb"}
ROW = "<tr><td>{tier}</td><td>{side}</td><td>{cell}</td></tr>"


def market(first: str, second: str, amount_first: float, amount_second: float, league: str = "L") -> dict:
    return {"league": league, "market_pair": [first, second], "volume_traded": {first: amount_first, second: amount_second}}


def waystone_page(rows: list[tuple[str, str]]) -> str:
    return "<table>" + "".join(ROW.format(tier=number, side=side, cell=cell) for number, (side, cell) in enumerate(rows, 1)) + "</table>"


WAYSTONE_EN = waystone_page([
    ("Suffix", "<span class='mod-value'>(-4<span>—</span>-3)</span>% maximum Player Resistances<br><span class='mod-value'>8</span>% more Pack size"),
    ("Suffix", "<span class='mod-value'>(-6<span>—</span>-5)</span>% maximum Player Resistances<br><span class='mod-value'>9</span>% more Pack size"),
    ("Prefix", "<span class='mod-value'>(5<span>—</span>9)</span>% increased Monster Damage<br><span class='mod-value'>25</span>% more Magic and Rare Monsters"),
    ("Prefix", ""),
    ("Suffix", "Monsters are Armoured<br><span class='mod-value'>18</span>% more Rarity of Items found in this Area"),
])
WAYSTONE_RU = waystone_page([
    ("Suffix", "<span class='mod-value'>(-4<span>—</span>-3)</span>% максимум сопротивлений игроков<br><span class='mod-value'>8</span>% больше размер групп"),
    ("Suffix", "<span class='mod-value'>(-6<span>—</span>-5)</span>% максимум сопротивлений игроков<br><span class='mod-value'>9</span>% больше размер групп"),
    ("Prefix", "<span class='mod-value'>(5<span>—</span>9)</span>% увеличение урона монстров<br><span class='mod-value'>25</span>% больше волшебных и редких монстров"),
    ("Prefix", ""),
    ("Suffix", "Монстры бронированы<br><span class='mod-value'>18</span>% больше редкости предметов в этой области"),
])


class BookmarkTests(unittest.TestCase):
    def test_newest_first_and_no_doubles(self):
        marks = add_bookmark([], "A", "1", "a", "d")
        marks = add_bookmark(marks, "B", "2", "b", "d")
        marks = add_bookmark(marks, "A again", "3", "a", "d")
        self.assertEqual([mark["name"] for mark in marks], ["A again", "B"])

    def test_keeps_a_limited_number(self):
        marks = []
        for number in range(tools.BOOKMARKS_KEPT + 5):
            marks = add_bookmark(marks, str(number), "", str(number), "d")
        self.assertEqual(len(marks), tools.BOOKMARKS_KEPT)
        self.assertEqual(marks[0]["name"], str(tools.BOOKMARKS_KEPT + 4))


class JournalTests(unittest.TestCase):
    def test_reads_both_decimal_marks_and_refuses_nonsense(self):
        self.assertEqual([read_amount(text) for text in ("1,5", "2.5", " 3 ", "abc", "", "-1", "inf")], [1.5, 2.5, 3.0, None, None, None, None])

    def test_converts_every_unit(self):
        self.assertEqual([to_exalted(2, unit, PRICES) for unit in tools.JOURNAL_UNITS], [2, 20.0, 200.0])

    def test_chaos_without_a_rate_is_unknown_and_does_not_count(self):
        deal = make_deal("X", 1, 2, "Chaos Orb", {"exalted_per_divine": 100.0}, "d")
        self.assertEqual(journal_totals([deal]), (0, 0, 0))

    def test_totals_separate_closed_from_open(self):
        deals = [make_deal("A", 10, 15, "Exalted Orb", PRICES, "d"), make_deal("B", 20, 5, "Exalted Orb", PRICES, "d"), make_deal("C", 1, None, "Divine Orb", PRICES, "d")]
        self.assertEqual(journal_totals(deals), (-10, 100.0, 2))

    def test_an_old_deal_keeps_its_old_rate(self):
        deal = make_deal("A", 1, None, "Divine Orb", PRICES, "d")
        closed = close_deal(deal, 1, {"exalted_per_divine": 300.0, "chaos_per_divine": 10.0})
        self.assertEqual(journal_totals([closed]), (200.0, 0, 1))
        self.assertIsNone(deal["sold"])


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        self.coins = [market(DIVINE, EXALTED, 10, 1000), market(CHAOS, DIVINE, 1000, 100), market(CHAOS, EXALTED, 1000, 10000)]

    def test_rate_is_what_changed_hands_divided(self):
        rates = exchange_rates([market(DIVINE, EXALTED, 10, 1000)], "L")
        self.assertEqual(rates[DIVINE][EXALTED], (100.0, 1000))
        self.assertEqual(rates[EXALTED][DIVINE], (0.01, 10))

    def test_other_leagues_and_empty_markets_are_ignored(self):
        self.assertEqual(exchange_rates([market(DIVINE, EXALTED, 10, 1000, "Other"), market(DIVINE, CHAOS, 0, 5)], "L"), {})

    def test_turnover_adds_up_what_was_paid_in_all_coins(self):
        # 2 Divine are 200 Exalted, 300 Exalted stay 300, and 10 Chaos are 100 Exalted.
        rows = exchange_turnover([*self.coins, market(ITEM, DIVINE, 50, 2), market(ITEM, EXALTED, 50, 300), market(ITEM, CHAOS, 50, 10)], "L", NAMES)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].item, "Thing")
        self.assertAlmostEqual(rows[0].traded_exalted, 600)
        self.assertEqual(rows[0].main_coin, "Exalted Orb")
        self.assertAlmostEqual(rows[0].main_share, 0.5)

    def test_the_busiest_comes_first(self):
        other = "Metadata/Items/Currency/Other"
        rows = exchange_turnover([*self.coins, market(ITEM, EXALTED, 1, 5), market(other, EXALTED, 1, 50)], "L", {**NAMES, other: "Other"})
        self.assertEqual([row.item for row in rows], ["Other", "Thing"])

    def test_coins_are_not_goods_and_trades_between_goods_do_not_count(self):
        other = "Metadata/Items/Currency/Other"
        self.assertEqual(exchange_turnover([*self.coins, market(ITEM, other, 5, 5)], "L", {**NAMES, other: "Other"}), [])

    def test_a_coin_without_a_rate_is_left_out(self):
        rows = exchange_turnover([market(ITEM, DIVINE, 1, 5), market(ITEM, EXALTED, 1, 7)], "L", NAMES)
        self.assertEqual([(row.traded_exalted, row.main_share) for row in rows], [(7.0, 1.0)])

    def test_unknown_goods_are_skipped(self):
        self.assertEqual(exchange_turnover([*self.coins, market(ITEM, DIVINE, 100, 100)], "L", {}), [])

    def test_names_cover_goods_but_not_equipment(self):
        gem = "Metadata/Items/Gem/SupportX"
        self.assertEqual(tools.exchange_names({DIVINE: {"name": "Divine Orb"}, gem: {"name": "Gem"}, "Metadata/Items/Armours/X": {"name": "Hat"}, "Metadata/Items/Currency/Nameless": {}}), {DIVINE: "Divine Orb", gem: "Gem"})

    def test_asks_for_the_last_finished_hour(self):
        asked = []

        def opener(request, timeout):
            asked.append(request.full_url)
            return io.BytesIO(json.dumps({"markets": []}).encode())

        hour, digest = fetch_exchange(7200 + 1800, "agent", opener)
        self.assertEqual((hour, digest), (3600, {"markets": []}))
        self.assertEqual(asked, ["https://web.poecdn.com/api/currency-exchange/poe2/3600"])

    def test_falls_back_one_hour_when_the_file_is_not_out_yet(self):
        asked = []

        def opener(request, timeout):
            asked.append(request.full_url)
            if len(asked) == 1:
                raise urllib.error.HTTPError(request.full_url, 404, "not yet", {}, None)
            return io.BytesIO(b'{"markets": []}')

        self.assertEqual(fetch_exchange(7200, "agent", opener)[0], 0)
        self.assertEqual(len(asked), 2)

    def test_other_errors_are_not_retried(self):
        asked = []

        def opener(request, timeout):
            asked.append(request.full_url)
            raise urllib.error.HTTPError(request.full_url, 429, "slow down", {}, None)

        with self.assertRaises(urllib.error.HTTPError):
            fetch_exchange(7200, "agent", opener)
        self.assertEqual(len(asked), 1)


class WaystoneTests(unittest.TestCase):
    def setUp(self):
        self.waystones = read_waystone_mods(WAYSTONE_EN, WAYSTONE_RU)

    def test_one_wording_for_any_roll(self):
        for line in ("(5—9)% more Life", "7% more Life", "7(5-9)% more Life", "+7% more Life", "+(5—9)% more Life"):
            self.assertEqual(waystone_template(line), "#% more Life", line)
        self.assertEqual(waystone_template("(-4—-3)% maximum Player Resistances"), "#% maximum Player Resistances")
        self.assertEqual(waystone_template("-3% maximum Player Resistances"), "#% maximum Player Resistances")

    def test_tiers_of_a_mod_become_one_kind_and_empty_rows_are_skipped(self):
        self.assertEqual([kind["key"] for kind in self.waystones["kinds"]], ["#% maximum Player Resistances", "#% increased Monster Damage", "Monsters are Armoured"])
        self.assertEqual(self.waystones["kinds"][0]["ru"], "#% максимум сопротивлений игроков")
        self.assertEqual(self.waystones["kinds"][0]["side"], "suffix")

    def test_rewards_are_kept_apart_from_the_dangers(self):
        self.assertIn("#% more Pack size", self.waystones["rewards"]["en"])
        self.assertNotIn("#% more Pack size", [kind["key"] for kind in self.waystones["kinds"]])

    def test_pages_that_differ_are_refused(self):
        with self.assertRaises(ValueError):
            read_waystone_mods(WAYSTONE_EN, waystone_page([("Prefix", "only one")]))
        with self.assertRaises(ValueError):
            read_waystone_mods("<p>nothing</p>", "<p>nothing</p>")

    def test_knows_a_waystone_by_its_item_class_in_both_languages(self):
        self.assertTrue(is_waystone("Item Class: Waystones\nRarity: Rare"))
        self.assertTrue(is_waystone("Класс предмета: Путевые камни\nРедкость: Редкий"))
        self.assertFalse(is_waystone("Класс предмета: Шлемы\nРедкость: Редкий\nПутевые камни"))

    def test_warns_about_chosen_mods_in_either_language_and_copy_style(self):
        kinds = self.waystones["kinds"]
        danger = {"#% maximum Player Resistances"}
        self.assertEqual(dangerous_lines("Item Class: Waystones\r\n-3% maximum Player Resistances\r\n8% increased Monster Damage", kinds, danger), ["-3% maximum Player Resistances"])
        self.assertEqual(dangerous_lines('{ Суффикс "А" }\n-3(-4—-3)% максимум сопротивлений игроков\n', kinds, danger), ["-3(-4—-3)% максимум сопротивлений игроков"])
        self.assertEqual(dangerous_lines("8% increased Monster Damage", kinds, danger), [])

    def test_the_first_list_takes_only_mods_the_game_has_and_an_empty_choice_stays_empty(self):
        kinds = self.waystones["kinds"]
        self.assertEqual(danger_keys(None, kinds), {"#% maximum Player Resistances"})
        self.assertEqual(danger_keys([], kinds), set())
        self.assertEqual(danger_keys(["Monsters are Armoured"], kinds), {"Monsters are Armoured"})

    def test_a_fragment_belongs_to_its_line_alone(self):
        line = "Monsters are Armoured"
        others = ["Monsters Break Armour equal to #% of Physical Damage dealt", "#% increased Monster Damage"]
        fragment = shortest_fragment(line, others)
        self.assertGreaterEqual(len(fragment), SHORTEST_FRAGMENT)
        self.assertIn(fragment, line.casefold())
        self.assertFalse(any(fragment in other.casefold() for other in others))

    def test_a_fragment_prefers_no_spaces_and_never_holds_numbers(self):
        fragment = shortest_fragment("#% less Cooldown Recovery Rate", ["#% less Recovery"])
        self.assertNotIn(" ", fragment)
        self.assertNotRegex(fragment, r"[#%\d]")

    def test_a_longer_word_piece_beats_a_shorter_piece_across_two_words(self):
        self.assertEqual(shortest_fragment("abcde fghij", ["abcd", "bcde", "fghi", "ghij"]), "abcde")

    def test_a_piece_across_two_words_is_the_last_resort(self):
        self.assertEqual(shortest_fragment("ab cd", ["ab", "cd"]), "ab c")

    def test_a_piece_across_two_words_is_long_enough_to_mean_something(self):
        fragment = shortest_fragment("abcd efgh", ["abcd", "efgh"])
        self.assertIn(" ", fragment)
        self.assertGreaterEqual(len(fragment), tools.SHORTEST_SPACED_FRAGMENT)

    def test_a_line_with_no_free_piece_gets_no_fragment(self):
        self.assertEqual(shortest_fragment("Monster Damage", ["More Monster Damage here"]), "")

    def test_fragments_do_not_hide_rewards(self):
        for code in ("en", "ru"):
            fragments = waystone_fragments(self.waystones, code)
            for fragment in fragments.values():
                self.assertTrue(fragment)
                self.assertFalse(any(fragment in reward.casefold() for reward in self.waystones["rewards"][code]))

    def test_search_line(self):
        self.assertEqual(exclusion_search(["abcd", "", "efgh"]), '"!abcd|efgh"')
        self.assertEqual(exclusion_search([""]), "")


class StopwatchTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.watch = Stopwatch(lambda: self.now)

    def test_counts_only_while_running(self):
        self.watch.toggle()
        self.now += 10
        self.watch.toggle()
        self.now += 50
        self.assertEqual(self.watch.elapsed, 10)
        self.assertFalse(self.watch.running)

    def test_a_lap_ends_the_map_and_keeps_counting(self):
        self.watch.toggle()
        self.now += 60
        self.watch.lap()
        self.now += 120
        self.watch.lap()
        self.assertEqual(self.watch.laps, [60, 120])
        self.assertEqual(self.watch.average, 90)
        self.assertEqual(self.watch.elapsed, 0)
        self.assertTrue(self.watch.running)

    def test_a_lap_while_paused_stays_paused(self):
        self.watch.toggle()
        self.now += 30
        self.watch.toggle()
        self.watch.lap()
        self.now += 30
        self.assertEqual((self.watch.laps, self.watch.elapsed, self.watch.running), ([30], 0, False))

    def test_an_empty_lap_is_not_recorded(self):
        self.watch.lap()
        self.assertEqual((self.watch.laps, self.watch.average), ([], None))

    def test_reset_clears_everything(self):
        self.watch.toggle()
        self.now += 5
        self.watch.lap()
        self.watch.reset()
        self.assertEqual((self.watch.elapsed, self.watch.laps, self.watch.running), (0, [], False))

    def test_time_format(self):
        self.assertEqual([format_time(seconds) for seconds in (0, 65.9, 3725)], ["00:00", "01:05", "1:02:05"])


def page_of(*mods: Mod) -> Page:
    return Page("Test", list(mods))


def life(level: int, weight: int, name: str = "life") -> Mod:
    return Mod(f"{name}{level}", "prefix", level, (name,), weight, True, f"+({level}-{level + 5}) to {name}", f"+# to {name}")


class ReferenceTests(unittest.TestCase):
    def test_shares_add_up_and_the_likeliest_comes_first(self):
        page = page_of(life(1, 300), life(50, 100), life(1, 600, "mana"), Mod("s", "suffix", 1, ("s",), 500, True, "+1 to s", "+# to s"))
        table = mod_table(page, 82, "prefix")
        self.assertEqual([entry[0].template for entry in table], ["+# to mana", "+# to life"])
        self.assertAlmostEqual(sum(entry[1] for entry in table), 1)
        self.assertEqual([(tier, mod.level) for tier, mod, _ in table[1][2]], [(1, 50), (2, 1)])
        self.assertAlmostEqual(table[1][2][0][2], 0.1)

    def test_item_level_hides_tiers_and_keeps_their_numbers(self):
        table = mod_table(page_of(life(1, 300), life(50, 100)), 20, "prefix")
        self.assertEqual([(tier, mod.level) for tier, mod, _ in table[0][2]], [(2, 1)])
        self.assertAlmostEqual(table[0][1], 1)

    def test_a_side_with_nothing_is_empty(self):
        self.assertEqual(mod_table(page_of(life(50, 100)), 10, "prefix"), [])
        self.assertEqual(mod_table(page_of(life(1, 100)), 82, "suffix"), [])


class WantedModTests(unittest.TestCase):
    INDEX = {"explicit": {"# to life": ["explicit.life"], "adds # to # fire damage": ["explicit.fire", "explicit.fire_local"]}}

    def test_a_goal_asks_for_its_lowest_roll(self):
        mod = trade_search.wanted_mod(["+(61-73) to Life"], self.INDEX)
        self.assertEqual(mod.stats, (trade_search.StatFilter(("explicit.life",), 61.0),))

    def test_two_rolls_ask_for_their_average_like_the_site_does(self):
        mod = trade_search.wanted_mod(["Adds (10-12) to (20-24) Fire Damage"], self.INDEX)
        self.assertEqual(mod.stats[0].ids, ("explicit.fire", "explicit.fire_local"))
        self.assertEqual(mod.stats[0].value, 15)

    def test_a_wording_the_site_lacks_gives_no_filter(self):
        self.assertEqual(trade_search.wanted_mod(["+(1-2) to Nonsense"], self.INDEX).stats, ())
        self.assertEqual(trade_search.wanted_mod(["+(61-73) to Life", "+(1-2) to Nonsense"], self.INDEX).stats, ())

    def test_the_goal_becomes_a_search_of_at_least_that_roll(self):
        query = trade_search.build_query(None, "Tiara", False, [trade_search.wanted_mod(["+(61-73) to Life"], self.INDEX)], 1.0)
        self.assertEqual(query["query"]["stats"][0]["filters"], [{"id": "explicit.life", "value": {"min": 61}}])


class SimulationTests(unittest.TestCase):
    PRICES = {"Orb of Transmutation": 1.0, "Greater Orb of Transmutation": 5.0, "Perfect Orb of Transmutation": 20.0, "Orb of Augmentation": 1.0, "Greater Orb of Augmentation": 5.0, "Perfect Orb of Augmentation": 20.0,
              "Orb of Alchemy": 2.0, "Regal Orb": 2.0, "Greater Regal Orb": 8.0, "Perfect Regal Orb": 30.0, "Exalted Orb": 1.0, "Greater Exalted Orb": 10.0, "Perfect Exalted Orb": 40.0,
              "Chaos Orb": 1.0, "Greater Chaos Orb": 9.0, "Perfect Chaos Orb": 35.0, "Orb of Annulment": 10.0, "Fracturing Orb": 50.0, crafter.NEW_BASE: 1.0,
              **{name: 5.0 for name in crafter.OMENS}}

    def make_plan(self):
        mods = [Mod(f"m{number}", "prefix", 1, (f"g{number}",), 100, True, f"+(1-2) to stat{number}", f"+# to stat{number}") for number in range(6)]
        mods += [Mod(f"s{number}", "suffix", 1, (f"h{number}",), 100, True, f"+(1-2) to other{number}", f"+# to other{number}") for number in range(6)]
        page = Page("Test", mods)
        wants = [make_want(page.ladders[0], None, 82)]
        planner = Planner(page, 82, wants, self.PRICES)
        return planner.solve(State("normal", (0,), 0, 0))

    def test_the_average_of_the_runs_agrees_with_the_calculation(self):
        plan = self.make_plan()
        result = simulate_plan(plan, 4000, random.Random(5))
        expected = plan.values[plan.start]
        self.assertEqual(result.runs, 4000)
        self.assertLess(abs(result.mean - expected) / expected, 0.06)

    def test_bad_luck_costs_more_than_good_luck(self):
        result = simulate_plan(self.make_plan(), 2000, random.Random(7))
        self.assertLessEqual(result.median, result.unlucky)
        self.assertLessEqual(result.unlucky, result.worst)
        self.assertGreater(result.worst, result.median)

    def test_the_same_seed_gives_the_same_answer(self):
        plan = self.make_plan()
        self.assertEqual(simulate_plan(plan, 300, random.Random(1)), simulate_plan(plan, 300, random.Random(1)))

    def test_an_endless_plan_gives_up_without_an_answer(self):
        self.assertIsNone(simulate_plan(self.make_plan(), 2000, random.Random(1), budget=3))

    def test_a_short_budget_keeps_only_finished_runs(self):
        plan = self.make_plan()
        result = simulate_plan(plan, 100000, random.Random(1), budget=20000)
        self.assertGreater(result.runs, 100)
        self.assertLess(result.runs, 100000)

    def test_recipe_names_the_goal_and_the_steps(self):
        plan = self.make_plan()
        text = recipe_text(plan, "Тиара, ilvl 82", "5 Ex")
        lines = text.split("\n")
        self.assertEqual(lines[0], "Тиара, ilvl 82")
        self.assertIn(f"- {plan.planner.wants[0].label}", lines)
        self.assertIn("5 Ex", text)
        self.assertRegex(lines[-1], r"^\d+\. ")


class TranslationTests(unittest.TestCase):
    def test_every_caption_has_an_english_version(self):
        source = Path(tools.__file__).read_text(encoding="utf-8")
        captions = set(re.findall(r'\bt\("((?:[^"\\]|\\.)*)"\)', source)) | {title for _, title in (*tools.ToolsPage.TABS, *tools.ToolsPage.SIDE_TITLES)} | {"Предмет", "Куплено за", "Продано за"}
        self.assertGreater(len(captions), 40)
        self.assertEqual(sorted(caption for caption in captions if caption not in crafter.ENGLISH), [])

    def test_the_bookmark_button_has_an_english_version(self):
        self.assertIn("★ В закладки", crafter.ENGLISH)
        self.assertIn("★ В закладках", crafter.ENGLISH)


if __name__ == "__main__":
    unittest.main()
