import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import crafter
import trade_search
import tools
from price_check import CopiedItem
from tray import NIF_INFO, NIM_MODIFY, TrayIcon
from tools import Stopwatch, add_history as tools_add_history, add_watch as tools_add_watch, format_time as tools_format_time, watches_reached as tools_watches_reached
from trade_search import ItemMod, StatFilter


def mod(label: str, covers: tuple = ()) -> ItemMod:
    return ItemMod(label, None, (StatFilter(("explicit.stat_1",), 1.0),), covers)


class FileTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        patcher = mock.patch.object(crafter, "LOG_PATH", self.folder / "errors.log")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_good_file_is_read(self):
        path = self.folder / "a.json"
        crafter.write_json(path, {"ключ": 1})
        self.assertEqual(crafter.read_json(path), {"ключ": 1})

    def test_a_missing_file_is_none(self):
        self.assertIsNone(crafter.read_json(self.folder / "none.json"))

    def test_a_damaged_file_is_set_aside_and_logged(self):
        path = self.folder / "a.json"
        path.write_text('{"half": ', encoding="utf-8")
        self.assertIsNone(crafter.read_json(path))
        self.assertFalse(path.exists())
        self.assertEqual((self.folder / "a.json.broken").read_text(encoding="utf-8"), '{"half": ')
        self.assertIn("a.json", crafter.LOG_PATH.read_text(encoding="utf-8"))

    def test_a_file_of_the_wrong_shape_counts_as_damaged(self):
        path = self.folder / "a.json"
        path.write_text("[1, 2]", encoding="utf-8")
        self.assertIsNone(crafter.read_json(path))

    def test_undecodable_bytes_count_as_damaged(self):
        path = self.folder / "a.json"
        path.write_bytes(b"\xff\xfe\x00broken")
        self.assertIsNone(crafter.read_json(path))

    def test_a_file_held_for_a_moment_is_still_written(self):
        path = self.folder / "a.json"
        real = Path.replace
        calls = []

        def busy_once(source, target):
            calls.append(target)
            if len(calls) == 1:
                raise PermissionError("held")
            return real(source, target)

        with mock.patch.object(Path, "replace", busy_once), mock.patch.object(crafter.time, "sleep"):
            crafter.write_json(path, {"a": 1})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"a": 1})
        self.assertEqual(len(calls), 2)

    def test_a_file_held_for_good_is_reported(self):
        with mock.patch.object(Path, "replace", side_effect=PermissionError("held")), mock.patch.object(crafter.time, "sleep"):
            with self.assertRaises(PermissionError):
                crafter.write_json(self.folder / "a.json", {"a": 1})

    def test_the_log_stays_small(self):
        crafter.LOG_PATH.write_text("x" * (crafter.LOG_MAX_BYTES + 10), encoding="utf-8")
        crafter.log_error("here", "what")
        self.assertLess(crafter.LOG_PATH.stat().st_size, crafter.LOG_MAX_BYTES)
        self.assertIn("what", crafter.LOG_PATH.read_text(encoding="utf-8"))

    def test_a_log_that_cannot_be_written_is_no_second_error(self):
        with mock.patch.object(crafter, "LOG_PATH", self.folder):  # a folder cannot be opened as a file
            crafter.log_error("here", "what")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.object(crafter, "LOG_PATH", Path(folder.name) / "errors.log")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_failed_service_starts_again(self):
        runs = []

        def service(value):
            runs.append(value)
            if len(runs) < 3:
                raise KeyError("odd reply")

        with mock.patch.object(crafter.time, "sleep") as pause:
            crafter.keep_running(service, "x")
        self.assertEqual(runs, ["x", "x", "x"])
        self.assertEqual(pause.call_count, 2)
        self.assertIn("odd reply", crafter.LOG_PATH.read_text(encoding="utf-8"))

    def test_a_service_that_ends_is_not_started_again(self):
        runs = []
        crafter.keep_running(runs.append, 1)
        self.assertEqual(runs, [1])


class DatabaseUpdateTests(unittest.TestCase):
    PATCHES = {"schema": crafter.SCHEMA_VERSION, "poe2db_patch": "0.5.5e", "game_version": "0.5.5.5"}

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for name, value in (("LOG_PATH", "errors.log"), ("DATA_PATH", "data.json"), ("UNIQUES_PATH", "uniques.json"), ("WAYSTONES_PATH", "waystones.json"), ("UPDATES_PATH", "updates.json")):
            patcher = mock.patch.object(crafter, name, self.folder / value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(crafter.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def data(self, pages: int = 10, mods: int = 5, bases: int = 10) -> dict:
        return {"pages": {str(page): {"mods": [{}] * mods} for page in range(pages)}, "bases": {str(base): {} for base in range(bases)}}

    def test_0_5_10_is_newer_than_0_5_9(self):
        self.assertEqual(max(["0.5.9", "0.5.10", "0.5.5e"], key=crafter.version_order), "0.5.10")

    def test_a_letter_makes_a_patch_newer(self):
        self.assertEqual(max(["0.5.5", "0.5.5e", "0.5.5a"], key=crafter.version_order), "0.5.5e")

    def test_empty_data_never_replaces_anything(self):
        with mock.patch.object(crafter, "Database"):
            self.assertFalse(crafter.data_is_sound({"pages": {}, "bases": {}}, None))
            self.assertFalse(crafter.data_is_sound(self.data(mods=0), None))

    def test_much_less_than_before_is_a_changed_site(self):
        with mock.patch.object(crafter, "Database"):
            self.assertFalse(crafter.data_is_sound(self.data(pages=7), self.data()))
            self.assertFalse(crafter.data_is_sound(self.data(mods=3), self.data()))
            self.assertFalse(crafter.data_is_sound(self.data(bases=2), self.data()))

    def test_ordinary_changes_of_a_patch_are_fine(self):
        with mock.patch.object(crafter, "Database"):
            self.assertTrue(crafter.data_is_sound(self.data(pages=9), self.data()))
            self.assertTrue(crafter.data_is_sound(self.data(pages=20), self.data()))
            self.assertTrue(crafter.data_is_sound(self.data(), None))

    def test_data_the_program_cannot_read_is_refused(self):
        with mock.patch.object(crafter, "Database", side_effect=KeyError("page")):
            self.assertFalse(crafter.data_is_sound(self.data(), self.data()))

    def test_a_changed_site_leaves_the_old_file_in_place(self):
        crafter.write_json(crafter.DATA_PATH, self.data())
        before = crafter.DATA_PATH.read_text(encoding="utf-8")
        with mock.patch.object(crafter, "fetch", lambda url, **_: "<html>a new layout</html>"), mock.patch.object(crafter, "read_repoe", return_value=(b"{}", "tag")):
            with self.assertRaises(ValueError):
                crafter.update_data(self.PATCHES, lambda _: None)
        self.assertEqual(crafter.DATA_PATH.read_text(encoding="utf-8"), before)

    def test_the_same_patch_reads_no_pages(self):
        crafter.write_json(crafter.DATA_PATH, {**self.PATCHES, "fetched_at": crafter.now_text()})
        with mock.patch.object(crafter, "update_data") as rebuild:
            crafter.update_mods(self.PATCHES, lambda _: None, lambda: None)
        rebuild.assert_not_called()

    def test_a_new_patch_rebuilds_and_tells_the_window(self):
        crafter.write_json(crafter.DATA_PATH, {**self.PATCHES, "poe2db_patch": "0.5.5d", "fetched_at": crafter.now_text()})
        told = []
        with mock.patch.object(crafter, "update_data") as rebuild:
            crafter.update_mods(self.PATCHES, lambda _: None, lambda: told.append(1))
        rebuild.assert_called_once()
        self.assertEqual(told, [1])

    def test_a_lost_file_is_rebuilt(self):
        with mock.patch.object(crafter, "update_data") as rebuild:
            crafter.update_mods(self.PATCHES, lambda _: None, lambda: None)
        rebuild.assert_called_once()

    def test_other_bases_follow_the_patch_and_the_calendar(self):
        fresh = {"fetched_at": crafter.now_text(), "game_version": "0.5.5.5"}
        self.assertFalse(crafter.base_is_due(fresh, self.PATCHES))
        self.assertTrue(crafter.base_is_due({**fresh, "game_version": "0.5.5.4"}, self.PATCHES))
        self.assertTrue(crafter.base_is_due({"fetched_at": "2020-01-01T00:00:00", "game_version": "0.5.5.5"}, self.PATCHES))
        self.assertTrue(crafter.base_is_due(None, self.PATCHES))
        self.assertFalse(crafter.base_is_due(fresh, {"game_version": None}))

    def test_a_shrunken_list_of_uniques_keeps_the_old_file(self):
        crafter.write_json(crafter.UNIQUES_PATH, {"fetched_at": "2020-01-01T00:00:00", "art": {str(number): "x" for number in range(100)}, "items": {}, "exchange": {}})
        before = crafter.UNIQUES_PATH.read_text(encoding="utf-8")
        with mock.patch.object(crafter, "fetch", return_value="{}"), mock.patch.object(crafter, "read_repoe", return_value=(b"{}", "tag")):
            with self.assertRaises(ValueError):
                crafter.update_uniques(self.PATCHES, lambda _: None, lambda: None)
        self.assertEqual(crafter.UNIQUES_PATH.read_text(encoding="utf-8"), before)

    def uniques_file(self, **changes) -> dict:
        return {"fetched_at": crafter.now_text(), "game_version": "0.5.5.5", "tags": {"uniques": "u1", "base_items": "b1"}, "art": {"a": "x"}, "items": {}, "exchange": {}, **changes}

    def test_unchanged_files_cost_no_rebuild(self):
        crafter.write_json(crafter.UNIQUES_PATH, self.uniques_file())
        told = []
        with mock.patch.object(crafter, "read_repoe", side_effect=[(None, "u1"), (None, "b1")]), mock.patch.object(crafter, "fetch") as page:
            crafter.update_uniques(self.PATCHES, lambda _: None, lambda: told.append(1))
        page.assert_not_called()
        self.assertEqual(told, [])

    def test_a_quiet_correction_without_a_new_version_is_noticed(self):
        crafter.write_json(crafter.UNIQUES_PATH, self.uniques_file())
        told = []
        answers = {"uniques.min.json": (b"{}", "u2"), "base_items.min.json": (None, "b1")}
        with mock.patch.object(crafter, "read_repoe", side_effect=lambda name, tag=None: answers[name] if tag else (b"{}", "b1")), mock.patch.object(crafter, "fetch", return_value=""), mock.patch.object(crafter, "read_unique_art", return_value={"a": "x"}):
            crafter.update_uniques(self.PATCHES, lambda _: None, lambda: told.append(1))
        self.assertEqual(told, [1])
        self.assertEqual(crafter.read_json(crafter.UNIQUES_PATH)["tags"], {"uniques": "u2", "base_items": "b1"})

    def test_a_file_comes_down_once_in_a_pass(self):
        crafter._repoe_pass.clear()
        self.addCleanup(crafter._repoe_pass.clear)
        with mock.patch.object(crafter, "download", return_value=(b"body", "t1")) as down:
            self.assertEqual(crafter.read_repoe("a.json"), (b"body", "t1"))
            self.assertEqual(crafter.read_repoe("a.json", "t1"), (None, "t1"))
            self.assertEqual(crafter.read_repoe("a.json"), (b"body", "t1"))
        self.assertEqual(down.call_count, 1)

    def test_unchanged_on_the_site_is_no_download_and_no_error(self):
        crafter._repoe_pass.clear()
        self.addCleanup(crafter._repoe_pass.clear)
        refusal = crafter.urllib.error.HTTPError("u", 304, "Not Modified", None, None)
        with mock.patch.object(crafter, "download", side_effect=refusal) as down:
            self.assertEqual(crafter.read_repoe("a.json", "t1"), (None, "t1"))
        self.assertEqual(down.call_args[0][0].get_header("If-none-match"), "t1")

    def test_a_refusal_is_not_asked_again(self):
        for code in (403, 404, 429):
            with mock.patch.object(crafter.urllib.request, "urlopen", side_effect=crafter.urllib.error.HTTPError("u", code, "no", None, None)) as opened:
                with self.assertRaises(crafter.urllib.error.HTTPError):
                    crafter.fetch_bytes("https://x")
            self.assertEqual(opened.call_count, 1, code)

    def test_a_server_having_a_bad_moment_is_asked_again(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"ok"
        with mock.patch.object(crafter.urllib.request, "urlopen", side_effect=[crafter.urllib.error.HTTPError("u", 503, "busy", None, None), crafter.urllib.error.URLError("no network"), response]) as opened:
            self.assertEqual(crafter.fetch_bytes("https://x"), b"ok")
        self.assertEqual(opened.call_count, 3)

    def test_links_with_the_language_in_front_give_names(self):
        page = '<a class="gem_blue" href="/ru/Arbiters_Ignition">Воспламенение Арбитра</a><a href="Omen_of_Light">Знамение света</a><a href="/ru/Omen">RU Русский</a><a href="/ru/Fan#x">Метка</a><a href="/tw/Omen">TW 繁體中文</a><a href="/ru/">PoE2DB</a><a href="https://example.com/a">Сайт</a>'
        self.assertEqual(crafter.read_names(page), {"arbiters ignition": "Воспламенение Арбитра", "omen of light": "Знамение света"})

    def test_an_item_gives_its_name_on_its_own_page(self):
        page = "<html><head><title>Взгляд Аманаму - PoE2DB, Path of Exile Wiki ru</title></head></html>"
        with mock.patch.object(crafter, "fetch", return_value=page) as fetched:
            self.assertEqual(crafter.own_page_name("Amanamu's Gaze"), "Взгляд Аманаму")
        self.assertTrue(fetched.call_args[0][0].endswith("/ru/Amanamus_Gaze"))

    def test_a_title_in_english_is_no_russian_name(self):
        with mock.patch.object(crafter, "fetch", return_value="<title>Some Item - PoE2DB</title>"):
            self.assertIsNone(crafter.own_page_name("Some Item"))

    def test_an_item_without_a_page_has_no_name(self):
        with mock.patch.object(crafter, "fetch", side_effect=crafter.urllib.error.HTTPError("u", 404, "no", None, None)):
            self.assertIsNone(crafter.own_page_name("Nothing"))

    def test_a_refused_page_stops_the_search_for_names(self):
        with mock.patch.object(crafter, "fetch", side_effect=crafter.urllib.error.HTTPError("u", 403, "no", None, None)):
            with self.assertRaises(crafter.urllib.error.HTTPError):
                crafter.own_page_name("Anything")

    def test_only_nameless_items_are_looked_up_and_failures_wait_a_week(self):
        long_ago = "2020-01-01T00:00:00"
        priced = ["Amanamu's Gaze", "Chaos Orb", "Lost Item", "Old Failure"]
        keys = {"chaos orb": "Сфера хаоса"}
        self.assertEqual(crafter.names_to_look_up(priced, keys, {"Lost Item": crafter.now_text(), "Old Failure": long_ago}), ["Amanamu's Gaze", "Old Failure"])

    def names_on_file(self):
        crafter.write_json(crafter.DATA_PATH, {"currency_keys": {"chaos orb": "Сфера хаоса"}})

    def test_found_names_reach_the_file_and_the_window(self):
        self.names_on_file()
        told = []
        with mock.patch.object(crafter, "read_prices", return_value={"prices_in_divine": {"Chaos Orb": 1, "A Gaze": 1, "No Page": 1}}), mock.patch.object(crafter, "own_page_name", side_effect=lambda name: "Взгляд" if name == "A Gaze" else None):
            crafter.update_names(self.PATCHES, lambda _: None, lambda: told.append(1))
        stored = crafter.read_json(crafter.DATA_PATH)
        self.assertEqual(stored["currency_keys"]["a gaze"], "Взгляд")
        self.assertEqual(stored["names_from_own_pages"], {"a gaze": "Взгляд"})
        self.assertIn("No Page", stored["names_not_found"])
        self.assertEqual(told, [1])

    def test_names_found_before_a_refusal_are_kept(self):
        self.names_on_file()
        answers = iter(["Взгляд", crafter.urllib.error.HTTPError("u", 429, "slow", None, None)])

        def answer(_):
            value = next(answers)
            if isinstance(value, Exception):
                raise value
            return value

        with mock.patch.object(crafter, "read_prices", return_value={"prices_in_divine": {"A": 1, "B": 1}}), mock.patch.object(crafter, "own_page_name", side_effect=answer):
            with self.assertRaises(crafter.urllib.error.HTTPError):
                crafter.update_names(self.PATCHES, lambda _: None, lambda: None)
        self.assertEqual(crafter.read_json(crafter.DATA_PATH)["currency_keys"]["a"], "Взгляд")

    def test_all_names_known_means_no_requests(self):
        self.names_on_file()
        with mock.patch.object(crafter, "read_prices", return_value={"prices_in_divine": {"Chaos Orb": 1}}), mock.patch.object(crafter, "own_page_name") as looked:
            crafter.update_names(self.PATCHES, lambda _: None, lambda: None)
        looked.assert_not_called()

    def test_many_lost_names_are_reported(self):
        crafter.write_json(crafter.DATA_PATH, {"currency_keys": {}, "names_not_found": {"A": crafter.now_text(), "B": crafter.now_text()}})
        said = []
        with mock.patch.object(crafter, "read_prices", return_value={"prices_in_divine": {"A": 1, "B": 1}}):
            crafter.update_names(self.PATCHES, said.append, lambda: None)
        self.assertEqual(len(said), 1)
        self.assertIn("0 of 2", crafter.LOG_PATH.read_text(encoding="utf-8"))

    def test_a_rebuild_keeps_names_from_own_pages(self):
        crafter.write_json(crafter.DATA_PATH, {"names_from_own_pages": {"a gaze": "Взгляд"}, "currency_keys": {"a gaze": "Взгляд"}})
        with mock.patch.object(crafter, "fetch", lambda url, **_: ""), mock.patch.object(crafter, "read_repoe", return_value=(b"{}", "t")), mock.patch.object(crafter, "data_is_sound", return_value=True):
            crafter.update_data(self.PATCHES, lambda _: None)
        stored = crafter.read_json(crafter.DATA_PATH)
        self.assertEqual(stored["currency_keys"]["a gaze"], "Взгляд")
        self.assertEqual(stored["names_from_own_pages"], {"a gaze": "Взгляд"})

    MAP = "<loc>https://poe.ninja/poe2/economy/forbiddenrites/currency</loc><loc>https://poe.ninja/poe2/economy/forbiddenrites/new-thing</loc><loc>https://poe.ninja/poe2/economy/forbiddenriteshc/other-thing</loc>"

    def test_a_new_section_of_the_market_is_seen(self):
        self.assertEqual(crafter.new_market_sections(self.MAP, "Forbidden Rites", {"currency"}), ["new-thing"])

    def test_a_map_without_the_league_says_nothing(self):
        self.assertEqual(crafter.new_market_sections(self.MAP, "Some Other League", {"currency"}), [])

    def test_a_section_with_no_data_is_said_once_and_the_map_read_once_a_day(self):
        said = []
        maps = []

        def fetched(url, **_):
            maps.append(url) if url == crafter.NINJA_SITEMAP else None
            return self.MAP if url == crafter.NINJA_SITEMAP else "{}"

        with mock.patch.object(crafter, "MARKET_SECTIONS_PATH", self.folder / "market.json"), mock.patch.object(crafter, "read_prices", return_value={"league": "Forbidden Rites"}), mock.patch.object(crafter, "fetch", fetched):
            crafter.update_market_sections(self.PATCHES, said.append, None)
            crafter.update_market_sections(self.PATCHES, said.append, None)
            self.assertEqual(len(maps), 1)
            self.assertEqual(len(said), 1)
            stored = crafter.read_json(crafter.MARKET_SECTIONS_PATH)
            self.assertEqual(stored["reported"], ["new-thing"])
            crafter.write_json(crafter.MARKET_SECTIONS_PATH, {**stored, "checked_at": "2020-01-01T00:00:00"})
            crafter.update_market_sections(self.PATCHES, said.append, None)
            self.assertEqual(len(maps), 2)
            self.assertEqual(len(said), 1)

    def restore_market(self):
        import market_demand
        kinds, sections, titles = list(market_demand.UNIQUE_KINDS), list(crafter.PRICE_KINDS), dict(market_demand.LEARNED_UNIQUE_TITLES)

        def restore():
            market_demand.UNIQUE_KINDS[:] = kinds
            crafter.PRICE_KINDS[:] = sections
            crafter.LEARNED_SECTIONS.clear()
            market_demand.LEARNED_UNIQUE_TITLES.clear()
            market_demand.LEARNED_UNIQUE_TITLES.update(titles)

        self.addCleanup(restore)

    def test_a_new_section_is_taken_in_by_itself(self):
        self.restore_market()
        said = []

        def fetched(url, **_):
            if url == crafter.NINJA_SITEMAP:
                return self.MAP
            return json.dumps({"lines": [{"id": "a"}]}) if "type=NewThing" in url else "{}"

        with mock.patch.object(crafter, "MARKET_SECTIONS_PATH", self.folder / "market.json"), mock.patch.object(crafter, "read_prices", return_value={"league": "Forbidden Rites"}), mock.patch.object(crafter, "fetch", fetched):
            crafter.update_market_sections(self.PATCHES, said.append, None)
        self.assertIn("NewThing", crafter.PRICE_KINDS)
        self.assertIn("NewThing", crafter.UpdateInterest().wanted_sections({"NewThing": "2026-01-01T00:00:00"}))
        self.assertEqual(crafter.price_section("New Good", {"kinds": {"New Good": "NewThing"}}), crafter.OTHER_SECTION)
        self.assertIn("NewThing", said[0])

    def test_section_names_are_guessed_from_the_address(self):
        self.assertEqual(crafter.section_kinds("soul-cores"), ["SoulCores", "Soul"])
        self.assertEqual(crafter.section_kinds("breach-catalyst"), ["BreachCatalyst", "Breach"])
        self.assertEqual(crafter.section_kinds("runes"), ["Runes"])

    def test_a_new_kind_of_unique_is_taken_in_with_its_title(self):
        import market_demand
        self.restore_market()
        self.assertEqual(market_demand.learn_unique_kinds([["weapon", "Weapons"], ["relic", "Relics"]]), ["relic"])
        self.assertIn("relic", market_demand.UNIQUE_KINDS)
        self.assertEqual(market_demand.LEARNED_UNIQUE_TITLES, {"relic": "Relics"})

    def test_categories_are_read_and_odd_ones_dropped(self):
        import market_demand
        unique, currency = market_demand.read_categories({"UniqueCategories": [{"ApiId": "a", "Label": "A"}, 5, {"Label": "x"}, {"ApiId": "b"}], "CurrencyCategories": "x"})
        self.assertEqual((unique, currency), ([["a", "A"], ["b", "b"]], []))
        self.assertEqual(market_demand.read_categories({}), ([], []))

    def test_a_good_only_poe2scout_has_gets_its_price_and_poe_ninjas_stay(self):
        stored = {"exalted_per_divine": 500, "prices_in_divine": {"Chaos Orb": 0.1}, "kinds": {"Chaos Orb": "Currency"}, "icons": {}}
        lines = [{"Text": "New Coin", "CurrentPrice": 250, "IconUrl": "https://x/i.png"}, {"Text": "Chaos Orb", "CurrentPrice": 99}, {"Text": "Bad", "CurrentPrice": "x"}, 5, {"CurrentPrice": 1}]
        result = crafter.scout_lines_to_prices(stored, lines)
        self.assertEqual(result["prices_in_divine"], {"Chaos Orb": 0.1, "New Coin": 0.5})
        self.assertEqual(result["kinds"]["New Coin"], crafter.SCOUT_KIND)
        self.assertEqual(crafter.price_section("New Coin", result), crafter.OTHER_SECTION)
        again = crafter.scout_lines_to_prices(result, [{"Text": "New Coin", "CurrentPrice": 500}])
        self.assertEqual(again["prices_in_divine"]["New Coin"], 1)

    def test_only_a_category_poe_ninja_lacks_is_asked_of_poe2scout(self):
        crafter.write_json(self.folder / "market.json", {"currency_categories": [["currency", "Currency"], ["newcoins", "New"]]})
        asked = []

        def overview(url, tag):
            asked.append(url)
            return {"Items": [{"Text": "New Coin", "CurrentPrice": 50}]}, None

        with mock.patch.object(crafter, "MARKET_SECTIONS_PATH", self.folder / "market.json"), mock.patch.object(crafter, "PRICES_PATH", self.folder / "prices.json"), mock.patch.object(crafter, "fetch_overview", overview):
            stored = {"league": "L", "exalted_per_divine": 100, "prices_in_divine": {}}
            result = crafter.update_scout_currency(stored, lambda: None)
            self.assertEqual(result["prices_in_divine"], {"New Coin": 0.5})
            crafter.update_scout_currency(result, lambda: None)
        self.assertEqual(len(asked), 1)
        self.assertIn("category=newcoins", asked[0])

    def test_a_newer_release_is_noticed(self):
        good = {"tag_name": "v1.2.0", "html_url": "https://x"}
        self.assertEqual(crafter.read_release(good, "1.1.9"), ("v1.2.0", "https://x"))
        self.assertIsNone(crafter.read_release(good, "1.2.0"))
        self.assertIsNone(crafter.read_release(good, "1.10.0"))
        self.assertIsNone(crafter.read_release({**good, "prerelease": True}, "1.0.0"))
        self.assertIsNone(crafter.read_release({**good, "tag_name": "nightly"}, "1.0.0"))
        self.assertIsNone(crafter.read_release({}, "1.0.0"))

    def test_with_no_repository_nothing_is_asked(self):
        with mock.patch.object(crafter, "GITHUB_REPOSITORY", ""), mock.patch.object(crafter, "fetch") as fetched:
            crafter.update_program(self.PATCHES, lambda _: None, None)
        fetched.assert_not_called()

    def test_one_failed_base_does_not_stop_the_others(self):
        ran = []

        def fails(*_):
            raise AttributeError("a page changed")

        def works(*_):
            ran.append("works")

        said = []
        with mock.patch.object(crafter, "find_patches", return_value=self.PATCHES):
            state = crafter.check_databases({}, said.append, ((fails, None), (works, None)))
        self.assertEqual(ran, ["works"])
        self.assertEqual(state["failures"], 1)
        self.assertIn("a page changed", state["last_error"])
        self.assertIn("a page changed", crafter.LOG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(said), 1)

    def test_no_connection_is_tried_again_soon_then_less_often(self):
        self.assertEqual([crafter.retry_pause(number).total_seconds() / 60 for number in (1, 2, 3, 4, 5, 6, 7, 40)], [10, 20, 40, 80, 160, 320, 360, 360])
        with mock.patch.object(crafter, "find_patches", side_effect=OSError("no network")):
            state = crafter.check_databases({"failures": 2}, lambda _: None, ())
        self.assertEqual(state["failures"], 3)
        wait = crafter.datetime.fromisoformat(state["next_check"]) - crafter.datetime.now()
        self.assertLess(abs(wait.total_seconds() - 2400), 5)

    def test_success_forgets_the_failures_and_waits_for_the_next_check(self):
        with mock.patch.object(crafter, "find_patches", return_value=self.PATCHES):
            state = crafter.check_databases({"failures": 4}, lambda _: None, ())
        self.assertEqual(state["failures"], 0)
        self.assertIsNone(state["last_error"])
        wait = crafter.datetime.fromisoformat(state["next_check"]) - crafter.datetime.now()
        self.assertLess(abs(wait - crafter.DATA_CHECK_INTERVAL).total_seconds(), 5)

    def test_a_restart_before_the_next_check_asks_for_nothing(self):
        for path in (crafter.DATA_PATH, crafter.UNIQUES_PATH, crafter.WAYSTONES_PATH):
            path.write_text("{}", encoding="utf-8")
        later = (crafter.datetime.now() + crafter.timedelta(hours=1)).isoformat()
        self.assertFalse(crafter.check_is_due({"next_check": later}))
        self.assertTrue(crafter.check_is_due({"next_check": "2020-01-01T00:00:00"}))
        self.assertTrue(crafter.check_is_due({}))

    def test_a_lost_file_does_not_wait_for_the_next_check(self):
        later = (crafter.datetime.now() + crafter.timedelta(hours=1)).isoformat()
        self.assertTrue(crafter.check_is_due({"next_check": later}))


class FileShapeTests(unittest.TestCase):
    ODD = (None, 0, -1, 5, "x", "", True, [], {}, [None], {"x": None}, 1e308, float("nan"), [[]], {"x": {"y": None}})
    GOOD = {
        "prices": {"league": "L", "exalted_per_divine": 600, "chaos_per_divine": 9, "prices_in_divine": {"Chaos Orb": 0.1}, "kinds": {"Chaos Orb": "Currency"}, "icons": {"Chaos Orb": "a"}, "changes": {"Chaos Orb": 1.0}, "sparklines": {"Chaos Orb": [1, None]}, "volumes": {"Chaos Orb": 5}, "updated": {"Currency": "2026-01-01T00:00:00"}, "etags": {"Currency": "t"}, "fetched_at": "2026-01-01T00:00:00", "league_checked": "2026-01-01T00:00:00", "skipped_leagues": ["X"], "retry_after": "2026-01-01T00:00:00"},
        "settings": {"language": "ru", "hotkeys": {"copy": {"mods": 2, "vk": 69}}, "price_window": "+1+1", "craft_mode": "budget", "theme": "yozakura", "petals": True, "craft_banned": ["Regal Orb"], "craft_budget": "5"},
        "demand": {"league": "L", "source": "s", "items": {"A": {"kind": "weapon", "price": 1.0, "base": "B", "listings": 3, "change": 1.0, "listings_change": 2.0, "spark": [1.0], "mods": ["m"], "icon": "i"}}, "updated": {"weapon": "2026-01-01T00:00:00"}, "etags": {"weapon": "t"}},
        "uniques": {"art": {"a": "b"}, "russian": {"a": "б"}, "items": {"a": "b"}, "exchange": {"a": "b"}, "tags": {"uniques": "t"}, "fetched_at": "2026-01-01T00:00:00", "game_version": "0.5"},
        "waystones": {"kinds": [{"key": "k", "side": "prefix", "ru": "к", "forms": ["k", "к"]}], "rewards": {"ru": ["н"]}, "fetched_at": "2026-01-01T00:00:00"},
        "tools": {"bookmarks": [{"name": "n", "price": "p", "link": "l", "date": "d"}], "journal": [{"name": "n", "bought": 1.0, "sold": None, "unit": "Divine Orb", "date": "d", "bought_exalted": 600.0, "sold_exalted": None}], "waystone_danger": ["k"], "search_memory": {"k": {"stats": ["1"], "strictness": 0.9}}},
        "trade_stats": {"ru": {"fetched_at": "2026-01-01T00:00:00", "index": {"a": {"explicit": ["x"]}}}},
        "updates": {"checked_at": "2026-01-01T00:00:00", "next_check": "2026-01-01T00:00:00", "failures": 2, "last_error": None},
        "patch_watch": {"build": 5, "rush_since": "2026-01-01T00:00:00", "data_then": ["a", "b"]},
        "market_sections": {"checked_at": "2026-01-01T00:00:00", "reported": ["x"]},
    }

    def cleaner(self, name):
        import shapes
        return getattr(shapes, f"clean_{name}")

    def test_good_files_pass_untouched(self):
        for name, good in self.GOOD.items():
            cleaned = self.cleaner(name)(json.loads(json.dumps(good)))
            for key, value in good.items():
                self.assertEqual(cleaned.get(key), value, (name, key))

    def test_nothing_read_from_disk_raises_and_good_parts_survive(self):
        import itertools
        for name, good in self.GOOD.items():
            clean = self.cleaner(name)
            self.assertIsInstance(clean({}), dict)
            for key, odd in itertools.product(good, self.ODD):
                damaged = json.loads(json.dumps(good))
                damaged[key] = odd
                self.assertIsInstance(clean(damaged), dict)
                value = good[key]
                if isinstance(value, dict) and value:
                    inner = next(iter(value))
                    damaged = json.loads(json.dumps(good))
                    damaged[key][inner] = odd
                    self.assertIsInstance(clean(damaged), dict)
                    if isinstance(value[inner], dict):
                        for deep in value[inner]:
                            damaged = json.loads(json.dumps(good))
                            damaged[key][inner][deep] = odd
                            self.assertIsInstance(clean(damaged), dict)
                if isinstance(value, list) and value:
                    damaged = json.loads(json.dumps(good))
                    damaged[key][0] = odd
                    self.assertIsInstance(clean(damaged), dict)

    def test_an_odd_rate_drops_every_price(self):
        import shapes
        for odd in (0, -1, None, "x", True, float("nan")):
            self.assertNotIn("prices_in_divine", shapes.clean_prices({**self.GOOD["prices"], "exalted_per_divine": odd}))

    def test_an_odd_price_goes_and_the_others_stay(self):
        import shapes
        result = shapes.clean_prices({**self.GOOD["prices"], "prices_in_divine": {"A": "x", "B": -1, "C": 0, "D": None, "E": 2}})
        self.assertEqual(result["prices_in_divine"], {"E": 2})

    def test_a_damaged_note_goes_and_the_others_stay(self):
        import shapes
        good = self.GOOD["tools"]["bookmarks"][0]
        self.assertEqual(shapes.clean_tools({"bookmarks": [5, good, {"name": 1}]})["bookmarks"], [good])

    def test_an_odd_waystone_list_means_the_usual_one_not_none_at_all(self):
        import shapes
        self.assertNotIn("waystone_danger", shapes.clean_tools({"waystone_danger": 5}))

    def test_an_odd_hotkey_falls_back_to_the_usual_one(self):
        import shapes
        cleaned = shapes.clean_settings({"hotkeys": {"copy": {"mods": "x", "vk": 69}, "price": {"mods": 2, "vk": 71}, "toggle": 5}})
        self.assertEqual(cleaned["hotkeys"], {"price": {"mods": 2, "vk": 71}})

    def test_a_half_written_rush_ends(self):
        import shapes
        self.assertIsNone(shapes.clean_patch_watch({"rush_since": "2026-01-01T00:00:00", "data_then": 5})["rush_since"])


class LeagueTests(unittest.TestCase):
    STATE = {"economyLeagues": [{"name": "Rites", "hardcore": False}, {"name": "Old", "hardcore": False}, {"name": "HC Rites", "hardcore": True}, {"name": "HC Old", "hardcore": True}, {"name": "Standard", "hardcore": False}, {"name": "Hardcore", "hardcore": True}]}
    LISTED = STATE["economyLeagues"]

    def test_with_no_choice_it_is_the_newest_trade_league(self):
        self.assertEqual(crafter.league_candidates(self.STATE)[0], "Rites")
        self.assertEqual(crafter.league_candidates(self.STATE, crafter.AUTO_LEAGUE), ["Rites", "Old", "Standard"])

    def test_the_hardcore_choice_keeps_to_hardcore(self):
        self.assertEqual(crafter.league_candidates(self.STATE, crafter.AUTO_HARDCORE), ["HC Rites", "HC Old", "Hardcore"])

    def test_one_named_league_comes_first(self):
        self.assertEqual(crafter.league_candidates(self.STATE, "Old")[0], "Old")
        self.assertEqual(crafter.league_candidates(self.STATE, "Standard")[0], "Standard")
        self.assertEqual(crafter.league_candidates(self.STATE, "Hardcore")[0], "Hardcore")

    def test_a_named_league_that_has_ended_falls_back_on_its_kind(self):
        self.assertEqual(crafter.league_candidates(self.STATE, "HC Gone Long Ago")[0], "HC Rites")
        self.assertEqual(crafter.league_candidates(self.STATE, "Gone Long Ago")[0], "Rites")

    def test_picking_the_newest_of_a_kind_follows_the_next_league(self):
        self.assertEqual(crafter.league_rule("Rites", self.LISTED), crafter.AUTO_LEAGUE)
        self.assertEqual(crafter.league_rule("HC Rites", self.LISTED), crafter.AUTO_HARDCORE)
        new_league = {"economyLeagues": [{"name": "Next", "hardcore": False}, {"name": "HC Next", "hardcore": True}, *self.LISTED]}
        self.assertEqual(crafter.league_candidates(new_league, crafter.AUTO_HARDCORE)[0], "HC Next")

    def test_picking_any_other_stays_there(self):
        self.assertEqual(crafter.league_rule("Old", self.LISTED), "Old")
        self.assertEqual(crafter.league_rule("Standard", self.LISTED), "Standard")
        self.assertEqual(crafter.league_rule("Hardcore", self.LISTED), "Hardcore")

    def test_the_list_of_leagues_is_kept_for_the_window(self):
        result = crafter.apply_league({}, self.STATE, crafter.AUTO_HARDCORE)
        self.assertEqual(result["league"], "HC Rites")
        self.assertEqual([league["name"] for league in result["leagues"]][:2], ["Rites", "Old"])

    def folder(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        for name, value in (("PRICES_PATH", "prices.json"), ("DEMAND_PATH", "demand.json"), ("LEAGUE_FOLDER", "leagues"), ("LOG_PATH", "errors.log")):
            patcher = mock.patch.object(crafter, name, root / value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return root

    def test_each_league_keeps_what_it_has_seen(self):
        self.folder()
        crafter.write_json(crafter.PRICES_PATH, {"league": "Rites", "exalted_per_divine": 600, "prices_in_divine": {"Chaos Orb": 0.1}, "leagues": self.LISTED})
        crafter.write_json(crafter.DEMAND_PATH, {"league": "Rites", "items": {"A": {"kind": "weapon", "price": 1}}})
        crafter.switch_league_files("Rites", "HC Rites")
        self.assertEqual(crafter.read_json(crafter.PRICES_PATH)["league"], "HC Rites")
        self.assertNotIn("prices_in_divine", crafter.read_json(crafter.PRICES_PATH))
        self.assertEqual(crafter.read_json(crafter.PRICES_PATH)["leagues"], self.LISTED)
        self.assertEqual(crafter.read_json(crafter.DEMAND_PATH), {"league": "HC Rites"})
        crafter.write_json(crafter.PRICES_PATH, {"league": "HC Rites", "exalted_per_divine": 300, "prices_in_divine": {"Chaos Orb": 0.5}, "leagues": self.LISTED})
        crafter.switch_league_files("HC Rites", "Rites")
        back = crafter.read_json(crafter.PRICES_PATH)
        self.assertEqual((back["league"], back["prices_in_divine"]), ("Rites", {"Chaos Orb": 0.1}))
        self.assertEqual(crafter.read_json(crafter.DEMAND_PATH)["items"]["A"]["price"], 1)

    def test_an_answer_for_the_old_league_is_not_saved(self):
        self.folder()
        board = crafter.LeagueBoard()
        crafter.write_json(crafter.PRICES_PATH, {"league": "New"})
        started = board.switches
        board.switches += 1
        with self.assertRaises(crafter.LeagueSwitched):
            board.save_prices({"league": "Old"}, started)
        self.assertEqual(crafter.read_json(crafter.PRICES_PATH)["league"], "New")
        with self.assertRaises(crafter.LeagueSwitched):
            board.save_demand({"league": "Old"}, started)
        board.save_prices({"league": "New", "x": 1}, board.switches)
        self.assertEqual(crafter.read_json(crafter.PRICES_PATH)["x"], 1)

    def test_a_watched_section_stays_fresh_with_nobody_at_the_computer(self):
        now = [0.0]
        interest = crafter.UpdateInterest(lambda: now[0])
        interest.watched = frozenset({"Runes", "armour"})
        now[0] = crafter.ACTIVE_SECONDS + 1
        self.assertEqual(interest.wanted_sections({}), ["Runes"])
        self.assertEqual(interest.wanted_uniques(), ["armour"])


class IdeasOnPaperTests(unittest.TestCase):
    def test_the_total_counts_stacks_and_how_many(self):
        history = tools.add_history([], "A", "a", "1", "A", "d", 3)
        history = tools.add_history(history, "B", "b", "1", "B", "d")
        history = tools.add_history(history, "C", "c", "", None, "d")
        history = tools.change_count(history, "b", 1)
        self.assertEqual(tools.history_total(history, {"A": 2.0, "B": 5.0}.get), (16.0, 1))
        history = tools.change_count(history, "a", -1)
        self.assertEqual(tools.history_total(history, {"A": 2.0, "B": 5.0}.get), (10.0, 1))

    def test_the_count_stays_in_bounds_and_survives_a_new_check(self):
        history = tools.add_history([], "A", "a", "1", "A", "d")
        history = tools.change_count(history, "a", -5)
        self.assertEqual(history[0]["count"], 0)
        history = tools.change_count(history, "a", 5000)
        self.assertEqual(history[0]["count"], 999)
        history = tools.add_history(history, "A", "a", "2", "A", "d2")
        self.assertEqual((history[0]["count"], history[0]["price"]), (999, "2"))

    def test_an_old_history_without_counts_still_adds_up(self):
        self.assertEqual(tools.history_total([{"copied": "a", "priced_name": "A"}], {"A": 2.0}.get), (2.0, 0))

    def test_the_same_goal_stays_one(self):
        mods = [{"template": "T", "side": "prefix", "desecrated": False, "tier": 2}]
        goals = tools.add_craft_goal([], "Ring", 82, mods, "one")
        goals = tools.add_craft_goal(goals, "Ring", 82, [{**mods[0], "tier": 1}], "two")
        goals = tools.add_craft_goal(goals, "Ring", 82, mods, "again")
        self.assertEqual([goal["label"] for goal in goals], ["again", "two"])

    def test_the_stash_line(self):
        self.assertEqual(tools.stash_words(' a b, "c" ,, d|e '), ["a b", "c", "d", "e"])
        self.assertEqual(tools.stash_search(["a", "b"], [], []), '"a" "b"')
        self.assertEqual(tools.stash_search([], ["a", "b"], []), '"a|b"')
        self.assertEqual(tools.stash_search([], [], ["a", "b"]), '"!a|b"')
        self.assertEqual(tools.stash_search(["x"], ["a", "b"], ["c"]), '"x" "a|b" "!c"')
        self.assertEqual(tools.stash_search([], [], []), "")

    def test_saved_lines_do_not_repeat(self):
        self.assertEqual(tools.add_stash_line(["a", "b"], "b"), ["b", "a"])

class NoTradesTests(unittest.TestCase):
    @staticmethod
    def overview(*names):
        return {"core": {"primary": "divine", "rates": {"exalted": 100, "chaos": 10}, "items": []}, "items": [{"id": name, "name": name, "image": ""} for name in names],
                "lines": [{"id": name, "primaryValue": 2.0, "volumePrimaryValue": 1, "sparkline": {}} for name in names]}

    def test_a_good_that_leaves_the_market_keeps_its_last_price_and_date(self):
        stored = crafter.merge_overview({"league": "L"}, self.overview("A", "B"), "Runes")
        when = stored["updated"]["Runes"]
        stored = crafter.merge_overview(stored, self.overview("A"), "Runes")
        self.assertNotIn("B", stored["prices_in_divine"])
        self.assertEqual(stored["last_seen"], {"B": {"price": 2.0, "date": when}})

    def test_a_good_that_comes_back_forgets_it(self):
        stored = crafter.merge_overview({"league": "L"}, self.overview("A", "B"), "Runes")
        stored = crafter.merge_overview(stored, self.overview("A"), "Runes")
        stored = crafter.merge_overview(stored, self.overview("A", "B"), "Runes")
        self.assertEqual(stored["last_seen"], {})

    def test_the_prices_of_a_past_league_are_not_remembered_in_a_new_one(self):
        stored = crafter.merge_overview({"league": "Old"}, self.overview("A", "B"), "Runes")
        stored = crafter.merge_overview(stored, self.overview("A"), "Runes")
        stored = crafter.apply_league({**stored, "league_checked": crafter.now_text()}, {"economyLeagues": [{"name": "New", "hardcore": False}]})
        self.assertEqual(stored["last_seen"], {})
        stored = crafter.merge_overview(stored, self.overview("C"), "Runes")
        self.assertEqual(stored["last_seen"], {})

    def test_a_good_is_known_in_either_language_with_or_without_a_price(self):
        names = {"hexers rune": "Руна ведьмы", "uncut skill gem (level 5)": "Неогранённый камень умения (уровень 5)"}
        with mock.patch.object(crafter, "currency_keys", names):
            self.assertEqual(crafter.exchange_good_key(CopiedItem("Валюта", ("Руна ведьмы",), 1, None)), "hexers rune")
            self.assertEqual(crafter.exchange_good_key(CopiedItem("Currency", ("Hexer's Rune",), 1, None)), "hexers rune")
            self.assertEqual(crafter.exchange_good_key(CopiedItem("Камень", ("Неогранённый камень умения",), 1, 5)), "uncut skill gem (level 5)")
            self.assertIsNone(crafter.exchange_good_key(CopiedItem("Редкий", ("Гибельная петля", "Рубиновое кольцо"), 1, None)))

    def test_an_odd_memory_of_prices_is_dropped(self):
        stored = crafter.clean_prices({"exalted_per_divine": 100, "last_seen": {"A": {"price": 2.0, "date": "2026-11-04T00:00:00"}, "B": {"price": "x", "date": "2026-11-04T00:00:00"}, "C": {"price": 1.0, "date": "soon"}, "D": 5}})
        self.assertEqual(list(stored["last_seen"]), ["A"])


class TheTradeSiteIsLeftAloneTests(unittest.TestCase):
    """GGG's terms do not allow programs on the trade site's own API: the player's browser goes there, the program never does."""
    PROGRAM = ("crafter.py", "tools.py", "trade_search.py", "price_check.py", "market_demand.py", "shapes.py", "sakura.py", "tray.py")

    def test_no_part_of_the_program_names_the_sites_api(self):
        for name in self.PROGRAM:
            text = (Path(crafter.__file__).parent / name).read_text(encoding="utf-8")
            for word in ("/api/trade", "api.pathofexile.com", "POESESSID"):
                self.assertNotIn(word, text, name)

    def test_the_search_code_cannot_go_online(self):
        text = (Path(crafter.__file__).parent / "trade_search.py").read_text(encoding="utf-8")
        for word in ("urllib.request", "urlopen", "http.client", "socket"):
            self.assertNotIn(word, text)


STAT_COUNT = 1000


class TradeStatsUpdateTests(unittest.TestCase):
    LINE = '{"matchers": [{"string": "# Life"}], "trade": {"ids": {"explicit": ["explicit.stat_1"]}}}'

    def folder(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.object(crafter, "TRADE_STATS_PATH", Path(folder.name) / "stats.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = mock.patch.object(crafter.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def many(self):
        words = [f"{first}{second}{third}" for first in "abcdefghij" for second in "abcdefghij" for third in "abcdefghij"]
        return "\n".join('{"matchers": [{"string": "# Stat %s"}], "trade": {"ids": {"explicit": ["explicit.stat_%s"]}}}' % (word, word) for word in words[:STAT_COUNT])

    def test_both_languages_come_from_the_open_list_and_never_from_the_trade_site(self):
        self.folder()
        changed = mock.Mock()
        with mock.patch.object(crafter, "fetch", return_value=self.many()) as fetch:
            crafter.update_trade_stats({}, None, changed)
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(all(call.args[0].startswith("https://raw.githubusercontent.com/") for call in fetch.call_args_list))
        stored = crafter.read_json(crafter.TRADE_STATS_PATH)
        self.assertEqual(set(stored), {"en", "ru"})
        changed.assert_called_once()

    def test_a_fresh_list_is_not_asked_for_again(self):
        self.folder()
        with mock.patch.object(crafter, "fetch", return_value=self.many()) as fetch:
            crafter.update_trade_stats({}, None, mock.Mock())
            crafter.update_trade_stats({}, None, mock.Mock())
        self.assertEqual(fetch.call_count, 2)

    def test_a_list_taken_from_the_site_by_an_older_version_is_replaced(self):
        self.folder()
        crafter.write_json(crafter.TRADE_STATS_PATH, {"en": {"fetched_at": crafter.now_text(), "index": {"explicit": {}}}, "ru": {"fetched_at": crafter.now_text(), "index": {"explicit": {}}}})
        with mock.patch.object(crafter, "fetch", return_value=self.many()) as fetch:
            crafter.update_trade_stats({}, None, mock.Mock())
        self.assertEqual(fetch.call_count, 2)

    def test_settings_of_the_old_search_are_dropped(self):
        stored = crafter.clean_settings({"language": "ru", "trade_search": True, "trade_wait": {"search": 1.5}})
        self.assertEqual(stored["language"], "ru")
        self.assertNotIn("trade_search", stored)
        self.assertNotIn("trade_wait", stored)

    def test_a_short_or_broken_list_leaves_the_old_one(self):
        self.folder()
        old = {"en": {"fetched_at": "2020-01-01T00:00:00", "index": {"explicit": {"a": ["b"]}}}}
        crafter.write_json(crafter.TRADE_STATS_PATH, old)
        for reply in (self.LINE, "{broken"):
            with mock.patch.object(crafter, "fetch", return_value=reply), self.assertRaises(ValueError):
                crafter.update_trade_stats({}, None, mock.Mock())
            self.assertEqual(crafter.read_json(crafter.TRADE_STATS_PATH), old)


class LeagueOnAFreshWindowTests(unittest.TestCase):
    def test_changing_league_needs_no_page_to_have_been_opened(self):
        window = object.__new__(crafter.App)
        window.price_window = window.plan = None
        window.stepping_aside = crafter.SteppingAside()
        window._drop_what_used_old_prices()
        self.assertEqual(window.solve_token, 1)


class SteppingAsideTests(unittest.TestCase):
    def aside(self):
        now = [0.0]
        keeper = crafter.SteppingAside(lambda: now[0])
        keeper.start(["window"])
        return keeper, now

    def test_nothing_comes_back_until_the_player_has_left_and_returned(self):
        keeper, _ = self.aside()
        self.assertEqual(keeper.windows_to_bring_back("game", "game"), [])  # the browser has not taken the screen yet
        self.assertEqual(keeper.windows_to_bring_back("browser", "game"), [])
        self.assertEqual(keeper.windows_to_bring_back("browser", "game"), [])
        self.assertEqual(keeper.windows_to_bring_back("game", "game"), ["window"])

    def test_it_comes_back_once(self):
        keeper, _ = self.aside()
        keeper.windows_to_bring_back("browser", "game")
        keeper.windows_to_bring_back("game", "game")
        self.assertEqual(keeper.windows_to_bring_back("game", "game"), [])

    def test_a_browser_that_never_took_the_screen_does_not_leave_them_away(self):
        keeper, now = self.aside()
        now[0] = crafter.BROWSER_LONGEST_WAIT_SECONDS - 1
        self.assertEqual(keeper.windows_to_bring_back("game", "game"), [])
        now[0] = crafter.BROWSER_LONGEST_WAIT_SECONDS + 1
        self.assertEqual(keeper.windows_to_bring_back("game", "game"), ["window"])

    def test_while_the_player_stays_in_the_browser_nothing_comes_back_however_long(self):
        keeper, now = self.aside()
        keeper.windows_to_bring_back("browser", "game")
        now[0] = 9999
        self.assertEqual(keeper.windows_to_bring_back("browser", "game"), [])

    def test_a_new_price_check_ends_the_wait(self):
        keeper, _ = self.aside()
        keeper.windows_to_bring_back("browser", "game")
        keeper.cancel()
        self.assertEqual(keeper.windows_to_bring_back("game", "game"), [])


class UpgradeTokenTests(unittest.TestCase):
    def test_an_upgrade_answer_cannot_cancel_a_plan(self):
        window = object.__new__(crafter.App)
        window.solve_token = 7
        window.upgrade_token = 3
        window.trade_panel = mock.Mock()
        window.prices = {"exalted_per_divine": 100}
        window.on_upgrade(3, "мод", None)
        window.trade_panel.show_note.assert_called_once_with("мод")
        self.assertEqual(window.solve_token, 7)

    def test_a_late_answer_about_another_item_is_dropped(self):
        window = object.__new__(crafter.App)
        window.upgrade_token = 4
        window.trade_panel = mock.Mock()
        window.prices = {"exalted_per_divine": 100}
        window.on_upgrade(3, "мод", 5.0)
        window.trade_panel.show_note.assert_not_called()


class ExchangePricesTests(unittest.TestCase):
    COINS = tools.EXCHANGE_COINS
    STORED = {"league": "HC", "exalted_per_divine": 400, "chaos_per_divine": 10, "prices_in_divine": {"Priced": 2.0}, "kinds": {"Priced": "Runes"}}

    def market(self, thing, coin, things, coins, league="HC"):
        return {"league": league, "market_pair": [thing, coin], "volume_traded": {thing: things, coin: coins}}

    def test_a_good_with_no_price_gets_one_by_the_busiest_coin(self):
        markets = [self.market("path/a", self.COINS["Exalted Orb"], 2, 800), self.market("path/a", self.COINS["Divine Orb"], 1, 0.5)]
        result = crafter.exchange_lines_to_prices(self.STORED, markets, {"path/a": "New Rune"})
        self.assertEqual(result["prices_in_divine"]["New Rune"], 1.0)  # 400 Exalted each, by far the most traded
        self.assertEqual(result["kinds"]["New Rune"], crafter.EXCHANGE_KIND)

    def test_a_price_from_the_sites_stays(self):
        markets = [self.market("path/p", self.COINS["Exalted Orb"], 1, 100)]
        result = crafter.exchange_lines_to_prices(self.STORED, markets, {"path/p": "Priced"})
        self.assertEqual(result["prices_in_divine"]["Priced"], 2.0)
        self.assertEqual(result["kinds"]["Priced"], "Runes")

    def test_another_league_is_left_out(self):
        markets = [self.market("path/a", self.COINS["Exalted Orb"], 1, 100, "Other")]
        self.assertNotIn("New Rune", crafter.exchange_lines_to_prices(self.STORED, markets, {"path/a": "New Rune"})["prices_in_divine"])

    def test_what_stopped_trading_loses_its_price(self):
        stored = {**self.STORED, "prices_in_divine": {**self.STORED["prices_in_divine"], "Old": 1.0}, "kinds": {**self.STORED["kinds"], "Old": crafter.EXCHANGE_KIND}}
        result = crafter.exchange_lines_to_prices(stored, [], {})
        self.assertNotIn("Old", result["prices_in_divine"])
        self.assertEqual(result["prices_in_divine"]["Priced"], 2.0)

    def test_it_goes_under_other_goods(self):
        self.assertEqual(crafter.price_section("X", {"kinds": {"X": crafter.EXCHANGE_KIND}}), crafter.OTHER_SECTION)

    def test_the_main_league_does_not_ask_for_the_file(self):
        stored = {"league": "Rites", "leagues": [{"name": "Rites", "hardcore": False}]}
        with mock.patch.object(crafter, "fetch_exchange") as fetch:
            self.assertEqual(crafter.update_exchange_prices(stored, mock.Mock(), 0), stored)
        fetch.assert_not_called()

    def test_notes_that_are_not_text_go(self):
        self.assertNotIn("notes", crafter.clean_tools({"notes": 5}))
        self.assertEqual(crafter.clean_tools({"notes": "x"})["notes"], "x")

    def test_a_calculation(self):
        self.assertEqual(tools.convert_amount(3, 1.0, 0.25), 12.0)


class TrayNoticeTests(unittest.TestCase):
    def tray(self, added=True):
        icon = TrayIcon("tip", None, None)
        icon.icon, icon.added, icon.shell32 = None, added, mock.Mock()
        return icon

    def test_a_notice_says_its_words_and_fits_the_fields(self):
        icon = self.tray()
        icon.notify("T" * 200, "x" * 900)
        kind, data = icon.shell32.Shell_NotifyIconW.call_args.args
        self.assertEqual((kind, data._obj.uFlags), (NIM_MODIFY, NIF_INFO))
        self.assertEqual((len(data._obj.szInfoTitle), len(data._obj.szInfo)), (63, 255))

    def test_a_notice_before_the_icon_is_up_waits_for_it(self):
        icon = self.tray(added=False)
        icon.notify("Title", "Words")
        icon.shell32.Shell_NotifyIconW.assert_not_called()
        icon.shell32.Shell_NotifyIconW.return_value = 1
        icon._add_icon()
        self.assertEqual(icon.shell32.Shell_NotifyIconW.call_count, 2)
        self.assertEqual(icon.shell32.Shell_NotifyIconW.call_args.args[1]._obj.szInfo, "Words")
        self.assertIsNone(icon.notice)


class WatchTests(unittest.TestCase):
    PRICES = {"exalted_per_divine": 100, "chaos_per_divine": 10}

    def watch(self, direction="below", amount=50.0, unit="Exalted Orb", fired=False):
        return {"name": "A", "direction": direction, "amount": amount, "unit": unit, "fired": fired}

    def run_it(self, watch, divine):
        return tools_watches_reached([watch], lambda _: divine, self.PRICES)

    def test_below_and_above(self):
        self.assertEqual(len(self.run_it(self.watch(), 0.4)[0]), 1)
        self.assertEqual(len(self.run_it(self.watch(), 0.6)[0]), 0)
        self.assertEqual(len(self.run_it(self.watch("above"), 0.6)[0]), 1)
        self.assertEqual(len(self.run_it(self.watch("above"), 0.4)[0]), 0)

    def test_it_speaks_once_and_is_ready_again_after_moving_back(self):
        reached, kept = self.run_it(self.watch(), 0.4)
        self.assertEqual(len(reached), 1)
        reached, kept = self.run_it(kept[0], 0.4)
        self.assertEqual(reached, [])
        reached, kept = self.run_it(kept[0], 0.6)
        self.assertFalse(kept[0]["fired"])
        reached, _ = self.run_it(kept[0], 0.4)
        self.assertEqual(len(reached), 1)

    def test_limits_in_other_currencies(self):
        self.assertEqual(len(self.run_it(self.watch("below", 1, "Divine Orb"), 0.9)[0]), 1)
        self.assertEqual(len(self.run_it(self.watch("below", 1, "Divine Orb"), 1.1)[0]), 0)
        self.assertEqual(len(self.run_it(self.watch("below", 20, "Chaos Orb"), 1.5)[0]), 1)  # 200 Exalted against 150

    def test_no_price_or_rate_says_nothing_and_loses_nothing(self):
        watch = self.watch()
        self.assertEqual(self.run_it(watch, None), ([], [watch]))
        self.assertEqual(tools_watches_reached([watch], lambda _: 1, {}), ([], [watch]))

    def test_the_same_item_the_same_way_has_one_limit(self):
        watches = tools_add_watch([], "A", "below", 5, "Exalted Orb")
        watches = tools_add_watch(watches, "A", "above", 9, "Exalted Orb")
        watches = tools_add_watch(watches, "A", "below", 3, "Divine Orb")
        self.assertEqual([(watch["direction"], watch["amount"]) for watch in watches], [("below", 3), ("above", 9)])


class HistoryTests(unittest.TestCase):
    def test_the_newest_first_and_no_repeats(self):
        history = tools_add_history([], "A", "text a", "1 Divine", "A", "d1")
        history = tools_add_history(history, "B", "text b", "", None, "d2")
        history = tools_add_history(history, "A", "text a", "2 Divine", "A", "d3")
        self.assertEqual([(entry["name"], entry["price"]) for entry in history], [("A", "2 Divine"), ("B", "")])

    def test_it_keeps_a_limited_number(self):
        history = []
        for number in range(120):
            history = tools_add_history(history, str(number), f"text {number}", "", None, "d")
        self.assertEqual(len(history), 50)
        self.assertEqual(history[0]["name"], "119")

    def test_odd_clipboard_contents_stay_small(self):
        self.assertLessEqual(len(tools_add_history([], "A", "x" * 100000, "", None, "d")[0]["copied"]), 6000)


class BadRepliesTests(unittest.TestCase):
    ITEM = {"id": "a", "name": "Chaos Orb", "image": "/gen/image/x/y/z.png"}
    STORED = {"league": "L", "prices_in_divine": {"Chaos Orb": 0.1}, "exalted_per_divine": 600, "chaos_per_divine": 9}

    def overview(self, rates=None, line=None, item=None):
        return {"core": {"primary": "divine", "rates": {"exalted": 600, "chaos": 9} if rates is None else rates, "items": [item or self.ITEM]}, "lines": [{"id": "a", "primaryValue": 0.2, **(line or {})}], "items": []}

    def test_a_good_reply_goes_in(self):
        result = crafter.merge_overview(self.STORED, self.overview(), "Currency")
        self.assertEqual((result["prices_in_divine"]["Chaos Orb"], result["exalted_per_divine"]), (0.2, 600))

    def test_an_odd_rate_never_reaches_the_file(self):
        for rate in (0, -1, None, "много", True, float("inf"), float("nan")):
            with self.assertRaises(ValueError, msg=rate):
                crafter.merge_overview(self.STORED, self.overview({"exalted": rate}), "Currency")

    def test_an_odd_price_never_reaches_the_file(self):
        for price in (0, -5, None, "дорого", True, float("nan")):
            with self.assertRaises(ValueError, msg=price):
                crafter.merge_overview(self.STORED, self.overview(line={"primaryValue": price}), "Currency")

    def test_what_has_left_the_market_goes_and_other_sections_stay(self):
        stored = {**self.STORED, "prices_in_divine": {"Chaos Orb": 0.1, "Old Good": 5, "Other Rune": 1, "Unmarked": 2}, "kinds": {"Chaos Orb": "Currency", "Old Good": "Currency", "Other Rune": "Runes"},
                  "changes": {"Old Good": 1}, "sparklines": {"Old Good": [1]}, "volumes": {"Old Good": 1}, "icons": {"Old Good": "a"}}
        result = crafter.merge_overview(stored, self.overview(), "Currency")
        self.assertEqual(result["prices_in_divine"], {"Chaos Orb": 0.2, "Other Rune": 1, "Unmarked": 2})
        for key in ("kinds", "changes", "sparklines", "volumes", "icons"):
            self.assertNotIn("Old Good", result[key])

    def test_one_odd_line_leaves_the_others(self):
        reply = self.overview()
        reply["core"]["items"].append({"id": "b", "name": "Bad Orb"})
        reply["lines"].append({"id": "b", "primaryValue": "x"})
        self.assertNotIn("Bad Orb", crafter.merge_overview(self.STORED, reply, "Currency")["prices_in_divine"])

    def test_an_odd_graph_becomes_an_empty_one(self):
        result = crafter.merge_overview(self.STORED, self.overview(line={"sparkline": {"totalChange": "x", "data": "y"}}), "Currency")
        self.assertIsNone(result["changes"]["Chaos Orb"])
        self.assertEqual(result["sparklines"]["Chaos Orb"], [])

    def test_a_missing_chaos_rate_keeps_the_saved_one(self):
        self.assertEqual(crafter.merge_overview(self.STORED, self.overview({"exalted": 600, "chaos": 0}), "Currency")["chaos_per_divine"], 9)

    def test_formatting_survives_odd_numbers(self):
        self.assertEqual(crafter.format_age(float("inf")), "—")
        self.assertEqual(crafter.format_amount(float("nan"), "Chaos Orb"), "—")
        self.assertIn("Exalted", crafter.format_cost(5, 0))
        self.assertEqual(tools_format_time(float("nan")), "00:00")

    def test_a_broken_reply_is_a_lost_connection(self):
        import http.client
        with mock.patch.object(crafter.urllib.request, "urlopen", side_effect=http.client.IncompleteRead(b"x")), mock.patch.object(crafter.time, "sleep"):
            with self.assertRaises(ConnectionError):
                crafter.fetch_bytes("https://x", attempts=2)

    def test_any_settings_file_gives_a_theme(self):
        import sakura
        for name in (None, 5, [], {}, "нет такой", True):
            self.assertEqual(sakura.theme_named(name), sakura.DEFAULT_THEME)
        self.assertEqual(sakura.theme_named("washi"), "washi")


class BadScoutRepliesTests(unittest.TestCase):
    STORED = {"league": "L", "source": None, "items": {"Old": {"kind": "weapon", "price": 1}}, "updated": {}, "etags": {}}

    def setUp(self):
        import market_demand
        self.md = market_demand
        self.stored = {**self.STORED, "source": market_demand.SOURCE}

    def update(self, *replies):
        answers = iter(replies)

        def opener(*_, **__):
            reply = mock.MagicMock()
            reply.__enter__.return_value.read.return_value = json.dumps(next(answers)).encode()
            reply.__enter__.return_value.headers.get.return_value = None
            return reply

        return self.md.update_demand(self.stored, "L", 600.0, lambda _: None, lambda: None, ("weapon",), opener=opener, sleep=lambda _: None)

    def test_a_reply_without_items_changes_nothing(self):
        for reply in ({}, {"Items": "x"}, {"Items": None}):
            with self.assertRaises(ValueError):
                self.update(reply)

    def test_a_reply_that_is_not_an_object_is_refused(self):
        for reply in ([], 5, None):
            with self.assertRaises(ValueError):
                self.update(reply)

    def test_nothing_usable_keeps_the_saved_items(self):
        self.assertIn("Old", self.update({"Items": []})["items"])
        self.assertIn("Old", self.update({"Items": [5, None, {"Name": "A", "CurrentPrice": "x"}, {"Name": "A", "CurrentPrice": -1}]})["items"])

    def test_one_odd_line_leaves_the_others(self):
        items = self.update({"Items": [5, {"Name": "Good", "CurrentPrice": 600}]})["items"]
        self.assertEqual(list(items), ["Good"])
        self.assertEqual(items["Good"]["price"], 1)

    def test_a_reply_naming_endless_pages_is_cut_short(self):
        replies = [{"Items": [{"Name": "Good", "CurrentPrice": 600}], "Pages": 10 ** 9}, *({"Items": []} for _ in range(self.md.MOST_PAGES))]
        self.update(*replies)  # one more page than these answers would raise StopIteration


class PatchWatchTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for name, value in (("PATCH_WATCH_PATH", "watch.json"), ("DATA_PATH", "data.json"), ("LOG_PATH", "errors.log")):
            patcher = mock.patch.object(crafter, name, self.folder / value)
            patcher.start()
            self.addCleanup(patcher.stop)
        crafter.write_json(crafter.DATA_PATH, {"poe2db_patch": "0.5.5e", "game_version": "0.5.5.5"})
        self.fired = []
        self.now = crafter.datetime(2026, 12, 11, 20, 0, 0)

    def watch(self):
        return crafter.PatchWatch(lambda: self.fired.append(1), clock=lambda: self.now)

    def test_the_first_build_ever_seen_is_no_patch(self):
        watch = self.watch()
        watch.see(100)
        self.assertEqual(self.fired, [])
        self.assertFalse(watch.rushing())

    def test_a_newer_build_fires_once_and_wakes_the_updates(self):
        watch = self.watch()
        watch.see(100)
        watch.see(101)
        watch.see(101)
        self.assertEqual(self.fired, [1])
        self.assertTrue(watch.rushing())
        self.assertTrue(watch.wake.is_set())

    def test_an_older_number_from_a_slow_source_is_nothing(self):
        watch = self.watch()
        watch.see(101)
        watch.see(100)
        self.assertEqual(self.fired, [])
        self.assertEqual(watch.build, 101)

    def test_a_patch_that_came_while_closed_counts(self):
        self.watch().see(100)
        watch = self.watch()
        watch.see(105)
        self.assertEqual(self.fired, [1])

    def test_a_rush_lives_through_a_restart(self):
        watch = self.watch()
        watch.see(100)
        watch.see(101)
        self.assertTrue(self.watch().rushing())

    def test_nothing_read_is_nothing_seen(self):
        watch = self.watch()
        watch.see(None)
        self.assertIsNone(watch.build)

    def rushing_watch(self):
        watch = self.watch()
        watch.see(100)
        watch.see(101)
        return watch

    def test_asks_often_at_first_then_less_often(self):
        watch = self.rushing_watch()
        checked = lambda minutes: {"checked_at": (self.now - crafter.timedelta(minutes=minutes)).isoformat()}
        self.assertFalse(watch.check_is_due(checked(1)))
        self.assertTrue(watch.check_is_due(checked(2)))
        self.now += crafter.timedelta(hours=2)
        self.assertFalse(watch.check_is_due(checked(9)))
        self.assertTrue(watch.check_is_due(checked(10)))

    def test_without_a_rush_there_is_no_hurry(self):
        watch = self.watch()
        self.assertFalse(watch.check_is_due({}))

    def test_one_site_moving_keeps_the_rush_going_and_both_end_it(self):
        watch = self.rushing_watch()
        watch.review({"poe2db_patch": "0.5.6", "game_version": "0.5.5.5"})
        self.assertTrue(watch.rushing())
        watch.review({"poe2db_patch": "0.5.6", "game_version": "0.5.6.0"})
        self.assertFalse(watch.rushing())

    def test_a_hotfix_that_changes_neither_site_ends_by_time(self):
        watch = self.rushing_watch()
        watch.review({"poe2db_patch": "0.5.5e", "game_version": "0.5.5.5"})
        self.assertTrue(watch.rushing())
        self.now += crafter.RUSH_LONGEST + crafter.timedelta(minutes=1)
        watch.review({"poe2db_patch": "0.5.5e", "game_version": "0.5.5.5"})
        self.assertFalse(watch.rushing())

    def test_the_build_is_read_from_the_steam_record(self):
        self.assertEqual(crafter.read_manifest_build('"AppState"\n{\n\t"appid"\t"2694490"\n\t"buildid"\t\t"26261440"\n}'), 26261440)
        self.assertIsNone(crafter.read_manifest_build("nothing"))

    def test_the_build_is_read_from_the_online_reply(self):
        reply = json.dumps({"data": {crafter.STEAM_APP_ID: {"depots": {"branches": {"public": {"buildid": "26261440"}}}}}})
        self.assertEqual(crafter.read_online_build(reply), 26261440)
        self.assertIsNone(crafter.read_online_build("<html>"))
        self.assertIsNone(crafter.read_online_build("{}"))

    def test_a_change_of_the_steam_record_is_noticed_within_a_second(self):
        import threading
        import time as real_time
        path = self.folder / "appmanifest.acf"
        path.write_text('"buildid" "100"', encoding="utf-8")
        watch = self.watch()
        worker = threading.Thread(target=crafter.run_local_build_watch, args=(watch, lambda: path), daemon=True)
        worker.start()
        deadline = real_time.time() + 3
        while watch.build != 100 and real_time.time() < deadline:
            real_time.sleep(0.01)
        self.assertEqual(watch.build, 100)
        real_time.sleep(0.05)  # some disks keep file times coarse
        path.write_text('"buildid" "101"', encoding="utf-8")
        begin = real_time.time()
        while not self.fired and real_time.time() < begin + 3:
            real_time.sleep(0.01)
        self.assertEqual(self.fired, [1])
        self.assertLess(real_time.time() - begin, 1.5)


class ScreenTests(unittest.TestCase):
    ONE = (0, 0, 1920, 1080)

    def test_a_place_on_screen_stays(self):
        self.assertEqual(crafter.place_on_screen("+745+38", self.ONE), "+745+38")

    def test_a_place_on_a_monitor_now_gone_is_dropped(self):
        self.assertIsNone(crafter.place_on_screen("+2500+38", self.ONE))
        self.assertIsNone(crafter.place_on_screen("+-1500+38", self.ONE))

    def test_a_monitor_on_the_left_counts(self):
        self.assertEqual(crafter.place_on_screen("+-1500+38", (-1920, 0, 3840, 1080)), "+-1500+38")

    def test_nothing_saved_is_nothing(self):
        self.assertIsNone(crafter.place_on_screen(None, self.ONE))

    def test_nonsense_is_nothing(self):
        self.assertIsNone(crafter.place_on_screen("1x1;bad", self.ONE))


class FileHeldTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "a.json"
        self.path.write_text('{"a": 1}', encoding="utf-8")
        patcher = mock.patch.object(crafter, "LOG_PATH", Path(folder.name) / "errors.log")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(crafter.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_file_held_for_a_moment_is_still_read(self):
        real = Path.read_text
        calls = []

        def busy_once(path, **options):
            calls.append(1)
            if len(calls) == 1:
                raise PermissionError("held")
            return real(path, **options)

        with mock.patch.object(Path, "read_text", busy_once):
            self.assertEqual(crafter.read_json(self.path), {"a": 1})

    def test_a_file_held_for_good_is_not_called_damaged(self):
        with mock.patch.object(Path, "read_text", side_effect=PermissionError("held")):
            self.assertIsNone(crafter.read_json(self.path))
        self.assertTrue(self.path.exists())
        self.assertFalse(self.path.with_name("a.json.broken").exists())


class FakeLabel:
    def __init__(self):
        self.text, self.drawn, self.alive = "", 0, True

    def cget(self, _):
        return self.text

    def config(self, text):
        self.text, self.drawn = text, self.drawn + 1

    def winfo_exists(self):
        return self.alive


class FakeWindow:
    def __init__(self):
        self.jobs = []

    def winfo_toplevel(self):
        return self

    def after(self, _, action, *args):
        self.jobs.append(lambda: action(*args))
        return len(self.jobs)

    def after_idle(self, action, *args):
        return self.after(0, action, *args)

    def after_cancel(self, _):
        pass

    def winfo_exists(self):
        return True

    def winfo_ismapped(self):
        return False  # what Tk answers right after a tab opens, and while the window is hidden


class DrawingInTurnsTests(unittest.TestCase):
    def make_page(self, rows: int):
        import market_demand
        page = market_demand.DemandPage.__new__(market_demand.DemandPage)
        page.rows = list(range(rows))
        page.draw_job = None
        page.canvas = FakeWindow()
        page.drawn = []
        page._draw_row = lambda number, *_: page.drawn.append(number)
        return page

    def turn(self, page, first: int, row_seconds: float) -> None:
        import market_demand
        clock = iter(index * row_seconds for index in range(10000))
        with mock.patch.object(market_demand.time, "perf_counter", lambda: next(clock)):
            page._draw_rows_from(first, 800, {})

    def test_the_first_turn_fills_the_screen_even_when_rows_are_slow(self):
        import market_demand
        page = self.make_page(100)
        self.turn(page, 0, 1.0)
        self.assertEqual(len(page.drawn), market_demand.DRAWN_AT_ONCE)
        self.assertEqual(len(page.canvas.jobs), 1)

    def test_later_turns_stop_on_time_so_the_window_keeps_answering(self):
        import market_demand
        page = self.make_page(100)
        self.turn(page, market_demand.DRAWN_AT_ONCE, 1.0)
        self.assertEqual(len(page.drawn), 1)

    def test_a_short_list_is_drawn_at_once_with_nothing_left_waiting(self):
        page = self.make_page(5)
        self.turn(page, 0, 1.0)
        self.assertEqual(page.drawn, [0, 1, 2, 3, 4])
        self.assertIsNone(page.draw_job)

    def test_a_rebuilt_page_stops_quietly(self):
        page = self.make_page(5)
        page.canvas = mock.Mock()
        page.canvas.winfo_exists.return_value = False
        page.canvas.winfo_toplevel.side_effect = AssertionError("asked a destroyed widget")
        self.turn(page, 0, 1.0)
        self.assertEqual(page.drawn, [])


class StopwatchScreenTests(unittest.TestCase):
    def make_page(self, running: bool):
        import tools
        page = tools.ToolsPage.__new__(tools.ToolsPage)
        page.t = str
        page.now = 100.0
        page.stopwatch = Stopwatch(lambda: page.now)
        if running:
            page.stopwatch.toggle()
        page.canvas = FakeWindow()
        page.timer_label = FakeLabel()
        page.timer_toggle = mock.Mock()
        page.tab = "timer"
        return page

    def test_it_keeps_ticking_though_tk_says_it_is_not_on_screen(self):
        page = self.make_page(True)
        page._tick_timer()
        self.assertEqual(len(page.canvas.jobs), 1)
        page.now += 5
        page.canvas.jobs.pop()()
        self.assertEqual(page.timer_label.text, "00:05")
        self.assertEqual(len(page.canvas.jobs), 1)

    def test_it_stops_when_paused(self):
        page = self.make_page(False)
        page._tick_timer()
        self.assertEqual(page.canvas.jobs, [])

    def test_it_stops_with_its_page(self):
        page = self.make_page(True)
        page.timer_label.alive = False
        page._tick_timer()
        self.assertEqual(page.canvas.jobs, [])

    def test_it_stops_quietly_when_the_page_was_rebuilt(self):
        page = self.make_page(True)
        page.canvas = mock.Mock()
        page.canvas.winfo_exists.return_value = False
        page.canvas.winfo_toplevel.side_effect = AssertionError("asked a destroyed widget")
        page._tick_timer()

    def test_a_tick_within_the_same_second_draws_nothing(self):
        page = self.make_page(True)
        page._tick_timer()
        drawn = page.timer_label.drawn
        page.now += 0.25
        page.canvas.jobs.pop()()
        self.assertEqual(page.timer_label.drawn, drawn)


if __name__ == "__main__":
    unittest.main()
