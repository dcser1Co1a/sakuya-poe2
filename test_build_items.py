import base64
import re
import unittest
import zlib
from pathlib import Path

import build_items
import crafter
import price_check
import trade_search
from build_items import BuildCodeError, ShownMod, decode_build_code, explicit_mods, game_text, parse_pob_item, read_build

# Items as Path of Building 2 keeps them: an imported character has its own numbers, a unique from its list keeps ranges and the roll apart.
RING = """Rarity: RARE
Rune Spiral
Gold Ring
Unique ID: bad7ae6d
Item Level: 80
LevelReq: 60
Implicits: 1
7% increased Rarity of Items found
30% increased Lightning Damage
+108 to maximum Life
17% increased Rarity of Items found
21% increased Cast Speed
+18% to Chaos Resistance
17% increased Rarity of Items found"""
UNIQUE = """Rarity: UNIQUE
Soul Tether
Long Belt
Variant: Old
Variant: New
Selected Variant: 2
Item Level: 84
Implicits: 1
{tags:life}+(20-30) to maximum Life
{range:0.5}+(40-60) to maximum Energy Shield
{variant:1}Old wording
{variant:2}{range:1}+(10-20) to Intelligence
Leech Life 19% faster
Corrupted"""
STAFF = """Rarity: RARE
Tempest Pile
Ashen Staff
Item Level: 82
Quality: 20
Sockets: S S
Rune: Perfect Vision Rune
Implicits: 2
{enchant}{rune}+1 to Level of all Spell Skills
Grants Skill: Level 19 Firebolt
{fractured}+6 to Level of all Spell Skills
Gain 54% of Damage as Extra Fire Damage"""


def code_of(xml: str) -> str:
    return base64.urlsafe_b64encode(zlib.compress(xml.encode("utf-8"))).decode("ascii")


def build_xml(items: dict[str, str], slots: dict[str, str], root: str = "PathOfBuilding2") -> str:
    from xml.sax.saxutils import escape
    item_nodes = "".join(f'<Item id="{key}">{escape(text)}</Item>' for key, text in items.items())
    slot_nodes = "".join(f'<Slot name="{name}" itemId="{key}"/>' for name, key in slots.items())
    return (f'<?xml version="1.0" encoding="UTF-8"?><{root}><Build level="94" className="Witch" ascendClassName="Blood Mage"/>'
            f'<Items activeItemSet="2"><ItemSet id="1"><Slot name="Helmet" itemId="1"/></ItemSet><ItemSet id="2">{slot_nodes}</ItemSet>{item_nodes}</Items></{root}>')


class FakeMod:
    def __init__(self, name, text, ru_text="", desecrated=False):
        self.name, self.text, self.ru_text, self.desecrated = name, text, ru_text, desecrated


class FakeLadder:
    def __init__(self, side, mods):
        self.side, self.mods = side, tuple(mods)
        self.template = build_items.make_template(mods[0].text)


class FakePage:
    def __init__(self, ladders, desecrated=()):
        self.ladders, self.desecrated_ladders = ladders, list(desecrated)


RINGS = FakePage([
    FakeLadder("prefix", [FakeMod("Virile", "+(100-119) to maximum Life", "+(100-119) к максимуму здоровья"), FakeMod("Vigorous", "+(85-99) to maximum Life")]),
    FakeLadder("prefix", [FakeMod("Smiting", "(27-30)% increased Lightning Damage")]),
    FakeLadder("prefix", [FakeMod("Hoarder's", "(16-19)% increased Rarity of Items found")]),
    FakeLadder("suffix", [FakeMod("of Archaeology", "(15-18)% increased Rarity of Items found")]),
    FakeLadder("suffix", [FakeMod("of Sortilege", "(19-21)% increased Cast Speed")]),
    FakeLadder("suffix", [FakeMod("of Expulsion", "+(16-19)% to Chaos Resistance")]),
    FakeLadder("suffix", [FakeMod("of Light", "(8-12)% increased Mana Regeneration Rate / 5% increased Light Radius")]),
])


class CodeTests(unittest.TestCase):
    def test_a_code_opens_the_active_item_set(self):
        build = read_build(decode_build_code(code_of(build_xml({"1": RING, "2": UNIQUE}, {"Ring 1": "1", "Belt": "2", "Ring 2": "0", "Arm 1": "1"}))))
        self.assertEqual((build.level, build.class_name, build.ascendancy), (94, "Witch", "Blood Mage"))
        self.assertEqual(set(build.slots), {"Ring 1", "Belt"})  # an empty slot and a tree socket are no equipment
        self.assertEqual(build.slots["Ring 1"].name, "Rune Spiral")

    def test_the_code_may_come_with_spaces_and_the_other_base64_letters(self):
        code = code_of(build_xml({"1": RING}, {"Ring 1": "1"}))
        spaced = " ".join(code[index:index + 40] for index in range(0, len(code), 40)).replace("-", "+").replace("_", "/")
        self.assertIn("Ring 1", read_build(decode_build_code("\n" + spaced + "\n")).slots)

    def test_links_and_rubbish_are_refused_in_plain_words(self):
        for link in ("https://pobb.in/abc", "pobb.in/abc", "https://poe.ninja/poe2/pob/abc", "poe2.ninja/pob/x", "www.example.com"):
            with self.assertRaisesRegex(BuildCodeError, "ссылка"):
                decode_build_code(link)
        for odd in ("", "   ", "not a code at all!", base64.urlsafe_b64encode(b"plain").decode(), code_of("<html>")[:-8]):
            with self.assertRaises(BuildCodeError):
                read_build(decode_build_code(odd))
        with self.assertRaisesRegex(BuildCodeError, "первой части"):
            read_build(decode_build_code(code_of(build_xml({"1": RING}, {"Ring 1": "1"}, root="PathOfBuilding"))))

    def test_a_bomb_or_entities_are_refused(self):
        with self.assertRaises(BuildCodeError):
            decode_build_code(base64.urlsafe_b64encode(zlib.compress(b"<" * (build_items.LARGEST_BUILD + 10))).decode())
        with self.assertRaises(BuildCodeError):
            decode_build_code(code_of('<!DOCTYPE x [<!ENTITY a "aaaa">]><PathOfBuilding2>&a;</PathOfBuilding2>'))

    def test_jewels_come_from_the_active_tree(self):
        jewel = "Rarity: RARE\nDragon Shine\nSapphire\nItem Level: 81\nImplicits: 0\n15% increased Spell Damage"
        unique = "Rarity: UNIQUE\nFlesh Crucible\nDiamond\nItem Level: 82\nLimited to: 1\nImplicits: 0\nBlood Magic\nCorrupted"
        tree = ('<Tree activeSpec="2"><Spec><Sockets><Socket nodeId="1" itemId="3"/></Sockets></Spec>'
                '<Spec><Sockets><Socket nodeId="61834" itemId="3"/><Socket nodeId="21984" itemId="4"/><Socket nodeId="500" itemId="0"/><Socket nodeId="9" itemId="77"/></Sockets></Spec></Tree>')
        xml = build_xml({"1": RING, "3": jewel, "4": unique}, {"Ring 1": "1"}).replace("</PathOfBuilding2>", tree + "</PathOfBuilding2>")
        build = read_build(decode_build_code(code_of(xml)))
        self.assertEqual([(socket, item.name) for socket, item in build.jewels], [("61834", "Dragon Shine"), ("21984", "Flesh Crucible")])
        self.assertIn("corrupted", build.jewels[1][1].flags)

    def test_jewels_take_the_free_columns_first_then_rows(self):
        places = build_items.jewel_places(20)
        self.assertEqual(len(set(places)), 20)
        self.assertTrue(all(top < build_items.GRID_HEIGHT for _, top, _, _ in places[:16]))
        self.assertTrue(all(top > build_items.GRID_HEIGHT for _, top, _, _ in places[16:]))
        for left, top, width, height in places[:16]:  # none sits on a piece of gear
            for gear_left, gear_top, gear_width, gear_height in build_items.SLOT_PLACES.values():
                self.assertFalse(left < gear_left + gear_width and gear_left < left + width and top < gear_top + gear_height and gear_top < top + height)

    def test_the_character_name_comes_from_the_export_link_without_the_account(self):
        link = '<Import exportParty="false" importLink="https://poe.ninja/poe2/pob/raw/profile/code/Some-1234/forbiddenrites/RaorasFootArc"/>'
        xml = build_xml({"1": RING}, {"Ring 1": "1"}).replace("</PathOfBuilding2>", link + "</PathOfBuilding2>")
        build = read_build(decode_build_code(code_of(xml)))
        self.assertEqual(build.character, "RaorasFootArc")
        self.assertEqual(read_build(decode_build_code(code_of(build_xml({"1": RING}, {"Ring 1": "1"})))).character, "")  # a code made in Path of Building itself

    def test_a_newer_code_of_the_same_character_updates_its_entry_and_its_page_opens_once_an_hour(self):
        def exported(name, level, account="Some-1234"):
            link = f'<Import exportParty="false" importLink="https://poe.ninja/poe2/pob/raw/profile/code/{account}/forbiddenrites/{name}"/>'
            xml = build_xml({"1": RING}, {"Ring 1": "1"}).replace('level="94"', f'level="{level}"').replace("</PathOfBuilding2>", link + "</PathOfBuilding2>")
            return code_of(xml)
        old_code, new_code = exported("RaorasFootArc", 90), exported("RaorasFootArc", 94)
        build = read_build(decode_build_code(old_code))
        self.assertEqual(build.page, "https://poe.ninja/poe2/profile/Some-1234/character/RaorasFootArc")  # the character's own page, never their Path of Building address
        self.assertNotIn("/pob/", build.page)
        self.assertEqual(build_items.character_page("https://evil.example/poe2/pob/raw/profile/code/a/b/c"), "")
        self.assertEqual(build_items.character_page("https://poe.ninja/poe2/pob/raw/profile/code/A%20B/league/C%2FD"), "https://poe.ninja/poe2/profile/A%20B/character/C%2FD")
        self.assertEqual(read_build(decode_build_code(code_of(build_xml({"1": RING}, {"Ring 1": "1"})))).page, "")  # a code from Path of Building itself
        other = read_build(decode_build_code(exported("SomeoneElse", 50)))
        history = build_items.add_to_history([], old_code, build, "2026-11-10T20:00:00")
        history = build_items.add_to_history(history, exported("SomeoneElse", 50), other, "2026-11-10T20:01:00")
        history = build_items.marked_refreshed(history, "".join(old_code.split()), "2026-11-10T20:02:00")
        history = build_items.add_to_history(history, new_code, read_build(decode_build_code(new_code)), "2026-11-10T20:30:00")
        self.assertEqual([(entry["name"], entry["level"]) for entry in history], [("RaorasFootArc", 94), ("SomeoneElse", 50)])  # one entry each, the newer code in its place
        self.assertEqual(history[0]["refreshed_at"], "2026-11-10T20:02:00")  # the hour goes on with the newer code
        self.assertEqual(build_items.refresh_wait(history[0], "2026-11-10T20:32:00"), 1800)
        self.assertEqual(build_items.refresh_wait(history[0], "2026-11-10T21:02:00"), 0)
        self.assertEqual(build_items.refresh_wait(history[1], "2026-11-10T20:32:00"), 0)  # never opened
        self.assertEqual(build_items.refresh_wait({"refreshed_at": "2026-11-11T09:00:00"}, "2026-11-10T20:32:00"), 0)  # a clock put back does not lock the button
        import shapes
        self.assertEqual(shapes.clean_build_history(history)[0]["refreshed_at"], "2026-11-10T20:02:00")
        self.assertNotIn("refreshed_at", shapes.clean_build_history([{**history[0], "refreshed_at": "soon"}])[0])

    def test_the_history_keeps_the_newest_first_once_each(self):
        build = read_build(decode_build_code(code_of(build_xml({"1": RING}, {"Ring 1": "1"}))))
        history = build_items.add_to_history([], "code one", build, "2026-11-08T18:00:00")
        history = build_items.add_to_history(history, "code two", build, "2026-11-08T18:01:00")
        history = build_items.add_to_history(history, "code one", build, "2026-11-08T18:02:00")
        self.assertEqual([entry["code"] for entry in history], ["codeone", "codetwo"])
        self.assertEqual(build_items.history_label(history[0], lambda text: text), "Witch · Blood Mage · уровень 94")
        for number in range(40):
            history = build_items.add_to_history(history, f"code {number}", build, "2026-11-08T18:03:00")
        self.assertEqual(len(history), build_items.HISTORY_SIZE)
        top = history[0]["code"]
        named = build_items.renamed(history, top, "  Sakura Witch  ")
        self.assertEqual(named[0]["name"], "Sakura Witch")
        self.assertEqual([entry["name"] for entry in named[1:]], [entry["name"] for entry in history[1:]])  # only that build is renamed
        self.assertEqual(build_items.add_to_history(named, top, build, "2026-11-08T19:00:00")[0]["name"], "Sakura Witch")  # opening it again keeps the name the player gave
        self.assertEqual(len(build_items.renamed(history, top, "x" * 99)[0]["name"]), build_items.NICK_LENGTH)
        import shapes
        self.assertEqual(shapes.clean_build_history(history), history)
        self.assertEqual(shapes.clean_build_history([{"code": ""}, {"code": 5}, "x", {"code": "ok", "level": "high", "name": 7}]),
                         [{"code": "ok", "name": "", "class_name": "", "ascendancy": "", "level": None, "saved_at": ""}])
        self.assertEqual(shapes.clean_build_history({"not": "a list"}), [])

    def test_an_odd_item_costs_only_itself(self):
        build = read_build(decode_build_code(code_of(build_xml({"1": "nonsense", "2": RING}, {"Helmet": "1", "Ring 1": "2"}))))
        self.assertEqual(set(build.slots), {"Ring 1"})


class ItemTests(unittest.TestCase):
    def test_the_level_an_item_needs(self):
        self.assertEqual(parse_pob_item(RING).level_req, 60)
        self.assertIsNone(parse_pob_item(UNIQUE).level_req)  # Path of Building writes none for it

    def test_implicits_explicits_and_flags(self):
        item = parse_pob_item(RING)
        self.assertEqual((item.rarity, item.name, item.base_line, item.item_level), ("Rare", "Rune Spiral", "Gold Ring", 80))
        self.assertEqual([line.kind for line in item.lines], ["implicit"] + ["explicit"] * 6)

    def test_a_unique_keeps_its_variant_and_rolls(self):
        item = parse_pob_item(UNIQUE)
        self.assertEqual([line.text for line in item.lines], ["+25 to maximum Life", "+50 to maximum Energy Shield", "+20 to Intelligence", "Leech Life 19% faster"])
        self.assertIn("corrupted", item.flags)

    def test_runes_enchants_and_fractured_lines(self):
        item = parse_pob_item(STAFF)
        self.assertEqual([(line.kind, line.text) for line in item.lines][:2], [("rune", "+1 to Level of all Spell Skills"), ("implicit", "Grants Skill: Level 19 Firebolt")])
        self.assertEqual(item.fractured, frozenset({"+6 to Level of all Spell Skills"}))
        self.assertEqual(item.quality, 20)

    def test_a_magic_item_has_one_name_line(self):
        item = parse_pob_item("Rarity: MAGIC\nPotent Ultimate Life Flask of the Foliage\nItem Level: 81\nImplicits: 0\n73% increased Amount Recovered")
        self.assertEqual((item.rarity, item.name, item.base_line), ("Magic", "Potent Ultimate Life Flask of the Foliage", "Potent Ultimate Life Flask of the Foliage"))


class TierTests(unittest.TestCase):
    def test_mods_get_their_side_tier_and_rolls(self):
        mods = explicit_mods(parse_pob_item(RING), RINGS, {"prefix": 3, "suffix": 3})
        self.assertEqual([(mod.kind, mod.tier, mod.name) for mod in mods], [("prefix", 1, "Smiting"), ("prefix", 1, "Virile"), ("prefix", 1, "Hoarder's"),
                                                                            ("suffix", 1, "of Sortilege"), ("suffix", 1, "of Expulsion"), ("suffix", 1, "of Archaeology")])
        self.assertEqual(mods[1].text, "+108(100-119) to maximum Life")
        self.assertEqual(mods[1].shown_text, "+108 к максимуму здоровья")

    def test_the_same_wording_goes_where_there_is_room_and_once_per_mod(self):
        mods = explicit_mods(parse_pob_item(RING), RINGS, {"prefix": 2, "suffix": 4})  # a base with room for two prefixes only
        self.assertEqual(sum(mod.kind == "prefix" for mod in mods), 2)
        self.assertEqual(sum(mod.kind == "unknown" for mod in mods), 1)  # the second rarity line cannot be of Archaeology again
        self.assertEqual(sum(mod.name == "of Archaeology" for mod in mods), 1)

    def test_a_value_past_every_tier_or_an_unknown_line_has_no_tier(self):
        item = parse_pob_item("Rarity: RARE\nA\nGold Ring\nItem Level: 80\nImplicits: 0\n+150 to maximum Life\nSomething new")
        self.assertEqual([(mod.kind, mod.tier) for mod in explicit_mods(item, RINGS, {"prefix": 3, "suffix": 3})], [("unknown", None), ("unknown", None)])

    def test_a_hybrid_mod_takes_both_its_lines(self):
        item = parse_pob_item("Rarity: RARE\nA\nGold Ring\nItem Level: 80\nImplicits: 0\n10% increased Mana Regeneration Rate\n5% increased Light Radius")
        mods = explicit_mods(item, RINGS, {"prefix": 3, "suffix": 3})
        self.assertEqual([(mod.kind, mod.name, mod.text) for mod in mods], [("suffix", "of Light", "10(8-12)% increased Mana Regeneration Rate"), ("suffix", "of Light", "5% increased Light Radius")])

    def test_uniques_and_unknown_bases_are_shown_as_they_are(self):
        self.assertEqual({mod.kind for mod in explicit_mods(parse_pob_item(UNIQUE), RINGS, {"prefix": 3, "suffix": 3})}, {"unique"})
        self.assertEqual({mod.kind for mod in explicit_mods(parse_pob_item(RING), None, {"prefix": 3, "suffix": 3})}, {"unknown"})


class GameTextTests(unittest.TestCase):
    """The item written as the game copies it is read by the price window, the trade link and the planner alike."""

    def test_the_planner_and_the_price_window_read_it(self):
        item = parse_pob_item(RING)
        text = game_text(item, "Ring", explicit_mods(item, RINGS, {"prefix": 3, "suffix": 3}))
        copied = price_check.read_copied_item(text)
        self.assertEqual((copied.rarity, copied.lines), ("Rare", ("Rune Spiral", "Gold Ring")))
        self.assertIn('{ Prefix Modifier "Virile" (Tier: 1) }\n+108(100-119) to maximum Life', text)
        self.assertIn("{ Implicit Modifier }\n7% increased Rarity of Items found (implicit)", text)
        self.assertEqual([mod.tier for mod in trade_search.read_item_mods(text, {})], [1] * 6)
        database = crafter.Database({"pages": {"Rings": {"mods": []}}, "bases": {"Gold Ring": {"item_class": "Ring", "page": "Rings"}}})
        parsed = crafter.parse_item(text, database)
        self.assertEqual(parsed.mods[:2], [("prefix", "Smiting"), ("prefix", "Virile")])
        self.assertEqual((parsed.base, parsed.ilvl, parsed.rarity), ("Gold Ring", 80, "rare"))

    def test_fractured_and_corrupted_are_written_as_the_game_writes_them(self):
        item = parse_pob_item(UNIQUE)
        text = game_text(item, "Belt", [ShownMod("prefix", "+50(40-60) to maximum Life", 2, "Stout", "fractured")])
        self.assertIn('{ Fractured Prefix Modifier "Stout" (Tier: 2) }', text)
        self.assertTrue(text.rstrip().endswith("Corrupted"))


class OtherBaseTests(unittest.TestCase):
    def test_jewel_flask_and_charm_bases_get_their_russian_names_looked_up(self):
        art = {"Sapphire": "Art/2DItems/Jewels/SapphireJewel", "Ultimate Life Flask": "Art/2DItems/Flasks/Basetypes/FlaskLife09", "Golden Charm": "Art/2DItems/Charms/Basetypes/GoldenCharm",
               "Olroth's Resolve": "Art/2DItems/Flasks/Uniques/OlrothsResolve", "Chaos Orb": "Art/2DItems/Currency/CurrencyRerollRare"}
        self.assertEqual(crafter.other_bases(art), ["Golden Charm", "Sapphire", "Ultimate Life Flask"])
        self.assertEqual(crafter.names_to_look_up([*{"Chaos Orb": 1}, *crafter.other_bases(art)], {"chaos orb": "Сфера хаоса"}, {}), ["Golden Charm", "Sapphire", "Ultimate Life Flask"])


class TranslationTests(unittest.TestCase):
    def test_every_russian_text_has_an_english_version(self):
        source = Path(build_items.__file__).read_text(encoding="utf-8")
        texts = set(re.findall(r'"([^"\n]*[А-Яа-яЁё][^"\n]*)"', source))
        self.assertGreater(len(texts), 20)
        self.assertEqual(sorted(text for text in texts if text not in crafter.ENGLISH), [])


if __name__ == "__main__":
    unittest.main()
