import random
import unittest

import crafter
import trade_search
from crafter import (
    DESECRATE_OPTIONS,
    DESECRATED_JUNK,
    HIT,
    NONE,
    NOT_DESECRATED,
    Action,
    Database,
    Mod,
    Page,
    Planner,
    Simulation,
    State,
    budget_advice,
    make_want,
    normalize_desecrated,
    parse_item,
    simulate_plan,
    state_of_mods,
    surer_mode,
)
from trade_search import ItemMod, StatFilter, build_query, mods_on_by_default, read_item_totals, recalled_mods, remember_search, search_memory_key

PRICES = {"Orb of Transmutation": 1.0, "Orb of Augmentation": 1.0, "Orb of Alchemy": 2.0, "Regal Orb": 2.0, "Exalted Orb": 1.0, "Chaos Orb": 1.0, "Orb of Annulment": 10.0, "Divine Orb": 100.0, crafter.NEW_BASE: 1.0,
          "Preserved Jawbone": 2.0, "Ancient Jawbone": 20.0, "Omen of Sinistral Necromancy": 3.0, "Omen of Dextral Necromancy": 3.0, "Omen of Abyssal Echoes": 4.0, "Omen of Light": 50.0}
REVEAL = 2500


def regular(number: int, side: str = "prefix", level: int = 1, weight: int = 1000) -> Mod:
    return Mod(f"m{side}{number}", side, level, (f"group{side}{number}",), weight, True, f"+(1-2) to stat{side}{number}", f"+# to stat{side}{number}")


def desecrated(number: int, side: str = "prefix", level: int = 65) -> Mod:
    return Mod("Amanamu's", side, level, (f"dark{side}{number}",), REVEAL, False, f"+(1-2) to dark{side}{number}", f"+# to dark{side}{number}", "Амануму", f"+(1-2) к тьме{side}{number}", True)


def make_page(name: str = "Daggers") -> Page:
    mods = [regular(number) for number in range(3)] + [regular(number, "suffix") for number in range(3)]
    return Page(name, mods, [], [desecrated(0), desecrated(0, "suffix")])


def want_of(page: Page, template: str, ladders: list | None = None):
    ladder = next(found for found in ladders or page.ladders if found.template == template)
    return make_want(ladder, None, 82)


class DesecrationTests(unittest.TestCase):
    def setUp(self):
        self.page = make_page()
        self.want = want_of(self.page, "+# to statprefix0")
        self.planner = Planner(self.page, 82, [self.want], PRICES)
        self.rare = State("rare", (NONE,), 0, 0)

    def test_the_right_bone_for_each_item(self):
        self.assertEqual(make_page("Daggers").bones(82), ["Preserved Jawbone", "Ancient Jawbone"])
        self.assertEqual(make_page("Quivers").bones(82)[0], "Preserved Jawbone")
        self.assertEqual(make_page("Rings").bones(82)[0], "Preserved Collarbone")
        self.assertEqual(make_page("Helmets_str").bones(82)[0], "Preserved Rib")

    def test_a_gnawed_bone_only_up_to_its_item_level(self):
        self.assertEqual(make_page().bones(64)[0], "Gnawed Jawbone")
        self.assertNotIn("Gnawed Jawbone", make_page().bones(65))

    def test_no_data_means_no_bones(self):
        self.assertEqual(Page("Daggers", [regular(0)]).bones(82), [])

    def test_only_a_rare_item_can_be_desecrated(self):
        self.assertEqual(self.planner.outcomes(State("magic", (NONE,), 0, 0), Action("desecrate", (), "Preserved Jawbone")), {})

    def test_a_desecrated_item_cannot_be_desecrated_again(self):
        self.assertEqual(self.planner.outcomes(self.rare._replace(junk_prefix=1, desecrated=DESECRATED_JUNK["prefix"]), Action("desecrate", (), "Preserved Jawbone")), {})

    def odds(self, omens: tuple = ()) -> float:
        outcomes = self.planner.outcomes(self.rare, Action("desecrate", omens, "Preserved Jawbone"))
        self.assertAlmostEqual(sum(outcomes.values()), 1)
        return outcomes.get(self.rare._replace(status=(HIT,), desecrated=1), 0)

    def test_the_chance_counts_every_option_of_the_reveal(self):
        # Three regular prefixes and one desecrated: the wanted one is 1000 of 5500, and it has to show up among the options.
        single = 1000 / 5500
        self.assertAlmostEqual(self.odds(("Omen of Sinistral Necromancy",)), 1 - (1 - single) ** DESECRATE_OPTIONS)

    def test_an_echo_gives_a_second_set_of_options(self):
        single = 1000 / 5500
        self.assertAlmostEqual(self.odds(("Omen of Sinistral Necromancy", "Omen of Abyssal Echoes")), 1 - (1 - single) ** (2 * DESECRATE_OPTIONS))

    def test_a_side_omen_keeps_the_mod_on_its_side(self):
        outcomes = self.planner.outcomes(self.rare, Action("desecrate", ("Omen of Dextral Necromancy",), "Preserved Jawbone"))
        self.assertEqual(outcomes, {self.rare._replace(junk_suffix=1, desecrated=DESECRATED_JUNK["suffix"]): 1.0})

    def test_without_an_omen_the_side_is_left_to_chance(self):
        self.assertAlmostEqual(self.odds(), 0.5 * (1 - (1 - 1000 / 5500) ** DESECRATE_OPTIONS))

    def test_a_full_side_takes_no_mod(self):
        full = self.rare._replace(junk_prefix=3)
        self.assertEqual(self.planner.outcomes(full, Action("desecrate", ("Omen of Sinistral Necromancy",), "Preserved Jawbone")), {})

    def test_an_ancient_bone_leaves_out_low_tiers(self):
        page = Page("Daggers", [regular(0, level=1), regular(0, level=50, weight=1000), regular(1)], [], [desecrated(0)])
        ladder = page.ladders[0]
        low = make_want(ladder, None, 82)
        planner = Planner(page, 82, [low], PRICES)
        self.assertEqual(sum(mod.level < 40 and mod.name == low.ladder.mods[-1].name for mod in page.reveal_pool(82, 40)), 0)
        self.assertLess(planner.reveal_tables[40]["hit"][0], planner.reveal_tables[0]["hit"][0])

    def test_light_removes_only_an_unwanted_desecrated_mod(self):
        light = Action("annulment", ("Omen of Light",))
        unwanted = self.rare._replace(junk_prefix=2, desecrated=DESECRATED_JUNK["prefix"])
        self.assertEqual(self.planner.outcomes(unwanted, light), {self.rare._replace(junk_prefix=1): 1.0})
        self.assertEqual(self.planner.outcomes(self.rare._replace(status=(HIT,), desecrated=1), light), {})
        self.assertEqual(self.planner.outcomes(self.rare._replace(junk_prefix=1), light), {})

    def test_a_random_removal_may_take_the_desecrated_mod(self):
        state = self.rare._replace(junk_prefix=2, desecrated=DESECRATED_JUNK["prefix"])
        outcomes = self.planner._remove(state, "prefix")
        self.assertAlmostEqual(outcomes[self.rare._replace(junk_prefix=1)], 0.5)
        self.assertAlmostEqual(outcomes[state._replace(junk_prefix=1)], 0.5)

    def test_a_fractured_desecrated_mod_stays_put(self):
        locked = self.rare._replace(junk_prefix=1, locked=crafter.LOCKED_JUNK["prefix"], desecrated=DESECRATED_JUNK["prefix"])
        self.assertEqual(self.planner.outcomes(locked, Action("annulment", ("Omen of Light",))), {})
        self.assertEqual(self.planner._remove(locked, "prefix"), {})

    def test_a_large_goal_with_every_kind_of_action_is_solved(self):
        wants = [want_of(self.page, f"+# to statprefix{number}") for number in range(2)] + [want_of(self.page, "+# to statsuffix0")]
        plan = Planner(self.page, 82, wants, {**PRICES, "Fracturing Orb": 5.0}).solve(State("normal", (NONE,) * 3, 0, 0))
        self.assertGreater(plan.values[plan.start], 0)

    def test_removing_a_wanted_desecrated_mod_frees_the_item(self):
        state = self.rare._replace(status=(HIT,), desecrated=1)
        self.assertEqual(self.planner._remove(state, "prefix"), {self.rare: 1.0})

    def test_a_goal_only_a_bone_can_reach_is_solved(self):
        want = want_of(self.page, "+# to darkprefix0", self.page.desecrated_ladders)
        self.assertTrue(want.desecrated_only)
        plan = Planner(self.page, 82, [want], PRICES).solve(State("normal", (NONE,), 0, 0))
        self.assertTrue(plan.uses_desecration)
        self.assertGreater(plan.values[plan.start], 0)

    def test_such_a_goal_survives_the_cheap_mode_price_limit(self):
        want = want_of(self.page, "+# to darkprefix0", self.page.desecrated_ladders)
        prices = {**PRICES, "Preserved Jawbone": 90.0, "Ancient Jawbone": 90.0}
        self.assertTrue(Planner(self.page, 82, [want], prices, "budget").solve(State("normal", (NONE,), 0, 0)).uses_desecration)

    def test_no_bone_no_such_goal(self):
        want = want_of(self.page, "+# to darkprefix0", self.page.desecrated_ladders)
        prices = {name: value for name, value in PRICES.items() if not name.endswith("Jawbone")}
        with self.assertRaises(ValueError):
            Planner(self.page, 82, [want], prices)

    def test_two_goals_only_bones_can_reach_are_refused(self):
        with self.assertRaises(ValueError):
            Planner(self.page, 82, [want_of(self.page, "+# to darkprefix0", self.page.desecrated_ladders), want_of(self.page, "+# to darksuffix0", self.page.desecrated_ladders)], PRICES)

    def test_a_cheap_bone_makes_a_regular_goal_cheaper(self):
        start = State("normal", (NONE,), 0, 0)
        without = {name: value for name, value in PRICES.items() if not name.endswith("Jawbone")}
        with_bone = Planner(self.page, 82, [self.want], {**PRICES, "Orb of Augmentation": 40.0, "Orb of Transmutation": 40.0, "Exalted Orb": 40.0, "Chaos Orb": 40.0, crafter.NEW_BASE: 40.0, "Regal Orb": 40.0, "Orb of Alchemy": 1.0}).solve(start)
        plain = Planner(self.page, 82, [self.want], {**without, "Orb of Augmentation": 40.0, "Orb of Transmutation": 40.0, "Exalted Orb": 40.0, "Chaos Orb": 40.0, crafter.NEW_BASE: 40.0, "Regal Orb": 40.0, "Orb of Alchemy": 1.0}).solve(start)
        self.assertLess(with_bone.values[start], plain.values[start])
        self.assertTrue(with_bone.uses_desecration)
        self.assertFalse(plain.uses_desecration)

    def test_the_runs_agree_with_the_calculation_when_bones_are_used(self):
        want = want_of(self.page, "+# to darkprefix0", self.page.desecrated_ladders)
        plan = Planner(self.page, 82, [want], PRICES).solve(State("normal", (NONE,), 0, 0))
        result = simulate_plan(plan, 4000, random.Random(3))
        self.assertLess(abs(result.mean - plan.values[plan.start]) / plan.values[plan.start], 0.08)

    def test_a_real_item_tells_which_mod_is_desecrated(self):
        dark, plain = self.page.desecrated[0], self.page.mods[1]
        want = want_of(self.page, "+# to darkprefix0", self.page.desecrated_ladders)
        self.assertEqual(state_of_mods("rare", [("prefix", dark), ("prefix", plain)], [want], None, ("prefix", dark)).desecrated, 1)
        other = want_of(self.page, "+# to statprefix0")
        self.assertEqual(state_of_mods("rare", [("prefix", dark)], [other], None, ("prefix", dark)).desecrated, DESECRATED_JUNK["prefix"])
        self.assertEqual(state_of_mods("rare", [("prefix", plain)], [other]).desecrated, NOT_DESECRATED)

    def test_mods_with_one_name_are_told_apart_by_their_words(self):
        first = Mod("Amanamu's", "prefix", 65, ("a",), REVEAL, False, "+(1-2) to shadow", "+# to shadow", "А", "+(1-2) к тени", True)
        second = Mod("Amanamu's", "prefix", 65, ("b",), REVEAL, False, "+(1-2) to dread", "+# to dread", "А", "+(1-2) к ужасу", True)
        page = Page("Daggers", [regular(0)], [], [first, second])
        self.assertIs(page.find_desecrated("prefix", "+2 to dread"), second)
        self.assertIs(page.find_desecrated("prefix", "+1(1-2) to shadow"), first)
        self.assertIs(page.find_desecrated("prefix", "+1 к ужасу"), second)
        self.assertIsNone(page.find_desecrated("suffix", "+2 to dread"))


class PerfectEssenceAndOmenTests(unittest.TestCase):
    """Worked out by hand on a small page, so the numbers can be checked."""

    def page(self, levels=(10, 20, 30), essence_text="+(100-120) life"):
        mods = [crafter.Mod("Life", "prefix", 80, ("Life",), 100, True, "+(90-99) life", "+# life"), crafter.Mod("Cold", "suffix", 80, ("Cold",), 100, True, "+(5-9)% cold", "+#% cold")]
        mods += [crafter.Mod(f"P{level}", "prefix", level, (f"P{level}",), 100, True, f"p{level}", f"p{level}") for level in levels]
        mods += [crafter.Mod(f"S{level}", "suffix", level, (f"S{level}",), 100, True, f"s{level}", f"s{level}") for level in levels]
        essences = [crafter.Essence("Perfect Essence of the Body", "prefix", 72, ("Life",), essence_text, perfect=True), crafter.Essence("Lesser Essence of the Body", "prefix", 80, ("Life",))]
        return crafter.Page("Rings", mods, essences)

    PRICES = {"Perfect Essence of the Body": 10, "Lesser Essence of the Body": 1, "Omen of Sinistral Crystallisation": 3, "Omen of Dextral Crystallisation": 3, "Omen of Whittling": 2, "Chaos Orb": 1}

    def planner(self, want_tier=1, essence_text="+(100-120) life"):
        page = self.page(essence_text=essence_text)
        wants = [crafter.make_want(page.ladders[0], want_tier, 82)]
        return crafter.Planner(page, 82, wants, self.PRICES), wants

    def state(self, status=crafter.NONE, prefix=0, suffix=0, rarity="rare"):
        return crafter.State(rarity, (status,), prefix, suffix)

    def action(self, planner, omens=()):
        return next(action for action in planner.actions if action.family == "perfect_essence" and action.omens == omens)

    def test_perfect_essences_are_their_own_action_on_rare_items_only(self):
        planner, _ = self.planner()
        self.assertTrue(any(action.family == "perfect_essence" for action in planner.actions))
        self.assertFalse(any(action.family == "essence" and action.essence.startswith("Perfect") for action in planner.actions))
        self.assertEqual(planner.outcomes(self.state(rarity="magic", prefix=1), self.action(planner)), {})

    def test_every_action_of_this_kind_names_its_essence(self):
        planner, _ = self.planner()
        self.assertTrue(all(action.essence for action in planner.actions if action.family == "perfect_essence"))

    def test_it_removes_a_random_mod_and_adds_its_own(self):
        planner, _ = self.planner()
        result = planner.outcomes(self.state(prefix=1, suffix=1), self.action(planner))
        self.assertEqual(sum(result.values()), 1)
        self.assertEqual(result, {self.state(crafter.HIT, 0, 1): 0.5, self.state(crafter.HIT, 1, 0): 0.5})

    def test_the_omen_decides_the_side(self):
        planner, _ = self.planner()
        result = planner.outcomes(self.state(prefix=1, suffix=1), self.action(planner, ("Omen of Dextral Crystallisation",)))
        self.assertEqual(result, {self.state(crafter.HIT, 1, 0): 1.0})

    def test_a_chance_of_no_room_is_not_risked(self):
        planner, _ = self.planner()
        full = self.state(prefix=3, suffix=1)
        self.assertEqual(planner.outcomes(full, self.action(planner)), {})
        self.assertEqual(planner.outcomes(full, self.action(planner, ("Omen of Dextral Crystallisation",))), {})
        self.assertEqual(planner.outcomes(full, self.action(planner, ("Omen of Sinistral Crystallisation",))), {self.state(crafter.HIT, 2, 1): 1.0})

    def test_nothing_to_remove_means_it_cannot_be_used(self):
        planner, _ = self.planner()
        self.assertEqual(planner.outcomes(self.state(), self.action(planner)), {})

    def test_a_fractured_mod_stays(self):
        planner, _ = self.planner()
        locked = self.state(prefix=1, suffix=1)._replace(locked=crafter.LOCKED_JUNK["prefix"])
        self.assertEqual(planner.outcomes(locked, self.action(planner)), {locked._replace(status=(crafter.HIT,), junk_suffix=0): 1.0})

    def test_a_perfect_essence_is_judged_by_its_numbers_not_by_its_level(self):
        planner, _ = self.planner(essence_text="+(90-120) life")
        self.assertEqual(planner.essences["Perfect Essence of the Body"][1], crafter.HIT)
        planner, _ = self.planner(essence_text="+(40-99) life")
        self.assertEqual(planner.essences["Perfect Essence of the Body"][1], crafter.WRONG_TIER)
        planner, _ = self.planner(essence_text="+95 life")
        self.assertEqual(planner.essences["Perfect Essence of the Body"][1], crafter.HIT)

    def test_a_perfect_essence_of_another_stat_in_the_family_does_not_count(self):
        planner, _ = self.planner(essence_text="+200 mana")
        self.assertNotIn("Perfect Essence of the Body", planner.essences)
        self.assertFalse(any(action.family == "perfect_essence" for action in planner.actions))

    def test_an_ordinary_essence_goes_on_by_its_level(self):
        planner, _ = self.planner()
        self.assertEqual(planner.essences["Lesser Essence of the Body"][1], crafter.HIT)

    def whittling(self, planner):
        return planner._remove_lowest

    def test_whittling_takes_an_unwanted_mod_when_the_wanted_one_stands_high(self):
        planner, _ = self.planner()
        # Every unwanted mod in the pool is below the wanted mod's level 80, so the unwanted one is always the lowest.
        result = planner._remove_lowest(self.state(crafter.HIT, 1, 0))
        self.assertEqual(result, {self.state(crafter.HIT, 0, 0): 1.0})

    def test_whittling_risks_a_wanted_mod_that_stands_low(self):
        page = self.page()
        low = crafter.Mod("Low", "prefix", 15, ("Low",), 100, True, "low", "low")
        page = crafter.Page("Rings", [*page.mods, low])
        ladder = next(found for found in page.ladders if found.mods[0] is low or low in found.mods)
        wants = [crafter.make_want(ladder, 1, 82)]
        planner = crafter.Planner(page, 82, wants, self.PRICES)
        result = planner._remove_lowest(crafter.State("rare", (crafter.HIT,), 1, 0))
        above = sum(weight for level, weight in planner.unwanted_levels if level > 15) / sum(weight for _, weight in planner.unwanted_levels)
        self.assertAlmostEqual(result[crafter.State("rare", (crafter.NONE,), 1, 0)], above)
        self.assertAlmostEqual(sum(result.values()), 1)

    def test_two_unwanted_mods_lower_the_risk(self):
        page = self.page()
        low = crafter.Mod("Low", "prefix", 15, ("Low",), 100, True, "low", "low")
        page = crafter.Page("Rings", [*page.mods, low])
        ladder = next(found for found in page.ladders if low in found.mods)
        planner = crafter.Planner(page, 82, [crafter.make_want(ladder, 1, 82)], self.PRICES)
        one = planner._remove_lowest(crafter.State("rare", (crafter.HIT,), 1, 0))[crafter.State("rare", (crafter.NONE,), 1, 0)]
        two = planner._remove_lowest(crafter.State("rare", (crafter.HIT,), 1, 1))[crafter.State("rare", (crafter.NONE,), 1, 1)]
        self.assertLess(two, one)

    def test_whittling_with_only_a_wanted_mod_takes_that(self):
        planner, _ = self.planner()
        self.assertEqual(planner._remove_lowest(self.state(crafter.HIT)), {self.state(): 1.0})

    def test_whittling_is_on_the_chaos_orb_and_the_words_exist(self):
        planner, _ = self.planner()
        action = next(found for found in planner.actions if found.omens == (crafter.OMEN_OF_WHITTLING,))
        self.assertEqual(action.family, "chaos")
        self.assertTrue(crafter.explain_action(action, self.state(prefix=1)))
        self.assertTrue(crafter.omen_text(crafter.OMEN_OF_WHITTLING))
        self.assertTrue(crafter.omen_text("Omen of Sinistral Crystallisation"))
        self.assertTrue(crafter.explain_action(self.action(planner, ("Omen of Sinistral Crystallisation",)), self.state(prefix=1)))

    def test_a_plan_can_use_them_and_is_worth_it_when_cheap(self):
        page = self.page()
        low_level_essence = crafter.Essence("Perfect Essence of the Body", "prefix", 72, ("Life",), "+(100-120) life", perfect=True)
        page = crafter.Page("Rings", page.mods, [low_level_essence])
        prices = {"Perfect Essence of the Body": 1, "Orb of Transmutation": 1, "Orb of Augmentation": 1, "Regal Orb": 1, "Exalted Orb": 500, "Chaos Orb": 500, "Orb of Annulment": 500, "Orb of Alchemy": 1, "Omen of Dextral Crystallisation": 1}
        wants = [crafter.make_want(page.ladders[0], 1, 82)]
        planner = crafter.Planner(page, 82, wants, prices)
        start = crafter.State("rare", (crafter.NONE,), 1, 1)
        plan = planner.solve(start)
        self.assertEqual(plan.policy[start].family, "perfect_essence")

    def test_the_data_reader_takes_all_that_act_on_a_rare_item(self):
        def entry(name):
            return {"ModGenerationTypeID": "1", "Name": name, "Level": "72", "ModFamilyList": ["F"], "str": "x"}

        found = crafter.normalize_perfect_essences([entry("Perfect Essence of the Mind"), entry("Essence of Hysteria"), entry("Swift Alloy")], [entry("Совершенная"), entry("Истерия"), entry("Лёгкий сплав")])
        self.assertEqual([item["name"] for item in found], ["Perfect Essence of the Mind", "Essence of Hysteria", "Swift Alloy"])
        self.assertTrue(all(item["perfect"] for item in found))


class NextTierTests(unittest.TestCase):
    def page(self):
        mods = [crafter.Mod("A", "prefix", 80, ("Life",), 100, True, "+(70-79) to Life", "+# to Life", "", "+(70-79) к здоровью"), crafter.Mod("B", "prefix", 60, ("Life",), 100, True, "+(60-69) to Life", "+# to Life", "", "+(60-69) к здоровью"), crafter.Mod("C", "prefix", 40, ("Life",), 100, True, "+(50-59) to Life", "+# to Life", "", "+(50-59) к здоровью"),
                crafter.Mod("D", "suffix", 20, ("Cold",), 100, True, "+(5-9)% to Cold", "+#% to Cold", "", "+(5-9)% к холоду"), crafter.Mod("E", "suffix", 10, ("Cold",), 100, True, "+(1-4)% to Cold", "+#% to Cold", "", "+(1-4)% к холоду")]
        return crafter.Page("Rings", mods)

    def test_the_tier_above_is_named_in_either_language(self):
        page = self.page()
        self.assertEqual(crafter.next_tier_hint(page, "+55(50-59) to Life", 3, 82), "▲ 60-69")
        self.assertEqual(crafter.next_tier_hint(page, "+55(50-59) к здоровью", 3, 82), "▲ 60-69")

    def test_the_best_tier_has_nothing_above(self):
        self.assertIsNone(crafter.next_tier_hint(self.page(), "+75(70-79) to Life", 1, 82))

    def test_an_item_too_low_is_told_the_level(self):
        self.assertIn("80", crafter.next_tier_hint(self.page(), "+65(60-69) to Life", 2, 70))

    def test_an_unknown_line_says_nothing(self):
        self.assertIsNone(crafter.next_tier_hint(self.page(), "+5 to Nothing", 3, 82))

    def mod(self, label, tier):
        return trade_search.ItemMod(label, tier, ())

    def test_the_goal_lifts_the_weakest_and_keeps_the_others(self):
        wants, title = crafter.upgrade_goal(self.page(), [self.mod("+55(50-59) to Life", 3), self.mod("+7(5-9)% to Cold", 1)], 82)
        self.assertEqual({want.ladder.template: want.min_tier for want in wants}, {"+# to Life": 2, "+#% to Cold": 1})

    def test_nothing_can_rise_on_an_item_too_low_or_already_best(self):
        self.assertIsNone(crafter.upgrade_goal(self.page(), [self.mod("+75(70-79) to Life", 1)], 82))
        self.assertIsNone(crafter.upgrade_goal(self.page(), [self.mod("+65(60-69) to Life", 2)], 70))

    def test_an_impossible_tier_on_the_item_gives_no_goal_instead_of_an_error(self):
        page = self.page()
        self.assertIsNone(crafter.upgrade_goal(page, [self.mod("+55(50-59) to Life", 3), self.mod("+7(5-9)% to Cold", 1)], 15))

    def test_links(self):
        self.assertEqual(crafter.poe2db_link("Hexer's Robe", "en"), "https://poe2db.tw/us/Hexers_Robe")
        self.assertTrue(crafter.poe2db_link("Ruby Ring", "ru").startswith("https://poe2db.tw/ru/"))


class AlloyAndRuneTests(unittest.TestCase):
    PRICES = {"Swift Alloy": 10, "Kolr's Hunt": 200, "Artificer's Orb": 1, "Chaos Orb": 1, "Exalted Orb": 2, "Orb of Transmutation": 1, "Orb of Augmentation": 1, "Regal Orb": 1, "Divine Orb": 500,
              "Omen of Sinistral Crystallisation": 1, "Omen of Dextral Crystallisation": 1, crafter.NEW_BASE: 5}

    def page(self):
        mods = [crafter.Mod("Life", "prefix", 80, ("Life",), 1000, True, "+(90-99) life", "+# life"), crafter.Mod("Cold", "suffix", 10, ("Cold",), 1000, True, "+(5-9)% cold", "+#% cold")]
        alloy = crafter.Essence("Swift Alloy", "suffix", 45, ("CastSpeed",), "(9-12)% increased Cast Speed", "", True)
        marks = [crafter.Mod("Kolr's", "prefix", 45, ("Marks",), 1000, False, "+(1-2) to Marks", "+# to Marks", rune="Kolr's Hunt"), crafter.Mod("Kolr's", "prefix", 65, ("Marks",), 1000, False, "+(3-4) to Marks", "+# to Marks", rune="Kolr's Hunt")]
        return crafter.Page("Gloves_dex", mods, [alloy], [], marks)

    def test_a_mod_only_an_alloy_gives_gets_its_own_row_and_never_rolls(self):
        page = self.page()
        self.assertEqual([ladder.mods[0].only_from for ladder in page.special_ladders], ["Swift Alloy"])
        self.assertNotIn("Swift Alloy", [mod.name for mod in page.pool(82)])

    def test_the_plan_reaches_it_with_the_alloy_and_no_omen(self):
        page = self.page()
        want = crafter.make_want(page.special_ladders[0], None, 82)
        planner = crafter.Planner(page, 82, [want], self.PRICES)
        self.assertEqual({action.omens for action in planner.actions if action.family == "perfect_essence"}, {()})
        plan = planner.solve(crafter.State("normal", (crafter.NONE,), 0, 0))
        self.assertGreater(plan.usage["Swift Alloy"], 0.9)

    def test_with_no_price_for_the_alloy_it_says_so(self):
        page = self.page()
        want = crafter.make_want(page.special_ladders[0], None, 82)
        with self.assertRaisesRegex(ValueError, "Swift|Сплав|сплав"):
            crafter.Planner(page, 82, [want], {key: value for key, value in self.PRICES.items() if key != "Swift Alloy"})

    def test_the_cheap_mode_may_still_use_the_only_way_there(self):
        page = self.page()
        want = crafter.make_want(page.special_ladders[0], None, 82)
        planner = crafter.Planner(page, 82, [want], {**self.PRICES, "Swift Alloy": 400}, "budget")
        self.assertTrue(any(action.essence == "Swift Alloy" for action in planner.actions))

    def test_rune_mods_roll_only_with_the_rune(self):
        page = self.page()
        self.assertFalse(any(mod.rune for mod in page.pool(82)))
        self.assertEqual(len([mod for mod in page.pool(82, 0, ("Kolr's Hunt",)) if mod.rune]), 2)
        self.assertFalse(any(mod.rune for mod in crafter.Planner(page, 82, [crafter.make_want(page.ladders[0], None, 82)], self.PRICES).tables[0] and page.pool(82)))

    def test_a_rune_goal_pays_for_the_rune_and_the_socket_once(self):
        page = self.page()
        want = crafter.make_want(page.rune_ladders[0], 1, 82)
        planner = crafter.Planner(page, 82, [want], self.PRICES)
        self.assertEqual(planner.setup, ["Artificer's Orb", "Kolr's Hunt"])
        self.assertEqual(planner.prices[crafter.NEW_BASE], 5 + 201)
        plain = crafter.Planner(page, 82, [crafter.make_want(page.ladders[1], None, 82)], self.PRICES)
        self.assertEqual((plain.setup, plain.setup_cost), ([], 0))
        plan = planner.solve(crafter.State("normal", (crafter.NONE,), 0, 0))
        self.assertEqual(plan.usage["Kolr's Hunt"] >= 1, True)
        self.assertGreater(plan.values[plan.start], 201)

    def test_the_plain_prices_are_kept_so_a_rune_is_never_counted_twice(self):
        page = self.page()
        planner = crafter.Planner(page, 82, [crafter.make_want(page.rune_ladders[0], 1, 82)], self.PRICES)
        self.assertEqual(planner.plain_prices[crafter.NEW_BASE], 5)
        again = crafter.Planner(page, 82, [crafter.make_want(page.rune_ladders[0], 1, 82)], planner.plain_prices)
        self.assertEqual(again.prices[crafter.NEW_BASE], 5 + 201)

    def test_a_rune_mod_can_be_rolled_in_the_plan(self):
        page = self.page()
        want = crafter.make_want(page.rune_ladders[0], 1, 82)
        planner = crafter.Planner(page, 82, [want], self.PRICES)
        self.assertGreater(planner.tables[0]["hit"][0], 0)

    def test_a_rune_without_a_price_stops_with_words(self):
        page = self.page()
        with self.assertRaises(ValueError):
            crafter.Planner(page, 82, [crafter.make_want(page.rune_ladders[0], 1, 82)], {key: value for key, value in self.PRICES.items() if key != "Kolr's Hunt"})

    def test_the_data_names_a_rune_for_each_group_and_keeps_a_usual_weight(self):
        raw = {"mods": [{"weight": 500}, {"weight": 1}, {"weight": 700}], "warped": {"marksman": [{"name": "Kolr's", "side": "prefix", "level": 45, "groups": ["M"], "text": "+1 x", "template": "+# x"}], "unknown": [{"name": "?"}]}}
        mods = crafter.warped_mods(raw)
        self.assertEqual([(mod.rune, mod.weight, mod.weight_known) for mod in mods], [("Kolr's Hunt", 600, False)])

    def test_a_mod_with_no_number_counts_when_it_is_the_same_mod(self):
        mod = crafter.Mod("Essence of the Abyss", "prefix", 1, ("Mark",), 0, True, "Mark of the Abyssal Lord", "Mark of the Abyssal Lord", only_from="Essence of the Abyss")
        essence = crafter.Essence("Essence of the Abyss", "prefix", 1, ("Mark",), "Mark of the Abyssal Lord", "", True)
        want = crafter.make_want(crafter.Ladder("prefix", "Mark of the Abyssal Lord", (mod,)), None, 82)
        self.assertEqual(crafter.perfect_essence_status(essence, want), crafter.HIT)

    def want_of(self, text, template):
        mod = crafter.Mod("x", "suffix", 1, (template,), 100, True, text, template)
        return crafter.make_want(crafter.Ladder("suffix", template, (mod,)), None, 82)

    def test_hints_after_the_craft(self):
        prices = {"Blazing Flux": 5, "Flesh Catalyst": 3, "Xoph's Catalyst": 2, "Armourer's Scrap": 1}
        fire = self.want_of("+(10-20)% to Fire Resistance", "+#% to Fire Resistance")
        life = self.want_of("+(60-70) to maximum Life", "+# to maximum Life")
        self.assertEqual(crafter.finishing_hints("Rings", [fire, life], prices), [("Blazing Flux", "flux"), ("Flesh Catalyst", "catalyst"), ("Xoph's Catalyst", "catalyst")])
        self.assertEqual(crafter.finishing_hints("Gloves_dex", [life], prices), [("Armourer's Scrap", "quality")])
        self.assertEqual(crafter.finishing_hints("Gloves_dex", [life], {}), [])

    def test_two_resistances_get_no_flux_because_it_would_merge_them(self):
        fire = self.want_of("+(10-20)% to Fire Resistance", "+#% to Fire Resistance")
        cold = self.want_of("+(10-20)% to Cold Resistance", "+#% to Cold Resistance")
        self.assertEqual(crafter.finishing_hints("Belts", [fire, cold], {"Blazing Flux": 5, "Chilling Flux": 5}), [])


class NamesTests(unittest.TestCase):
    def test_nothing_the_code_uses_is_left_undefined(self):
        """A missing import only shows when its line runs, which for a rarely pressed button may be in the player's hands."""
        import builtins
        import dis
        from pathlib import Path

        for module in (crafter, trade_search, crafter.sys.modules["tools"], crafter.sys.modules["price_check"]):
            code = compile(Path(module.__file__).read_text(encoding="utf-8"), module.__file__, "exec")
            pending, missing = [code], set()
            while pending:
                current = pending.pop()
                pending.extend(constant for constant in current.co_consts if hasattr(constant, "co_code"))
                missing.update(found.argval for found in dis.get_instructions(current) if found.opname in ("LOAD_GLOBAL", "LOAD_NAME") and not hasattr(module, found.argval) and not hasattr(builtins, found.argval))
            self.assertEqual(sorted(missing), [], module.__name__)


class ReadingItemTests(unittest.TestCase):
    def db(self) -> Database:
        raw = {"name": "x", "side": "prefix", "level": 1, "groups": ["g"], "weight": 1000, "text": "+(1-2) to a", "template": "+# to a"}
        dark = {"name": "Amanamu's", "side": "prefix", "level": 65, "groups": ["d"], "text": "+(1-2) to dark", "template": "+# to dark", "ru_name": "А", "ru_text": "+(1-2) к тьме"}
        return Database({"pages": {"Daggers": {"mods": [raw], "desecrated": [dark]}}, "bases": {"Dagger": {"page": "Daggers", "ru": "Кинжал"}}})

    TEXT = 'Item Class: Daggers\nRarity: Rare\nName\nDagger\n--------\nItem Level: 80\n--------\n{ Desecrated Prefix Modifier "Amanamu\'s" (Tier: 1) }\n+2(1-2) to dark\n'

    def test_a_database_gives_desecrated_mods_the_measured_weight(self):
        page = self.db().pages["Daggers"]
        self.assertEqual((page.desecrated[0].weight, page.desecrated[0].weight_known, page.desecrated[0].desecrated), (crafter.DESECRATED_WEIGHT, False, True))
        self.assertEqual(page.pool(82), page.mods)

    def test_an_old_data_file_still_loads(self):
        self.assertEqual(Database({"pages": {"Daggers": {"mods": []}}, "bases": {}}).pages["Daggers"].desecrated, [])

    def test_the_desecrated_mod_is_read_with_its_words(self):
        item = parse_item(self.TEXT, self.db())
        self.assertEqual(item.desecrated, ("prefix", "Amanamu's", "+2(1-2) to dark"))

    def test_also_in_russian_whatever_the_case_of_the_word(self):
        text = 'Класс предмета: Кинжалы\nРедкость: Редкий\nИмя\nКинжал\n--------\nУровень предмета: 80\n--------\n{ Очернённый префикс "А" (Уровень: 1) }\n+2(1-2) к тьме\n'
        for shown in (text, text.replace("префикс", "Префикс")):
            item = parse_item(shown, self.db())
            self.assertEqual(item.desecrated, ("prefix", "А", "+2(1-2) к тьме"))
            self.assertEqual(item.mods, [("prefix", "А")])

    def test_a_hidden_mod_must_be_revealed_first(self):
        with self.assertRaises(ValueError):
            parse_item(self.TEXT + "Unrevealed Desecrated Modifier\n", self.db())

    def test_poe2db_entries_keep_their_side_and_words(self):
        raw = [{"Name": "Amanamu's", "Level": "65", "ModGenerationTypeID": "2", "ModFamilyList": ["F"], "str": "<a href='x'>Attacks</a> deal (1<span>—</span>2)"}]
        found = normalize_desecrated(raw, [{**raw[0], "Name": "Амануму", "str": "Атаки (1—2)"}])
        self.assertEqual((found[0]["side"], found[0]["level"], found[0]["text"], found[0]["ru_name"], found[0]["ru_text"]), ("suffix", 65, "Attacks deal (1-2)", "Амануму", "Атаки (1-2)"))


class ForbiddenOrbTests(unittest.TestCase):
    def setUp(self):
        self.page = Page("Daggers", [regular(number) for number in range(3)] + [regular(number, "suffix") for number in range(3)])
        self.want = want_of(self.page, "+# to statprefix0")
        self.start = State("normal", (NONE,), 0, 0)

    def test_a_forbidden_orb_is_not_used(self):
        prices = {name: value for name, value in PRICES.items() if name != "Exalted Orb"}
        plan = Planner(self.page, 82, [self.want], prices).solve(self.start)
        self.assertNotIn("Exalted Orb", plan.usage)
        self.assertGreater(plan.values[self.start], 0)

    def test_forbidding_something_never_makes_the_plan_cheaper(self):
        free = Planner(self.page, 82, [self.want], PRICES).solve(self.start).values[self.start]
        limited = Planner(self.page, 82, [self.want], {name: value for name, value in PRICES.items() if name != "Orb of Transmutation"}).solve(self.start).values[self.start]
        self.assertGreaterEqual(limited, free - 1e-6)

    def test_a_goal_that_cannot_be_reached_says_so(self):
        with self.assertRaises(ValueError):
            Planner(self.page, 82, [self.want], {"Divine Orb": 100.0}).solve(self.start)

    def test_a_way_that_risks_getting_stuck_is_not_taken(self):
        # Nothing can remove a mod and no new base is allowed, so one wrong roll would end the craft for good.
        prices = {"Orb of Transmutation": 1.0, "Orb of Augmentation": 1.0, "Regal Orb": 1.0, "Exalted Orb": 1.0, "Divine Orb": 100.0}
        with self.assertRaises(ValueError):
            Planner(self.page, 82, [self.want], prices).solve(self.start)

    def test_a_new_base_rescues_that_goal(self):
        prices = {"Orb of Transmutation": 1.0, "Orb of Augmentation": 1.0, "Regal Orb": 1.0, "Exalted Orb": 1.0, "Divine Orb": 100.0, crafter.NEW_BASE: 1.0}
        plan = Planner(self.page, 82, [self.want], prices).solve(self.start)
        self.assertLess(plan.values[self.start], 100)


def simulated(costs: list[float]) -> Simulation:
    ordered = sorted(costs)
    return Simulation(len(ordered), sum(ordered) / len(ordered), ordered[len(ordered) // 2], ordered[int(len(ordered) * 0.9)], ordered[int(len(ordered) * 0.99)], tuple(ordered))


class FakePlan:
    def __init__(self, simulation, value: float = 100.0):
        self.simulation, self.start, self.values = simulation, "start", {"start": value}


class BudgetTests(unittest.TestCase):
    def test_the_chance_is_the_share_of_runs_that_fit(self):
        result = simulated([10, 20, 30, 40])
        self.assertEqual([result.chance_within(budget) for budget in (5, 10, 25, 40, 99)], [0, 0.25, 0.5, 1, 1])

    def test_a_plan_is_safer_only_when_bad_luck_costs_clearly_less(self):
        safe, wild = simulated([50] * 100), simulated([10] * 80 + [100] * 20)
        self.assertEqual(surer_mode({"budget": FakePlan(wild), "endgame": FakePlan(safe)}), "endgame")
        self.assertIsNone(surer_mode({"budget": FakePlan(simulated([50] * 100)), "endgame": FakePlan(simulated([49] * 100))}))

    def test_no_comparison_until_both_are_tested(self):
        self.assertIsNone(surer_mode({"budget": FakePlan("running"), "endgame": FakePlan(simulated([1] * 100))}))
        self.assertIsNone(surer_mode({"budget": FakePlan(False), "endgame": FakePlan(simulated([1] * 100))}))

    def test_advice_names_the_better_mode_and_a_goal_that_fits(self):
        plans = {"budget": FakePlan(simulated([100] * 100), 100), "endgame": FakePlan(simulated([10] * 100), 10)}
        options = [{"label": "dear", "cost": 80}, {"label": "fits", "cost": 40}]
        self.assertEqual(budget_advice(plans, "budget", 50, options), (0, "endgame", "fits"))

    def test_no_simpler_goal_when_the_plan_already_fits(self):
        plans = {"budget": FakePlan(simulated([10] * 100), 10)}
        self.assertEqual(budget_advice(plans, "budget", 50, [{"label": "fits", "cost": 5}]), (1, None, None))

    def test_no_advice_while_the_plan_is_being_tested(self):
        self.assertEqual(budget_advice({"budget": FakePlan("running")}, "budget", 50, None), (None, None, None))


INDEX = {
    "pseudo": {"всего #% сопротивления стихиям": ["pseudo.pseudo_total_elemental_resistance"], "всего #% сопротивления": ["pseudo.pseudo_total_resistance"], "всего # к максимуму здоровья": ["pseudo.pseudo_total_life"], "# итого к характеристикам": ["pseudo.pseudo_total_attributes"]},
    "explicit": {"#% к сопротивлению огню": ["explicit.stat_3372524247"], "#% к сопротивлению холоду": ["explicit.stat_4220027924"], "#% к сопротивлению всем стихиям": ["explicit.stat_2901986750"], "#% к сопротивлениям огню и хаосу": ["explicit.stat_378817135"],
                 "#% к сопротивлению хаосу": ["explicit.stat_2923486259"], "# к максимуму здоровья": ["explicit.stat_3299347043"], "# к силе": ["explicit.stat_4080418644"], "#% увеличение урона": ["explicit.stat_1"]},
    "implicit": {"# к максимуму здоровья": ["implicit.stat_3299347043"], "#% к сопротивлению огню": ["implicit.stat_3372524247"]},
}


def block(head: str, line: str) -> str:
    return "{ " + head + " }\n" + line + "\n"


class TotalsTests(unittest.TestCase):
    def totals(self, *blocks: str) -> dict:
        return {mod.stats[0].ids[0].removeprefix("pseudo.pseudo_"): mod.stats[0].value for mod in read_item_totals("".join(blocks), INDEX)}

    def test_two_resistances_make_a_total(self):
        found = self.totals(block('Суффикс "А" (Уровень: 2)', "+30(26-30)% к сопротивлению огню"), block('Суффикс "Б" (Уровень: 3)', "+20(16-20)% к сопротивлению холоду"))
        self.assertEqual(found, {"total_elemental_resistance": 50})

    def test_one_mod_alone_needs_no_total(self):
        self.assertEqual(self.totals(block('Суффикс "А"', "+30% к сопротивлению огню")), {})

    def test_a_mod_for_every_element_counts_three_times(self):
        found = self.totals(block('Суффикс "А"', "+10% к сопротивлению всем стихиям"))
        self.assertEqual(found, {"total_elemental_resistance": 30})

    def test_chaos_goes_only_into_the_wider_total(self):
        found = self.totals(block('Суффикс "А"', "+10% к сопротивлениям огню и хаосу"), block('Суффикс "Б"', "+20% к сопротивлению холоду"))
        self.assertEqual(found, {"total_resistance": 40, "total_elemental_resistance": 30})

    def test_chaos_alone_makes_no_total(self):
        self.assertEqual(self.totals(block('Суффикс "А"', "+10% к сопротивлению хаосу")), {})

    def test_implicit_mods_count_as_on_the_site(self):
        found = self.totals(block("Собственное", "+20(10-20) к максимуму здоровья"), block('Префикс "А"', "+50(40-50) к максимуму здоровья"))
        self.assertEqual(found, {"total_life": 70})

    def test_unknown_lines_change_nothing(self):
        self.assertEqual(self.totals(block('Префикс "А"', "+50% увеличение урона"), block('Префикс "Б"', "Нечто новое 12")), {})

    def test_the_label_shows_the_total(self):
        mods = read_item_totals(block('Суффикс "А"', "+10% к сопротивлению всем стихиям"), INDEX)
        self.assertEqual(mods[0].label, "Всего 30% сопротивления стихиям")
        self.assertEqual(mods[0].covers, ("fire", "cold", "lightning"))

    def test_no_totals_when_the_site_lists_none(self):
        self.assertEqual(read_item_totals(block('Суффикс "А"', "+10% к сопротивлению всем стихиям"), {"explicit": INDEX["explicit"]}), [])

    def test_a_total_starts_on_and_the_mods_inside_it_start_off(self):
        fire = ItemMod("+30% огонь", 1, (StatFilter(("explicit.stat_3372524247",), 30.0),))
        damage = ItemMod("+50% урон", 1, (StatFilter(("explicit.stat_1",), 50.0),))
        total = ItemMod("Всего 50%", None, (StatFilter(("pseudo.pseudo_total_elemental_resistance",), 50.0),), ("fire", "cold", "lightning"))
        self.assertEqual(mods_on_by_default([total, fire, damage], False), [total, damage])

    def test_of_two_totals_only_the_wider_starts_on(self):
        wide = ItemMod("Всего 40%", None, (StatFilter(("pseudo.pseudo_total_resistance",), 40.0),), ("fire", "cold", "chaos"))
        narrow = ItemMod("Всего 30%", None, (StatFilter(("pseudo.pseudo_total_elemental_resistance",), 30.0),), ("fire", "cold"))
        self.assertEqual(mods_on_by_default([wide, narrow], False), [wide])

    def test_a_unique_still_starts_with_nothing(self):
        self.assertEqual(mods_on_by_default([ItemMod("Всего", None, (StatFilter(("pseudo.x",), 1.0),), ("fire",))], True), [])

    def test_a_total_searches_for_at_least_that_sum(self):
        total = ItemMod("Всего 50%", None, (StatFilter(("pseudo.pseudo_total_elemental_resistance",), 50.0),), ("fire", "cold"))
        self.assertEqual(build_query(None, "Кольцо", False, [total], 0.9)["query"]["stats"][0]["filters"], [{"id": "pseudo.pseudo_total_elemental_resistance", "value": {"min": 45}}])


class SearchMemoryTests(unittest.TestCase):
    FIRE = ItemMod("огонь", 1, (StatFilter(("explicit.stat_1",), 30.0),))
    COLD = ItemMod("холод", 1, (StatFilter(("explicit.stat_2",), 30.0),))
    FRACTURED_FIRE = ItemMod("огонь", 1, (StatFilter(("fractured.stat_1",), 30.0),))
    TOTAL = ItemMod("всего", None, (StatFilter(("pseudo.total",), 60.0),), ("fire",))

    def test_rares_are_remembered_by_kind_and_uniques_by_name(self):
        self.assertEqual(search_memory_key("Класс предмета: Шлемы\nРедкость: Редкий", "Гибельный венец", False), "Класс предмета: Шлемы")
        self.assertEqual(search_memory_key("Класс предмета: Шлемы\nРедкость: Уникальный", "Корона", True), "unique:Корона")

    def test_the_choice_comes_back_on_the_next_item_of_that_kind(self):
        memory = remember_search({}, "шлем", [self.FIRE, self.TOTAL], 0.8)
        self.assertEqual(memory["шлем"]["strictness"], 0.8)
        self.assertEqual(recalled_mods(memory["шлем"], [self.TOTAL, self.FIRE, self.COLD]), [self.TOTAL, self.FIRE])

    def test_the_same_stat_counts_whichever_kind_of_mod_carries_it(self):
        memory = remember_search({}, "шлем", [self.FIRE], 0.9)
        self.assertEqual(recalled_mods(memory["шлем"], [self.FRACTURED_FIRE]), [self.FRACTURED_FIRE])

    def test_nothing_comes_back_when_the_item_has_none_of_it(self):
        memory = remember_search({}, "шлем", [self.FIRE], 0.9)
        self.assertEqual(recalled_mods(memory["шлем"], [self.COLD]), [])
        self.assertEqual(recalled_mods(None, [self.COLD]), [])

    def test_a_mod_the_site_does_not_know_is_never_recalled(self):
        memory = remember_search({}, "шлем", [self.FIRE], 0.9)
        self.assertEqual(recalled_mods(memory["шлем"], [ItemMod("странный", None, ())]), [])

    def test_a_new_search_replaces_the_old_one(self):
        memory = remember_search(remember_search({}, "шлем", [self.FIRE], 0.9), "шлем", [self.COLD], 1.0)
        self.assertEqual(memory["шлем"], {"stats": ["2"], "strictness": 1.0})

    def test_the_oldest_kinds_are_forgotten(self):
        memory = {}
        for number in range(trade_search.SEARCHES_REMEMBERED + 5):
            memory = remember_search(memory, str(number), [self.FIRE], 0.9)
        self.assertEqual(len(memory), trade_search.SEARCHES_REMEMBERED)
        self.assertNotIn("0", memory)
        self.assertIn(str(trade_search.SEARCHES_REMEMBERED + 4), memory)


if __name__ == "__main__":
    unittest.main()
