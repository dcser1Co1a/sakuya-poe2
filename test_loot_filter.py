"""Tests of the filter builder TEST (loot_filter.py). Remove together with it."""
import ast
import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import crafter
import loot_filter

PRICES = {"Mirror of Kalandra": 6426.0, "Divine Orb": 1.0, "Perfect Chaos Orb": 0.012, "Greater Essence of Haste": 0.15, "Orb of Augmentation": 0.0004,
          "Uncut Skill Gem (Level 20)": 0.4, 'Odd "Name"': 3.0, "Gone": 0}
NOW = datetime(2026, 11, 9, 12, 0)
RATE = 600.0  # exalted per divine


def settings(**changes):
    return {**copy.deepcopy(loot_filter.clean_settings({})), **changes}


class FilterTests(unittest.TestCase):
    def test_lines_by_worth_and_the_usual_filter_below(self):
        text = loot_filter.filter_text(PRICES, "Forbidden Rites", settings(base="UnstoppableEndgame055.filter"), RATE, NOW)
        self.assertIn('BaseType == "Mirror of Kalandra" "Divine Orb"', text)  # from 1 div, the dearest first
        self.assertIn('BaseType == "Greater Essence of Haste"', text)  # from 60 ex = 0.1 div
        self.assertNotIn("Perfect Chaos Orb", text)  # 7 ex: below the last line's 12 ex
        self.assertNotIn("Uncut Skill Gem", text)  # a level in brackets is many items under one base
        self.assertNotIn("Odd", text)
        self.assertTrue(text.rstrip().endswith('Import "UnstoppableEndgame055.filter" Optional'))
        self.assertIn("PlayEffect Red\n", text)
        self.assertIn("MinimapIcon 0 Red Star", text)
        self.assertIn("PlayAlertSound 6 300", text)
        self.assertNotIn("Hide", text)

    def test_own_sounds_beams_icons_and_fonts(self):
        own = settings(hide_below=1.0)
        own["tiers"][2].update(least=5.0, color="cyan", font=30, beam={"color": "Purple", "temp": True}, icon={"size": 2, "color": "Green", "shape": "Moon"},
                               sound={"kind": "custom", "file": "coin.mp3", "volume": 120})
        text = loot_filter.filter_text(PRICES, "Standard", own, RATE, NOW)
        block = text[text.index("Perfect Chaos Orb"):]
        self.assertIn("SetFontSize 30", block)
        self.assertIn("PlayEffect Purple Temp", block)
        self.assertIn("MinimapIcon 2 Green Moon", block)
        self.assertIn('CustomAlertSound "Sakuya sounds/coin.mp3" 120', block)
        self.assertIn('Hide\n    BaseType == "Orb of Augmentation"', text)
        hidden = loot_filter.tiered({"Exalted Orb": 1 / RATE, "Chaos Orb": 0.5 / RATE, "Orb of Augmentation": 0.0004}, settings(hide_below=2.0), RATE)[1]
        self.assertEqual(hidden, ["Orb of Augmentation"])  # the coins prices are counted in are never hidden

    def test_the_dearest_line_wins_whatever_their_order(self):
        own = settings()
        own["tiers"].reverse()  # the player may put the cheapest line first
        tiers, _ = loot_filter.tiered(PRICES, own, RATE)
        self.assertEqual(tiers[2], ["Mirror of Kalandra", "Divine Orb"])  # the 1 div line, now third, still takes them
        text = loot_filter.filter_text(PRICES, "Standard", own, RATE, NOW)
        self.assertLess(text.index("Mirror of Kalandra"), text.index("Greater Essence of Haste"))  # its block still comes first in the file

    def test_the_usual_filter_as_a_copy_or_an_import(self):
        usual = 'Show\n    Class == "Currency"\n    SetFontSize 30\n'
        copied = loot_filter.filter_text(PRICES, "Standard", settings(base="Mine.filter"), RATE, NOW, base_text=usual)
        self.assertNotIn("Import", copied)
        self.assertTrue(copied.rstrip().endswith('SetFontSize 30'))  # its own text, below Sakuya's rules: it works whether or not the game knows Import
        self.assertLess(copied.index("Mirror of Kalandra"), copied.index('Class == "Currency"'))
        linked = loot_filter.filter_text(PRICES, "Standard", settings(base="Mine.filter", link="import"), RATE, NOW, base_text=usual)
        self.assertTrue(linked.rstrip().endswith('Import "Mine.filter" Optional'))
        self.assertNotIn('Class == "Currency"', linked)
        unreadable = loot_filter.filter_text(PRICES, "Standard", settings(base="Mine.filter"), RATE, NOW, base_text=None)
        self.assertTrue(unreadable.rstrip().endswith('Import "Mine.filter" Optional'))  # a copy it cannot read falls back to the line
        self.assertEqual(loot_filter.clean_settings({})["link"], "copy")
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "Mine.filter").write_bytes("﻿Show\n".encode("utf-8"))
            self.assertEqual(loot_filter.read_usual_filter(Path(folder), "Mine.filter"), "Show\n")  # without the mark some editors put first
            self.assertIsNone(loot_filter.read_usual_filter(Path(folder), "Gone.filter"))

    def test_kinds_softer_stricter_or_left_alone(self):
        kinds = {"Greater Essence of Haste": "Essences", "Perfect Chaos Orb": "Currency", "Divine Orb": "Currency", "Mirror of Kalandra": "Currency"}
        softer = settings(kinds={"Currency": "softer"})
        tiers, _ = loot_filter.tiered(PRICES, softer, RATE, kinds)
        self.assertIn("Perfect Chaos Orb", tiers[2])  # 7.2 ex counts as 14.4 ex: past the 12 ex line
        stricter = settings(kinds={"Essences": "stricter"})
        tiers, _ = loot_filter.tiered(PRICES, stricter, RATE, kinds)
        self.assertIn("Greater Essence of Haste", tiers[2])  # 90 ex counts as 45 ex: down from the 60 ex line to the 12 ex one
        alone = settings(kinds={"Essences": "skip"})
        self.assertNotIn("Greater Essence of Haste", loot_filter.filter_text(PRICES, "Standard", alone, RATE, NOW, kinds))
        self.assertEqual(loot_filter.clean_settings({"kinds": {"Currency": "same", "Runes": "softer", "Nonsense": "skip"}})["kinds"], {"Runes": "softer"})

    def test_goods_set_by_hand_come_first(self):
        own = settings(items={"Orb of Augmentation": "loud", "Divine Orb": "hide", "Mirror of Kalandra": "normal", "Greater Essence of Haste": "hide"})
        text = loot_filter.filter_text(PRICES, "Standard", own, RATE, NOW)
        self.assertLess(text.index('# Set by hand to be loud: 1 goods\nShow\n    BaseType == "Orb of Augmentation"'), text.index("Hide"))
        self.assertIn('Hide\n    BaseType == "Greater Essence of Haste"', text)
        self.assertNotIn('"Divine Orb"', text)  # a coin is never hidden, and with a rule it is in no line either
        self.assertNotIn("Mirror of Kalandra", text)  # «as the usual filter»: Sakuya leaves it alone
        self.assertEqual(loot_filter.clean_settings({"items": {"A": "loud", 'B"': "hide", "C": "odd"}})["items"], {"A": "loud"})

    def test_a_preset_sets_the_lines_at_once(self):
        own = settings()
        own["tiers"][0]["name"] = "Mine"
        loot_filter.apply_preset(own, "strict", RATE)
        self.assertEqual([(tier["least"], tier["unit"]) for tier in own["tiers"]], [(2.0, "div"), (150.0, "ex"), (40.0, "ex")])
        self.assertEqual((own["hide_below"], own["tiers"][0]["name"]), (10.0, "Mine"))
        self.assertEqual(loot_filter.loudness_of(own["tiers"][2]), "noticeable")
        loot_filter.apply_preset(own, "soft", RATE)
        self.assertIsNone(own["hide_below"])

    def test_sound_packs(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            own = settings()
            loot_filter.apply_sound_pack(own, "chimes", folder, RATE)
            files = [tier["sound"]["file"] for tier in own["tiers"]]
            self.assertEqual(files, ["Sakuya chimes 1.wav", "Sakuya chimes 2.wav", "Sakuya chimes 3.wav"])
            made = folder / loot_filter.SOUND_FOLDER / "Sakuya chimes 1.wav"
            self.assertGreater(made.stat().st_size, 10000)
            self.assertEqual(made.read_bytes()[:4], b"RIFF")
            loot_filter.apply_sound_pack(own, "game", folder, RATE)
            self.assertEqual([tier["sound"]["id"] for tier in own["tiers"]], [6, 2, 1])
            loot_filter.apply_sound_pack(own, "none", folder, RATE)
            self.assertEqual([tier["sound"] for tier in own["tiers"]], [None, None, None])
            self.assertEqual(own["sound_pack"], "none")

    def test_one_choice_stands_for_beam_icon_and_sound(self):
        tier = copy.deepcopy(loot_filter.DEFAULT_TIERS[0])
        self.assertEqual(loot_filter.loudness_of(tier), "loud")
        tier.update(loot_filter.loudness_marks("noticeable", tier))
        self.assertEqual(loot_filter.loudness_of(tier), "noticeable")
        tier["sound"] = {"kind": "builtin", "id": 3, "volume": 100}
        self.assertEqual(loot_filter.loudness_of(tier), "own")

    def test_a_damaged_settings_file_falls_back_field_by_field(self):
        cleaned = loot_filter.clean_settings({"auto": "yes", "base": "..\\evil.filter", "hide_below": -3,
                                              "tiers": [{"least": 2, "unit": "div", "color": "rainbow", "font": 99, "sound": {"kind": "custom", "file": "../x.exe"}}, "junk"]})
        self.assertEqual((cleaned["auto"], cleaned["base"], cleaned["hide_below"]), (False, None, None))
        self.assertEqual(len(cleaned["tiers"]), 1)
        tier = cleaned["tiers"][0]
        self.assertEqual((tier["least"], tier["color"], tier["font"]), (2.0, "red", 45))
        self.assertEqual(tier["sound"]["kind"], "builtin")  # a file name with a path in it is not taken
        self.assertEqual(loot_filter.clean_settings("junk"), loot_filter.clean_settings({}))
        old = loot_filter.clean_settings({"tiers": [{"least": 1, "unit": "div", "color": "pink", "size": "small", "beam": True, "sound": False, "icon": True}]})["tiers"][0]
        self.assertEqual((old["font"], old["beam"], old["sound"]), (35, {"color": "Pink", "temp": False}, None))  # the first version's switches still read
        self.assertEqual(len(loot_filter.clean_settings({"tiers": [{}] * 9})["tiers"]), loot_filter.MOST_TIERS)

    def test_the_file_is_written_only_when_its_rules_change(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            first = loot_filter.filter_text(PRICES, "Forbidden Rites", settings(), RATE, NOW)
            self.assertTrue(loot_filter.write_filter(folder, first))
            later = loot_filter.filter_text(PRICES, "Forbidden Rites", settings(), RATE, datetime(2026, 11, 9, 13, 0))
            self.assertFalse(loot_filter.write_filter(folder, later))
            cheaper = loot_filter.filter_text({**PRICES, "Divine Orb": 0.05}, "Forbidden Rites", settings(), RATE, NOW)
            self.assertTrue(loot_filter.write_filter(folder, cheaper))

    def test_a_chosen_sound_is_copied_beside_the_filters(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / "picked" / "coin.mp3"
            source.parent.mkdir()
            source.write_bytes(b"ID3")
            self.assertEqual(loot_filter.add_sound(folder, source), "coin.mp3")
            self.assertTrue((folder / loot_filter.SOUND_FOLDER / "coin.mp3").is_file())
            with self.assertRaises(ValueError):
                loot_filter.add_sound(folder, folder / "picked" / "tool.exe")

    def test_the_usual_filters_are_the_players_own_files(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for name in ("b.filter", "A.filter", "Sakuya.filter", "Sakuya_test.filter", "notes.txt"):
                (folder / name).write_text("", encoding="utf-8")
            self.assertEqual(loot_filter.usual_filters(folder), ["A.filter", "b.filter"])
            (folder / "My Games" / "Path of Exile 2").mkdir(parents=True)
            self.assertEqual(loot_filter.filter_folder(folder), folder / "My Games" / "Path of Exile 2")
            self.assertIsNone(loot_filter.filter_folder(folder / "nowhere"))

    def test_every_caption_has_an_english_version(self):
        captions = {"Фильтр", *(tier["name"] for tier in loot_filter.DEFAULT_TIERS), *loot_filter.LOUDNESS_TITLES.values(), *loot_filter.GAME_COLORS.values(),
                    *loot_filter.ICON_SHAPES.values(), *loot_filter.ICON_SIZES.values(), *loot_filter.KIND_TITLES.values(), *(title for title, _ in loot_filter.KIND_RULES.values()),
                    *loot_filter.ITEM_RULES.values(), *(title for title, _, _ in loot_filter.PRESETS.values()), *loot_filter.SOUND_PACKS.values(), *loot_filter.LINKS.values()}
        for node in ast.walk(ast.parse(Path(loot_filter.__file__).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "t" and node.args and isinstance(node.args[0], ast.Constant):
                captions.add(node.args[0].value)
        self.assertEqual(sorted(caption for caption in captions if caption not in crafter.ENGLISH), [])


if __name__ == "__main__":
    unittest.main()
