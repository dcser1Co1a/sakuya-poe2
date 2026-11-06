import io
import json
import re
import unittest
import urllib.error
from datetime import datetime, timedelta
from email.message import Message
from pathlib import Path

import crafter
from market_demand import (
    ALL_TAB,
    CURRENCY_TAB,
    FEWEST_LISTINGS_FOR_DEMAND,
    UNIQUE_KINDS,
    DemandRow,
    demand_rows,
    demand_score,
    fetch_overview,
    kinds_due,
    merge_items,
    read_unique,
    update_demand,
)

NOW = datetime(2026, 11, 2, 12, 0, 0)
LINE = {"Name": "Ingenuity", "Type": "Utility Belt", "CurrentPrice": 10, "CurrentQuantity": 16081,
        "PriceLogs": [{"Price": 20, "Time": "2026-11-02T00:00:00Z", "Quantity": 500}, None, {"Price": 10, "Time": "2026-10-27T00:00:00Z", "Quantity": 1000}, {"Price": 15, "Time": "2026-10-30T00:00:00Z", "Quantity": 0}],
        "ItemMetadata": {"implicit_mods": ["Has (1-3) Charm Slot"], "explicit_mods": ["+(17-23)% to [Resistances|Chaos Resistance]"]}}


def reply(payload, headers=None):
    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    answer = Reply(json.dumps(payload).encode())
    answer.headers = headers or {}
    return answer


def fresh(minutes: int) -> dict:
    return {"source": "poe2scout", "updated": {kind: (NOW - timedelta(minutes=minutes)).isoformat() for kind in UNIQUE_KINDS}}


class ReadingTests(unittest.TestCase):
    def test_a_line_becomes_an_item_priced_in_divine(self):
        item = read_unique(LINE, 500, "accessory")
        self.assertEqual((item["kind"], item["base"], item["price"], item["listings"]), ("accessory", "Utility Belt", 0.02, 16081))
        self.assertEqual(item["mods"], ["Has (1-3) Charm Slot", "+(17-23)% to Chaos Resistance"])

    def test_history_runs_in_time_order_and_skips_empty_days(self):
        item = read_unique(LINE, 500, "accessory")
        self.assertEqual(item["spark"], [0.02, 0.04])
        self.assertEqual((item["change"], item["listings_change"]), (100, -50))

    def test_no_price_means_no_item(self):
        self.assertIsNone(read_unique({"Name": "A", "CurrentPrice": None}, 500, "accessory"))
        self.assertIsNone(read_unique({"CurrentPrice": 1}, 500, "accessory"))
        self.assertIsNone(read_unique({"Name": "INCOMPLETE", "CurrentPrice": 1}, 500, "accessory"))

    def test_an_item_without_history_has_no_trend(self):
        item = read_unique({"Name": "A", "CurrentPrice": 5, "PriceLogs": []}, 500, "accessory")
        self.assertEqual((item["change"], item["listings_change"], item["spark"]), (None, None, []))

    def test_the_most_listed_version_stays(self):
        lines = [{"Name": "A", "CurrentPrice": 1, "CurrentQuantity": 5}, {"Name": "A", "CurrentPrice": 9, "CurrentQuantity": 50}, {"Name": "A", "CurrentPrice": 2, "CurrentQuantity": 7}]
        self.assertEqual(merge_items({}, lines, "accessory", "tag", "stamp", 1)["items"]["A"]["price"], 9)

    def test_a_new_answer_replaces_only_its_own_kind(self):
        stored = {"items": {"Old": {"kind": "accessory"}, "Other": {"kind": "weapon"}}}
        self.assertEqual(list(merge_items(stored, [], "accessory", None, "stamp", 1)["items"]), ["Old", "Other"])  # a reply with nothing usable leaves the saved items alone
        self.assertEqual(list(merge_items(stored, [{"Name": "New", "CurrentPrice": 5}], "accessory", None, "stamp", 1)["items"]), ["Other", "New"])

    def test_unchanged_data_keeps_what_is_saved(self):
        stored = {"items": {"Old": {"kind": "accessory"}}}
        result = merge_items(stored, None, "accessory", "tag", "stamp", 1)
        self.assertEqual(result["items"], stored["items"])
        self.assertEqual((result["updated"]["accessory"], result["etags"]["accessory"]), ("stamp", "tag"))


class FetchTests(unittest.TestCase):
    def test_conditional_request(self):
        seen = []

        def opener(request, timeout):
            seen.append(request)
            error = urllib.error.HTTPError("https://x", 304, "same", Message(), io.BytesIO(b""))
            self.addCleanup(error.close)
            raise error

        self.assertEqual(fetch_overview("https://x", "tag", opener), (None, "tag"))
        self.assertEqual(seen[0].get_header("If-none-match"), "tag")
        self.assertTrue(seen[0].get_header("User-agent").isascii())

    def test_other_errors_are_not_hidden(self):
        def opener(request, timeout):
            error = urllib.error.HTTPError("https://x", 429, "slow", Message(), io.BytesIO(b""))
            self.addCleanup(error.close)
            raise error

        with self.assertRaises(urllib.error.HTTPError):
            fetch_overview("https://x", None, opener)

    def test_schedule(self):
        self.assertEqual(kinds_due({}, now=NOW), list(UNIQUE_KINDS))
        self.assertEqual(kinds_due(fresh(30), now=NOW), [])
        self.assertEqual(kinds_due(fresh(61), now=NOW), list(UNIQUE_KINDS))
        mixed = fresh(61)
        mixed["updated"][UNIQUE_KINDS[0]] = (NOW - timedelta(minutes=2)).isoformat()
        self.assertEqual(kinds_due(mixed, now=NOW), list(UNIQUE_KINDS[1:]))

    def test_data_from_the_old_source_counts_as_missing(self):
        self.assertEqual(kinds_due({"updated": fresh(1)["updated"]}, now=NOW), list(UNIQUE_KINDS))

    def test_only_what_is_wanted_is_asked_for(self):
        self.assertEqual(kinds_due({}, UNIQUE_KINDS[:1], NOW), list(UNIQUE_KINDS[:1]))
        self.assertEqual(kinds_due({}, (), NOW), [])
        urls = []

        def opener(request, timeout):
            urls.append(request.full_url)
            return reply({"Items": [], "Pages": 1})

        update_demand({}, "L", 500, lambda _: None, lambda: None, (), opener, lambda _: None)
        self.assertEqual(urls, [])
        update_demand({}, "L", 500, lambda _: None, lambda: None, UNIQUE_KINDS[:1], opener, lambda _: None)
        self.assertEqual(len(urls), 1)

    def test_one_request_per_kind_with_pauses_and_a_save_each(self):
        urls, saves, pauses = [], [], []

        def opener(request, timeout):
            urls.append(request.full_url)
            return reply({"Items": [], "Pages": 1}, {"ETag": "tag"})

        old = {"league": "Old", "source": "poe2scout", "items": {"A": {"kind": "weapon"}}}
        stored = update_demand(old, "Forbidden Rites", 500, saves.append, lambda: None, UNIQUE_KINDS, opener, pauses.append)
        self.assertEqual(len(urls), len(UNIQUE_KINDS))
        self.assertTrue(all("/poe2/Leagues/Forbidden%20Rites/Uniques/ByCategory?category=" in url and "perPage=250" in url for url in urls))
        self.assertEqual((len(saves), len(pauses)), (len(UNIQUE_KINDS), len(UNIQUE_KINDS)))
        self.assertEqual(stored["items"], {})  # those were the old league's items
        update_demand(stored, "Forbidden Rites", 500, saves.append, lambda: None, UNIQUE_KINDS, opener, pauses.append)
        self.assertEqual(len(urls), len(UNIQUE_KINDS))  # nothing is due yet

    def test_every_page_of_a_long_list_is_read(self):
        urls = []

        def opener(request, timeout):
            urls.append(request.full_url)
            return reply({"Items": [{"Name": f"N{len(urls)}", "CurrentPrice": 1}], "Pages": 2})

        stored = update_demand({}, "L", 1, lambda _: None, lambda: None, ("armour",), opener, lambda _: None)
        self.assertEqual(len(urls), 2)
        self.assertIn("page=2", urls[1])
        self.assertEqual(set(stored["items"]), {"N1", "N2"})


class DemandTests(unittest.TestCase):
    def row(self, change, listings_change, amount=1000):
        return DemandRow("A", "A", "", 1, amount, False, change, listings_change, (), ())

    def test_a_rising_price_and_shrinking_listings_both_add(self):
        self.assertEqual(demand_score(30, -20), 50)
        self.assertEqual(demand_score(-10, 40), -50)
        self.assertIsNone(demand_score(None, 5))

    def test_one_wild_week_is_limited(self):
        self.assertEqual(demand_score(5000, 0), 100)

    def test_words(self):
        self.assertEqual(self.row(30, -20).demand_word, "высокий")
        self.assertEqual(self.row(-30, 20).demand_word, "низкий")
        self.assertEqual(self.row(2, 1).demand_word, "средний")

    def test_few_listings_say_nothing_about_demand(self):
        self.assertIsNone(self.row(300, -50, FEWEST_LISTINGS_FOR_DEMAND - 1).demand_word)
        self.assertIsNone(self.row(None, None).demand_word)


class RowTests(unittest.TestCase):
    DEMAND = {"items": {"Cheap": {"kind": "accessory", "base": "Ring", "price": 0.01, "listings": 10000, "change": 5, "listings_change": 0},
                        "Dear": {"kind": "weapon", "base": "Axe", "price": 50, "listings": 10, "change": 90, "listings_change": -50},
                        "Hot": {"kind": "accessory", "base": "Belt", "price": 1, "listings": 50, "change": 60, "listings_change": -30}}}
    PRICES = {"prices_in_divine": {"A": 1, "B": 2}, "volumes": {"A": 50, "B": 5}, "changes": {"A": 1.5}}

    def rows(self, tab=ALL_TAB, sort="demand", query="", descending=True):
        return [row.name for row in demand_rows(self.DEMAND, self.PRICES, tab, query, sort, str, str, lambda q, text: q in text, descending)]

    def test_a_column_flips_and_empty_values_stay_last(self):
        self.assertEqual(self.rows(sort="demand", descending=False), ["Cheap", "Hot", "Dear"])
        self.assertEqual(self.rows(sort="amount"), ["Cheap", "Hot", "Dear"])
        self.assertEqual(self.rows(sort="amount", descending=False), ["Dear", "Hot", "Cheap"])
        self.assertEqual(self.rows(sort="change"), ["Dear", "Hot", "Cheap"])
        self.assertEqual(self.rows(sort="name", descending=False), ["Cheap", "Dear", "Hot"])

    def test_demand_comes_first_and_thin_markets_last(self):
        self.assertEqual(self.rows(), ["Hot", "Cheap", "Dear"])

    def test_other_orders(self):
        self.assertEqual(self.rows(sort="market"), ["Dear", "Cheap", "Hot"])
        self.assertEqual(self.rows(sort="price"), ["Dear", "Hot", "Cheap"])

    def test_a_lone_listing_at_a_wild_price_is_not_a_market(self):
        demand = {"items": {"Wild": {"kind": "weapon", "base": "Axe", "price": 42000000, "listings": 1}, "Real": {"kind": "weapon", "base": "Axe", "price": 5, "listings": 10}}}
        for sort in ("market", "price"):
            rows = demand_rows(demand, {}, ALL_TAB, "", sort, str, str, lambda q, text: True)
            self.assertEqual([row.name for row in rows], ["Real", "Wild"])

    def test_tabs_and_search(self):
        self.assertEqual(self.rows(tab="weapon"), ["Dear"])
        self.assertEqual(self.rows(query="Belt"), ["Hot"])

    def test_currency_ranks_by_volume_in_any_order_of_buttons(self):
        for sort in ("demand", "market"):
            self.assertEqual(self.rows(tab=CURRENCY_TAB, sort=sort), ["A", "B"])


class TranslationTests(unittest.TestCase):
    def test_every_caption_has_an_english_version(self):
        source = Path(crafter.__file__).with_name("market_demand.py").read_text(encoding="utf-8")
        captions = set(re.findall(r'self\.t\("([^"]+)"\)', source)) | set(re.findall(r'"([А-Яа-яЁё][^"]*)"\)[,)]', source))
        for word in ("высокий", "средний", "низкий", "Спрос", "Цена ≈", "История", "Неделя", "Предмет", "Объём", "Лотов"):
            captions.add(word)
        for caption in captions:
            self.assertIn(caption, crafter.ENGLISH)


if __name__ == "__main__":
    unittest.main()
