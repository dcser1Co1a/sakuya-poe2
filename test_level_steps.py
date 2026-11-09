"""Tests of the level steps (level_steps.py)."""
import re
import unittest
from pathlib import Path

import crafter
import level_steps
from build_items import ShownMod, parse_pob_item
from trade_search import ItemMod, StatFilter


class FakeMod:
    def __init__(self, name, level, text, ru_text=""):
        self.name, self.level, self.text, self.ru_text = name, level, text, ru_text


class FakeLadder:
    def __init__(self, side, mods):
        self.side, self.mods = side, tuple(mods)
        self.template = crafter.make_template(mods[0].text)


LIFE = FakeLadder("prefix", [FakeMod("Virile", 60, "+(100-119) to maximum Life"), FakeMod("Vigorous", 44, "+(85-99) to maximum Life"), FakeMod("Healthy", 6, "+(20-29) to maximum Life", "+(20-29) к максимуму здоровья")])
SPEED = FakeLadder("suffix", [FakeMod("of Sortilege", 55, "(19-21)% increased Cast Speed"), FakeMod("of Talent", 15, "(9-12)% increased Cast Speed")])
MANA = FakeLadder("suffix", [FakeMod("of Light", 30, "(8-12)% increased Mana Regeneration Rate / 5% increased Light Radius")])
SPELLS = FakeLadder("suffix", [FakeMod("of the Sorcerer", 78, "+(5-6) to Level of all Spell Skills"), FakeMod("of Magic", 55, "+4 to Level of all Spell Skills"),
                               FakeMod("of Wizardry", 25, "+3 to Level of all Spell Skills", "+3 к уровню всех камней умений чар")])
DESECRATED = FakeLadder("prefix", [FakeMod("Amanamu's", 65, "(148-178)% increased Spell Damage")])


class FakePage:
    name = "Staves"
    ladders = [LIFE, SPEED, MANA, SPELLS]
    desecrated_ladders = [DESECRATED]


LIFE_MOD = ShownMod("prefix", "+108(100-119) to maximum Life", 1, "Virile")
SPEED_MOD = ShownMod("suffix", "21(19-21)% increased Cast Speed", 1, "of Sortilege")
SPELL_MOD = ShownMod("suffix", "+6(5-6) to Level of all Spell Skills", 1, "of the Sorcerer")
DESECRATED_MOD = ShownMod("prefix", "157(148-178)% increased Spell Damage", 1, "Amanamu's", "desecrated")


class LevelTests(unittest.TestCase):
    def test_the_strongest_mod_a_level_allows(self):
        self.assertEqual(level_steps.highest_mod_level(30), 37)
        self.assertEqual(level_steps.highest_mod_level(48), 60)

    def test_each_mod_drops_to_the_best_tier_the_level_allows(self):
        shown = [LIFE_MOD, SPEED_MOD, ShownMod("suffix", "10(8-12)% increased Mana Regeneration Rate", 1, "of Light"), ShownMod("unknown", "Something", None, "")]
        # Level 30 allows mods up to level 37: life drops to its level 6 tier, cast speed to level 15, the hybrid of level 30 stays whole.
        self.assertEqual(level_steps.mods_at_level(shown, FakePage(), 30),
                         [("prefix", "+20 to maximum Life"), ("suffix", "9% increased Cast Speed"), ("suffix", "8% increased Mana Regeneration Rate"), ("suffix", "5% increased Light Radius")])
        self.assertEqual(level_steps.mods_at_level(shown, FakePage(), 36)[0], ("prefix", "+85 to maximum Life"))  # up to level 45: the level 44 tier
        self.assertEqual(level_steps.mods_at_level(shown, FakePage(), 4), [])  # nothing of the item rolls on an item that low

    def test_a_jewel_mod_is_found_with_its_range(self):
        chaos = FakeLadder("prefix", [FakeMod("Chaotic", 1, "(7-13)% increased Chaos Damage", "(7-13)% увеличение урона хаосом")])
        mana = FakeLadder("suffix", [FakeMod("of Mana", 40, "Recover (3-4)% of maximum Mana on Kill"), FakeMod("of Mana", 1, "Recover (1-2)% of maximum Mana on Kill")])

        class JewelPage:
            ladders = [chaos, mana]

        side, tier = level_steps.jewel_tier(JewelPage(), "13% increased Chaos Damage")
        self.assertEqual((side, tier.text), ("prefix", "(7-13)% increased Chaos Damage"))
        self.assertEqual(level_steps.jewel_tier(JewelPage(), "Recover 2% of maximum Mana on Kill")[1].level, 1)  # the tier whose range holds 2
        self.assertEqual(level_steps.jewel_tier(JewelPage(), "Recover 9% of maximum Mana on Kill")[1].level, 1)  # out of every range: the lowest
        self.assertIsNone(level_steps.jewel_tier(JewelPage(), "+5 to Strength"))
        self.assertEqual(level_steps.jewel_range(tier.text), "7–13")
        self.assertEqual(level_steps.lowest_roll(tier.text), "7% increased Chaos Damage")  # «the mod's range» searches from here, not from the jewel's 13
        self.assertEqual(level_steps.jewel_wording("13% increased Chaos Damage", tier, True), "13% увеличение урона хаосом")
        self.assertEqual(level_steps.jewel_wording("13% increased Chaos Damage", tier, False), "13% increased Chaos Damage")

    def test_a_missing_requirement_comes_from_the_strongest_mod(self):
        # Virile is a level 60 tier: 80% of it is 48. A base that needs more wins. The Lazuli Ring of the player's build had no LevelReq.
        self.assertEqual(level_steps.estimated_requirement([LIFE_MOD, SPEED_MOD], FakePage()), 48)
        self.assertEqual(level_steps.estimated_requirement([LIFE_MOD], FakePage(), 52), 52)
        self.assertEqual(level_steps.estimated_requirement([ShownMod("suffix", "21(19-21)% increased Cast Speed", 2, "of Talent")], FakePage()), 12)
        self.assertIsNone(level_steps.estimated_requirement([DESECRATED_MOD], FakePage()))

    def test_mods_a_level_cannot_have_are_told_with_the_level_they_come_at(self):
        # Level 15 allows mods up to level 18: spell levels start at a level 25 mod, worn from level 20.
        self.assertEqual(level_steps.missing_at_level([LIFE_MOD, SPELL_MOD, DESECRATED_MOD], FakePage(), 15), [("+3 to Level of all Spell Skills", 20)])
        self.assertEqual(level_steps.missing_at_level([SPELL_MOD], FakePage(), 15, russian=True), [("+3 к уровню всех камней умений чар", 20)])
        self.assertEqual(level_steps.missing_at_level([LIFE_MOD, SPELL_MOD], FakePage(), 40), [])

    def test_desecrated_mods_alloys_and_runes_are_left_out(self):
        self.assertIsNone(level_steps.ladder_of(FakePage(), "Amanamu's", "prefix"))
        self.assertEqual([mod.name for mod in level_steps.available_mods([LIFE_MOD, DESECRATED_MOD], FakePage(), 90)], ["Virile"])

    def test_how_strong_a_mod_can_be_at_a_level(self):
        self.assertAlmostEqual(level_steps.strength_at(SPELLS, 20), 3 / 6)  # +3 of +6 already at level 20
        self.assertAlmostEqual(level_steps.strength_at(LIFE, 30), 20 / 119)
        self.assertEqual(level_steps.strength_at(SPELLS, 10), 0.0)
        self.assertEqual(level_steps.mod_note(SPELL_MOD, FakePage(), 20), "+3 / +6")
        self.assertEqual(level_steps.mod_note(SPEED_MOD, FakePage(), 30), "9% / 21%")
        self.assertEqual(level_steps.mod_note(SPELL_MOD, FakePage(), 10), "— / +6")

    def test_the_key_mod_is_the_one_strongest_at_that_level(self):
        shown = [LIFE_MOD, SPEED_MOD, SPELL_MOD, DESECRATED_MOD]
        order = level_steps.key_order(level_steps.available_mods(shown, FakePage(), 20), FakePage(), 20)
        self.assertEqual(order[0].name, "of the Sorcerer")  # +3 of +6 beats 9% of 21% and +20 of +119
        rarity = ShownMod("prefix", "17(16-19)% increased Rarity of Items found", 1, "Hoarder's")
        self.assertEqual(level_steps.key_order([rarity, LIFE_MOD], FakePage(), 30)[0].name, "Virile")  # loot mods come last, however well they keep

    def test_the_trade_query_asks_for_the_ticked_mods(self):
        mods = [ItemMod("a", 1, (StatFilter(("explicit.life",), 85.0),)), ItemMod("b", 1, (StatFilter(("explicit.speed",), 1.0),))]
        every = level_steps.level_query(mods, 43, "weapon.staff", "Ashen Staff")["query"]["stats"]
        self.assertEqual(every, [{"type": "and", "filters": [{"id": "explicit.life", "value": {"min": 85}}, {"id": "explicit.speed", "value": {"min": 1}}]}])  # all ticked mods
        hybrid = [ItemMod("h", 1, (StatFilter(("explicit.mana",), 25.0), StatFilter(("explicit.light",), 5.0))), ItemMod("a", 1, (StatFilter(("explicit.life",), 85.0),))]
        self.assertEqual(len(level_steps.level_query(hybrid, 43, None, "Ashen Staff")["query"]["stats"][0]["filters"]), 3)  # both lines of a hybrid, not «2 of 3»
        half = level_steps.level_query(mods, 43, "weapon.staff", "Ashen Staff", 2, 0.5)["query"]["stats"][0]
        self.assertEqual(half["filters"], [{"id": "explicit.life", "value": {"min": 42}}, {"id": "explicit.speed"}])  # a half below 1 asks only for the mod

    def test_the_search_asks_for_the_kind_the_level_and_every_mod(self):
        mods = [ItemMod("a", 1, (StatFilter(("explicit.life",), 85.0),)), ItemMod("b", 1, (StatFilter(("explicit.speed", "explicit.speed_local"), 9.0),)), ItemMod("c", 1, ())]
        query = level_steps.level_query(mods, 36, "accessory.ring", "Gold Ring")["query"]
        self.assertEqual(query["filters"]["req_filters"]["filters"]["lvl"], {"max": 36})
        self.assertEqual(query["filters"]["type_filters"]["filters"]["category"], {"option": "accessory.ring"})
        self.assertNotIn("type", query)  # any base of the kind
        self.assertEqual(query["stats"], [{"type": "and", "filters": [{"id": "explicit.life", "value": {"min": 85}}]},
                                          {"type": "count", "value": {"min": 1}, "filters": [{"id": "explicit.speed", "value": {"min": 9}}, {"id": "explicit.speed_local", "value": {"min": 9}}]}])  # local or global
        self.assertIsNone(level_steps.level_query([ItemMod("c", 1, ())], 36, None, "Gold Ring"))
        rarity = [ItemMod("p", 1, (StatFilter(("explicit.rarity",), 12.0),)), ItemMod("s", 1, (StatFilter(("explicit.rarity",), 11.0),))]
        self.assertEqual(level_steps.level_query(rarity, 36, None, "Gold Ring")["query"]["stats"][0]["filters"], [{"id": "explicit.rarity", "value": {"min": 23}}])
        self.assertEqual(level_steps.level_query(mods, 36, None, "Gold Ring")["query"]["type"], "Gold Ring")

    def test_steps_are_where_a_mod_gets_a_better_tier(self):
        steps = level_steps.tier_steps([LIFE_MOD, SPEED_MOD, SPELL_MOD, DESECRATED_MOD], FakePage(), 20, 70, True)
        levels = [level for level, _ in steps]
        self.assertEqual(levels, sorted(levels))
        self.assertTrue(all(20 < level <= 70 for level in levels))
        at_44 = dict(steps)[44]  # +4 opens at 55 × 0.8 = 44, and so does the best cast speed: both are named
        self.assertIn("+4 to Level of all Spell Skills", at_44)
        self.assertIn("19% increased Cast Speed", at_44)
        self.assertLessEqual(len(steps), level_steps.MOST_STEPS)
        self.assertEqual(level_steps.tier_steps([LIFE_MOD], FakePage(), 90, 70, True), [])

    def test_a_craft_for_the_level_keeps_its_item_level_wearable(self):
        goal = level_steps.craft_goal([LIFE_MOD, SPEED_MOD, SPELL_MOD, DESECRATED_MOD], FakePage(), "Ashen Staff", 30)
        self.assertEqual((goal["base"], goal["ilvl"]), ("Ashen Staff", 37))
        self.assertEqual({(mod["template"], mod["tier"]) for mod in goal["mods"]}, {(LIFE.template, 3), (SPEED.template, 2), (SPELLS.template, 3)})
        self.assertFalse(any(mod["desecrated"] for mod in goal["mods"]))
        self.assertIsNone(level_steps.craft_goal([DESECRATED_MOD], FakePage(), "Ashen Staff", 30))

    def test_a_search_looks_at_a_band_of_levels(self):
        self.assertEqual(level_steps.band(15), (14, 21))
        self.assertEqual(level_steps.band(22), (21, 28))
        self.assertEqual(level_steps.band(1), (1, 7))
        mods = [ItemMod("a", 1, (StatFilter(("explicit.life",), 40.0),))]
        query = level_steps.level_query(mods, 21, None, "Withered Wand", 1, 1.0, 14)["query"]
        self.assertEqual(query["filters"]["req_filters"]["filters"]["lvl"], {"min": 14, "max": 21})
        self.assertEqual(query["type"], "Withered Wand")  # «only this base»

    def test_mods_are_cut_to_what_the_low_end_of_the_band_has(self):
        # +3 to spells is a level 25 mod, worn from about level 20: not at the band's low end 14, so it asks for its lowest tier the top 21 allows.
        self.assertEqual(level_steps.mods_in_band([LIFE_MOD, SPELL_MOD], FakePage(), 14, 21), [("prefix", "+20 to maximum Life"), ("suffix", "+3 to Level of all Spell Skills")])
        self.assertEqual(level_steps.mods_in_band([LIFE_MOD, SPELL_MOD], FakePage(), 5, 12), [("prefix", "+20 to maximum Life")])  # nothing of it below level 20

    def test_mods_with_the_same_name_are_told_apart_by_their_wording(self):
        havoc_crit = FakeLadder("suffix", [FakeMod("of Havoc", 55, "(80-89)% increased Critical Hit Chance for Spells")])
        havoc_chaos = FakeLadder("suffix", [FakeMod("of Havoc", 55, "+4 to Level of all Chaos Spell Skills")])
        page = type("Page", (), {"ladders": [havoc_crit, havoc_chaos], "desecrated_ladders": []})()
        self.assertIs(level_steps.ladder_for(page, ShownMod("suffix", "+4 to Level of all Chaos Spell Skills", 2, "of Havoc")), havoc_chaos)
        self.assertIs(level_steps.ladder_for(page, ShownMod("suffix", "85(80-89)% increased Critical Hit Chance for Spells", 2, "of Havoc")), havoc_crit)

    def test_an_item_copied_in_the_game_is_read_with_its_tiers(self):
        wand = "\n".join(["Item Class: Wands", "Rarity: Rare", "Blight Spire", "Withered Wand", "--------", "Requires: Level 44", "--------", "Item Level: 79", "--------",
                          "{ Implicit Modifier }", "Grants Skill: Level 18 Chaos Bolt (implicit)", "--------",
                          '{ Prefix Modifier "Vigorous" (Tier: 2) — Life }', "+90(85-99) to maximum Life",
                          '{ Suffix Modifier "of Magic" (Tier: 2) — Caster, Gem }', "+4 to Level of all Spell Skills", "(a hint)"])
        page = FakePage()
        page.by_name = {("prefix", "vigorous"): LIFE.mods[1], ("suffix", "of magic"): SPELLS.mods[1]}
        slot, item, mods, base = level_steps.copied_item(wand, lambda base: page, lambda line: "Withered Wand")
        self.assertEqual((slot, item.name, item.base_line, item.level_req, item.item_level, base), ("Weapon 1", "Blight Spire", "Withered Wand", 44, 79, "Withered Wand"))
        self.assertEqual([(mod.kind, mod.tier, mod.name, mod.text) for mod in mods], [("prefix", 2, "Vigorous", "+90(85-99) to maximum Life"), ("suffix", 2, "of Magic", "+4 to Level of all Spell Skills")])
        self.assertEqual([line.text for line in item.lines], ["Grants Skill: Level 18 Chaos Bolt (implicit)"])
        russian = wand.replace("Item Class: Wands", "Класс предмета: Жезлы").replace("Requires: Level 44", "Требуется: Уровень 44, 79 Инт").replace("Rarity: Rare", "Редкость: Редкий")
        self.assertEqual(level_steps.copied_item(russian, lambda base: page, lambda line: "Withered Wand")[1].level_req, 44)
        self.assertIsNone(level_steps.copied_item("eNrtcode", lambda base: page, lambda line: None))
        self.assertEqual(level_steps.copied_item(wand.replace("Wands", "Rings"), lambda base: page, lambda line: "Withered Wand")[0], "Ring 1")

    def test_the_search_is_told_before_it_opens(self):
        summary = level_steps.search_summary(["+2 к уровню всех камней умений чар хаоса", "45% увеличение урона от чар"], 21, 28, 1, "kind")
        self.assertEqual(summary, "Ищу: любая база этого вида, требование 21–28 ур., хотя бы 1 из: +2 к уровню всех камней умений чар хаоса; 45% увеличение урона от чар")
        self.assertEqual(level_steps.search_summary([], 21, 28, 1, "kind"), "")
        english = level_steps.search_summary(["+2 to Level of all Chaos Spell Skills"], 21, 28, 1, "base", lambda text: crafter.ENGLISH.get(text, text))
        self.assertEqual(english, "Looking for: this base only, needing level 21–28, the mod: +2 to Level of all Chaos Spell Skills")

    def test_the_ticked_mods_are_the_players_or_else_the_strictness(self):
        options = [("a", "A", True), ("b", "B", False), ("c", "C", True)]
        item = ("Blight Spire", "Withered Wand")
        level_steps.chosen_mods.clear()
        self.assertEqual(level_steps.checked_keys(item, 27, options), {"a", "c"})
        level_steps.chosen_mods[(item, 27)] = {"b", "gone"}
        self.assertEqual(level_steps.checked_keys(item, 27, options), {"b"})  # a mod the item no longer has at this level is dropped
        self.assertEqual(level_steps.checked_keys(item, 29, options), {"a", "c"})  # each level keeps its own ticks
        self.assertNotEqual(level_steps.mod_key(ShownMod("prefix", "17% increased Rarity of Items found", 1, "Hoarder's")),
                            level_steps.mod_key(ShownMod("suffix", "17% increased Rarity of Items found", 1, "of Archaeology")))
        level_steps.chosen_mods.clear()
        two = level_steps.search_summary(["a", "b", "c"], 26, 33, 2, "kind")
        self.assertIn("хотя бы 2 из: a; b; c", two)
        self.assertIn("все из: a; b", level_steps.search_summary(["a", "b"], 17, 24, 2, "kind"))

    def test_every_ticked_mod_is_wanted(self):
        self.assertEqual(level_steps.needed_count(2), 2)  # the screenshot: «key mod» and two ticks found a wand with only one of them
        self.assertEqual(level_steps.needed_count(0), 1)

    def test_the_item_keeps_its_level_requirement(self):
        item = parse_pob_item("Rarity: RARE\nA\nGold Ring\nItem Level: 80\nLevelReq: 60\nImplicits: 0\n+108 to maximum Life")
        self.assertEqual(item.level_req, 60)
        self.assertIsNone(parse_pob_item("Rarity: RARE\nA\nGold Ring\nImplicits: 0\nX").level_req)

    def test_every_caption_has_an_english_version(self):
        own = Path(level_steps.__file__).read_text(encoding="utf-8")
        captions = set(re.findall(r'\bt\("((?:[^"\\]|\\.)*)"\)', own)) | {"Мой уровень", "На этом уровне у вещи нет модов из её списка", "ур."}
        self.assertEqual(sorted(caption for caption in captions if caption not in crafter.ENGLISH), [])


if __name__ == "__main__":
    unittest.main()
