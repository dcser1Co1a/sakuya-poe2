import json
import re
import unittest
import urllib.parse
from pathlib import Path

import crafter
import drop_sources
import shapes
from drop_sources import Drop, build_drops, clean_wiki_text, fetch_drops, read_rows, russian_source, shown_drops, source_kind

# Rows as poe2wiki's Cargo API gave them on 2026-11-08 (the hover card shortened), plus what a changed wiki might send.
HOVER = ('Drops from [[Zarokh, the Eternal]] when completing a run using &lt;span class=&quot;hoverbox c-item-hoverbox&quot;&gt;&lt;span class=&quot;hoverbox__activator c-item-hoverbox__activator&quot;&gt;'
         '[[File:The Remembered Tales inventory icon.png|16x16px|link=|alt=]][[The Remembered Tales|The Remembered Tales]]&lt;/span&gt;&lt;span class=&quot;hoverbox__display c-item-hoverbox__display&quot;&gt;'
         '&lt;span class=&quot;item-box -unique&quot;&gt;&lt;span class=&quot;header -double&quot;&gt;The Remembered Tales&lt;br&gt;Coffer Relic&lt;/span&gt;&lt;span class=&quot;item-stats&quot;&gt;Cannot have Boons&lt;/span&gt;&lt;/span&gt;'
         '[[File:The Remembered Tales inventory icon.png|156x156px|link=|alt=|class=item-icon]]&lt;/span&gt;&lt;/span&gt;.')


def row(name, base="", text=None, restricted="0", enabled="1", level="1", kind="Ring"):
    return {"title": {"name": name, "base item": base, "class id": kind, "rarity id": "unique", "drop text": text, "is drop restricted": restricted, "drop enabled": enabled, "drop level": level}}


ROWS = [row("Voices", "Sapphire", "Drops in the [[Simulacrum]].", "1", kind="Jewel"),
        row("Assailum", "Closed Helm", "Drops in the [[Simulacrum (encounter)|Simulacrum]].", "1"),
        row("Blessed Bonds", "Linen Wraps", HOVER, "1"),
        row("Ab Aeterno", "Grand Cuisses", "Drops from [[The Arbiter of Ash]].", "1"),
        row("Beetlebite", "Velour Shoes", "Drops from [[The King in the Mists]] at the [[Crux of Nothingness]].", "1"),
        row("Atziri&#039;s Rule", "Reflecting Staff", "Can drop from Atziri&#039;s Vault in [[Atziri&#039;s Temple]] after defeating [[Atziri, the Red Queen]].", "1"),
        row("Grand Spectrum", "Sapphire", "Obtained from a &quot;Gold Spectrum Cache&quot; chest in the [[Trial of the Sekhemas]].", "1", kind="Jewel"),
        row("Demigod&#039;s Virtue", "Golden Visage", "Can only be obtained as an exclusive race reward for top placements in certain [[event]]s.", "1"),
        row("Polcirkeln", "Sapphire Ring", None, "0", level="47"),
        row("Old Thing", "Ring", None, "1", enabled="0"),
        row("Time-Lost Ruby", "", "Drops in the [[Trial of the Sekhemas]] from a &quot;Time-Lost Cache&quot;.", "1", kind="Jewel"),
        row("Diamond", "", "Can be created by reforging a [[Ruby]], [[Emerald]] and [[Sapphire]] in the [[Reforging Bench]].", "1", kind="Jewel"),
        row("Voices", "Sapphire", None, "1", kind="Jewel"),  # a variant without the text: the one with it stays
        {"title": {"name": None}}, {"title": "odd"}, 5]


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.drops = build_drops(read_rows({"cargoquery": ROWS}))

    def test_wiki_text_is_cleaned_of_links_cards_and_entities(self):
        self.assertEqual(clean_wiki_text(HOVER), "Drops from Zarokh, the Eternal when completing a run using The Remembered Tales.")
        self.assertEqual(self.drops["Atziri's Rule"]["source"], "Can drop from Atziri's Vault in Atziri's Temple after defeating Atziri, the Red Queen.")
        self.assertEqual(clean_wiki_text(None), "")

    def test_every_kind_of_source(self):
        kinds = {name: entry["kind"] for name, entry in self.drops.items()}
        self.assertEqual(kinds, {"Voices": "simulacrum", "Assailum": "simulacrum", "Blessed Bonds": "boss", "Ab Aeterno": "boss", "Beetlebite": "boss", "Atziri's Rule": "vault",
                                 "Grand Spectrum": "trial", "Demigod's Virtue": "event", "Polcirkeln": "world", "Old Thing": "legacy", "Time-Lost Ruby": "trial", "Diamond": "craft"})
        self.assertEqual(self.drops["Voices"]["source"], "Drops in the Simulacrum.")
        self.assertTrue(self.drops["Voices"]["jewel"])
        self.assertEqual(self.drops["Polcirkeln"]["level"], 47)

    def test_russian_wordings_keep_names_and_fall_back_to_the_wiki(self):
        shown = {name: russian_source(Drop(name, entry["base"], entry["kind"], entry["source"], entry["level"], entry["jewel"])) for name, entry in self.drops.items()}
        self.assertEqual(shown["Voices"], "Падает в Симулякре")
        self.assertEqual(shown["Ab Aeterno"], "Падает с босса The Arbiter of Ash")
        self.assertEqual(shown["Beetlebite"], "Падает с босса The King in the Mists (Crux of Nothingness)")
        self.assertEqual(shown["Grand Spectrum"], "Сундук «Gold Spectrum Cache» в Испытании сехем")
        self.assertEqual(shown["Time-Lost Ruby"], "Сундук «Time-Lost Cache» в Испытании сехем")
        self.assertEqual(shown["Polcirkeln"], "Падает где угодно, с уровня зоны 47")
        self.assertEqual(shown["Old Thing"], "Больше не выпадает")
        self.assertEqual(shown["Blessed Bonds"], "Падает с босса Zarokh, the Eternal, если пройти забег с реликвией The Remembered Tales")
        self.assertEqual(shown["Diamond"], "Создаётся на Столе перековки из: Ruby, Emerald and Sapphire")
        odd = Drop("X", "Ring", "boss", "Drops from Someone while it rains.", 1, False)
        self.assertEqual(russian_source(odd), "Drops from Someone while it rains.")  # anything unusual: as the wiki writes it

    def test_the_list_puts_rare_places_first_and_searches_both_names(self):
        drops = drop_sources.drops_of({"items": self.drops})
        show = lambda name: {"Voices": "Голоса"}.get(name, name)
        matches = lambda query, text: query.casefold() in text.casefold()
        special = [drop.name for drop in shown_drops(drops, "special", "", show, matches)]
        self.assertEqual(special[:2], ["Assailum", "Voices"] if show("Assailum") < show("Voices") else ["Voices", "Assailum"])
        self.assertNotIn("Polcirkeln", special)
        self.assertEqual([drop.name for drop in shown_drops(drops, "all", "голос", show, matches)], ["Voices"])
        self.assertEqual([drop.name for drop in shown_drops(drops, "world", "", show, matches)], ["Polcirkeln"])

    def test_a_line_for_the_build_page(self):
        stored = {"items": self.drops}
        self.assertEqual(drop_sources.drop_line(stored, "Voices", "ru"), "Падает в Симулякре")
        self.assertEqual(drop_sources.drop_line(stored, "Voices", "en"), "Drops in the Simulacrum.")
        self.assertIsNone(drop_sources.drop_line(stored, "Nobody", "ru"))


class FetchTests(unittest.TestCase):
    def test_both_queries_every_page_and_a_thin_reply_is_refused(self):
        urls = []
        many = [row(f"U{index}", "Ring") for index in range(drop_sources.ROWS_PER_PAGE)]

        def fetch(url):
            urls.append(url)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if query.get("action") == ["query"]:
                return json.dumps({"query": {"pages": {"1": {"title": "Simulacrum", "revisions": [{"slots": {"main": {"*": SIMULACRUM}}}]}, "2": {"missing": ""}}}})
            if "unique" in query["where"][0] and "<>" not in query["where"][0]:
                return json.dumps({"cargoquery": many if query["offset"] == ["0"] else ROWS[:3]})
            return json.dumps({"cargoquery": ROWS[10:12]})

        drops = fetch_drops(fetch)
        self.assertEqual(len(urls), 4)  # both lists, the second page of uniques, and the pages of the places in one request
        self.assertIn("titles=", urls[3])
        self.assertTrue(all(url.startswith("https://www.poe2wiki.net/w/api.php?action=cargoquery") for url in urls[:3]))
        self.assertIn("Time-Lost Ruby", drops)
        self.assertEqual(drops["Voices"]["chance"], [["", "~1%?"]])
        self.assertEqual(drops["Voices"]["page"], "Simulacrum")
        with self.assertRaises(ValueError):
            fetch_drops(lambda url: json.dumps({"cargoquery": ROWS[:3]}))
        with self.assertRaises(ValueError):
            fetch_drops(lambda url: json.dumps({"error": "x"}))


# Pieces of the wiki's boss and encounter pages as they were on 2026-11-08.
SIMULACRUM = """{{Mbox|text= Estimated drop rates from [[version 0.5.0]]. n=59<ref>x</ref>Actual drop rates may vary. }}
{| class="wikitable" 
! !! Reward !! Drop rate
|-
|  rowspan="9" | '''Guaranteed<br>Unique'''
|
* {{il|Assailum}}
| 42%
|-
|
* {{il|Megalomaniac}} (2 mod)
| 3%
|-
|
* {{il|Voices}}
| ~1%?
|-
|
* [[Liquid emotion]]s
|}"""
ARBITER = """{{Mbox|text= Estimated drop rates from [[version 0.3.0]]<ref name="Prohib" />}}
{| class="wikitable" 
|-
! colspan="2" |
! Regular
! Uber
|-
| Sample size || || 235 || 100
|-
|
* {{il|Morior Invictus}}
| 48%
| 41%
|-
|
* {{il|Solus Ipse}}
| ?%
| 23%
|-
|
* {{il|Prism of Belief}}
| {{Tooltip | 23% | dropped by the quest Arbiter}}
| 15%
|}"""
ATZIRI = """{{Mbox|text= Estimated drop rates from [[version 0.4.0]]. n=100<ref>x</ref> Actual drop rates may vary.
}}
* {{il|Atziri's Step}} (35%)
* {{il|name=Atziri's Splendour|skip_query=true|link=Atziri's Splendour}} (12%, 7 random variants)
* {{il|Sacrificial Regalia}} has a 5% chance, said later in the sentence
"""
OLD_TABLE = """{| class="wikitable"
|+ Estimated drop table
! Item !! Pre 0.3.0 drop rate
|-
| {{il|The Burden of Leadership}} || 35.5% (31%)
|}"""


class RateTests(unittest.TestCase):
    def test_tables_and_lists_give_rates_with_their_columns_and_sample(self):
        self.assertEqual(drop_sources.read_rates(SIMULACRUM), {"Assailum": {"chance": [["", "42%"]], "sample": "0.5.0, n=59"}, "Megalomaniac": {"chance": [["", "3%"]], "sample": "0.5.0, n=59"},
                                                              "Voices": {"chance": [["", "~1%?"]], "sample": "0.5.0, n=59"}})
        arbiter = drop_sources.read_rates(ARBITER)
        self.assertEqual(arbiter["Morior Invictus"]["chance"], [["Regular", "48%"], ["Uber", "41%"]])
        self.assertEqual(arbiter["Solus Ipse"]["chance"], [["Uber", "23%"]])  # an unknown «?%» is left out
        self.assertEqual(arbiter["Prism of Belief"]["chance"], [["Regular", "23%"], ["Uber", "15%"]])
        atziri = drop_sources.read_rates(ATZIRI)
        self.assertEqual({name: rate["chance"] for name, rate in atziri.items()}, {"Atziri's Step": [["", "35%"]], "Atziri's Splendour": [["", "12%"]]})

    def test_the_chance_column_keeps_the_estimate_apart_from_the_source(self):
        voices = Drop("Voices", "Sapphire", "simulacrum", "Drops in the Simulacrum.", 1, True, (("", "~1%?"),), "0.5.0, n=59")
        self.assertEqual(drop_sources.chance_lines(voices, True), ("1 из ~100", "~1%? · 0.5.0"))  # what a player counts: runs, the rate small
        arbiter = Drop("Morior Invictus", "Plate", "boss", "Drops from The Arbiter of Ash.", 1, False, (("Regular", "48%"), ("Uber", "41%")), "0.3.0")
        self.assertEqual(drop_sources.chance_lines(arbiter, True), ("1 из 2", "≈48% обычный · ≈41% убер · 0.3.0"))
        for rate, runs in (("42%", "1 из 2"), ("10%", "1 из ~10"), ("3%", "1 из ~33"), ("0.5%", "1 из ~200"), ("<1%", "реже 1 из 100"), ("100%", "каждый раз"), ("?%", "—")):
            self.assertEqual(drop_sources.attempts_text(rate, True), runs)
        self.assertEqual(drop_sources.attempts_text("~1%?", False), "1 in ~100")
        anywhere = Drop("Polcirkeln", "Sapphire Ring", "world", "", 47, False)
        self.assertEqual(drop_sources.chance_lines(anywhere, True, 120), ("на рынке 120", ""))
        self.assertEqual(drop_sources.chance_lines(anywhere, True), ("—", ""))

    def test_a_page_without_the_estimate_notice_gives_nothing(self):
        self.assertEqual(drop_sources.read_rates(OLD_TABLE), {})  # the wiki's own «pre 0.3.0» figures, with no notice: too old to quote

    def test_how_a_chance_is_written(self):
        self.assertEqual(drop_sources.chance_text([["", "42%"]], True), "≈42%")
        self.assertEqual(drop_sources.chance_text([["", "~1%?"]], True), "~1%?")
        self.assertEqual(drop_sources.chance_text([["Regular", "48%"], ["Uber", "41%"]], True), "≈48% обычный · ≈41% убер")
        self.assertEqual(drop_sources.chance_text([["Difficulty 3", "29.5%"]], True), "≈29.5% (сложность 3)")
        self.assertEqual(drop_sources.chance_text([["Difficulty 3", "29.5%"]], False), "≈29.5% (Difficulty 3)")
        voices = Drop("Voices", "Sapphire", "simulacrum", "Drops in the Simulacrum.", 1, True, (("", "~1%?"),), "0.5.0, n=59")
        self.assertEqual(drop_sources.full_source(voices, True), "Падает в Симулякре  •  1 из ~100 (~1%?, 0.5.0)")
        anywhere = Drop("Polcirkeln", "Sapphire Ring", "world", "", 47, False)
        self.assertEqual(drop_sources.full_source(anywhere, True, 120), "Падает где угодно, с уровня зоны 47  •  на рынке 120")


class FileTests(unittest.TestCase):
    def test_the_saved_file_is_checked_when_read(self):
        stored = {"fetched_at": "2026-11-08T12:00:00", "items": {"Voices": {"base": "Sapphire", "source": "x", "kind": "simulacrum", "level": 1, "jewel": True},
                                                                 "Bad": {"kind": "nonsense"}, "Odd": 5, "": {"kind": "world"}, "Lvl": {"kind": "world", "level": "high", "base": 3}}}
        cleaned = shapes.clean_drops(stored)
        self.assertEqual(set(cleaned["items"]), {"Voices", "Lvl"})
        self.assertEqual(cleaned["items"]["Lvl"], {"base": "", "source": "", "kind": "world", "level": None, "jewel": False, "chance": [], "sample": ""})
        odd = shapes.clean_drops({"items": {"A": {"kind": "boss", "chance": [["Uber", "41%"], ["x"], [1, "2%"], "5%"], "sample": 7}}})
        self.assertEqual((odd["items"]["A"]["chance"], odd["items"]["A"]["sample"]), ([["Uber", "41%"]], ""))
        self.assertEqual(shapes.clean_drops("garbage"), {"items": {}})


class TranslationTests(unittest.TestCase):
    def test_every_caption_has_an_english_version(self):
        source = Path(drop_sources.__file__).read_text(encoding="utf-8")
        captions = set(re.findall(r'\bt\("((?:[^"\\]|\\.)*)"\)', source)) | set(drop_sources.KIND_TITLES.values())
        self.assertGreater(len(captions), 10)
        self.assertEqual(sorted(caption for caption in captions if caption not in crafter.ENGLISH), [])


if __name__ == "__main__":
    unittest.main()
