"""Tests of the watcher that opens Sakuya with Path of Exile 2 (game_watch.py). Nothing here touches the real Run key or starts a program."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import game_watch

POE2 = r"C:\Program Files (x86)\Steam\steamapps\common\Path of Exile 2\PathOfExileSteam.exe"
POE1 = r"C:\Program Files (x86)\Steam\steamapps\common\Path of Exile\PathOfExileSteam.exe"


class GameTests(unittest.TestCase):
    def test_the_second_game_is_told_from_the_first_by_its_folder(self):
        self.assertTrue(game_watch.game_is_running([(10, 1, "PathOfExileSteam.exe")], {10: POE2}.get))
        self.assertFalse(game_watch.game_is_running([(10, 1, "PathOfExileSteam.exe")], {10: POE1}.get))
        self.assertTrue(game_watch.game_is_running([(10, 1, "PathOfExile_x64.exe")], lambda _: None))  # Windows would not say where: the name is enough
        self.assertFalse(game_watch.game_is_running([(10, 1, "explorer.exe"), (11, 1, "PathOfExile.log")], lambda _: POE2))

    def test_the_watcher_is_not_the_program(self):
        processes = [(5, 4, "Sakuya.exe"), (4, 1, "Sakuya.exe"), (9, 1, "notepad.exe")]
        self.assertFalse(game_watch.app_is_running(processes, "Sakuya.exe", {4, 5}))
        self.assertTrue(game_watch.app_is_running([*processes, (20, 5, "sakuya.EXE")], "Sakuya.exe", {4, 5}))


class WatchTests(unittest.TestCase):
    def watched(self, frames, app_open=()):
        """frames: whether the game runs at each look; app_open: the looks at which Sakuya is already open. Returns the looks that opened it."""
        opened, look = [], [0]

        def processes_now():
            number = look[0]
            look[0] += 1
            game = [(10, 1, "PathOfExile.exe")] if frames[number] else []
            app = [(30, 1, "Sakuya.exe")] if number in app_open else []
            return [(4, 1, "Sakuya.exe"), *game, *app]

        with mock.patch.object(game_watch, "process_path", return_value=POE2):
            game_watch.watch(Path("Sakuya.exe"), {4}, sleep=lambda _: None, processes_now=processes_now, still_wanted=lambda: True,
                             start=lambda _: opened.append(look[0] - 1), rounds=len(frames))
        return opened

    def test_it_opens_once_each_time_the_game_starts(self):
        self.assertEqual(self.watched([False, True, True, True, False, False, True]), [1, 6])

    def test_a_game_running_when_it_starts_is_not_a_start(self):
        self.assertEqual(self.watched([True, True, False, True]), [3])

    def test_an_open_program_is_not_opened_again(self):
        self.assertEqual(self.watched([False, True], app_open={1}), [])

    def test_it_ends_when_the_setting_is_off(self):
        wanted = iter([True, False])
        looks = []
        game_watch.watch(Path("Sakuya.exe"), set(), sleep=lambda _: None, processes_now=lambda: looks.append(1) or [], still_wanted=lambda: next(wanted))
        self.assertEqual(len(looks), 1)


class FileTests(unittest.TestCase):
    def test_the_run_key_command_and_the_watcher_file(self):
        exe = Path(r"C:\Games\Sakuya\Sakuya.exe")
        self.assertEqual(game_watch.run_command(exe), '"C:\\Games\\Sakuya\\Sakuya.exe" --watch-game')
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / "Sakuya.exe"
            self.assertEqual(game_watch.watcher_pids(exe, []), set())  # no file
            game_watch.pid_file(exe).write_text(json.dumps({"pids": [4, 5]}), encoding="utf-8")
            self.assertEqual(game_watch.watcher_pids(exe, [(4, 1, "Sakuya.exe"), (5, 4, "notepad.exe")]), {4})  # only those still running under this name
            game_watch.pid_file(exe).write_text("junk", encoding="utf-8")
            self.assertEqual(game_watch.watcher_pids(exe, [(4, 1, "Sakuya.exe")]), set())

    def test_it_is_registered_only_for_this_exe(self):
        exe = Path(r"C:\Games\Sakuya\Sakuya.exe")
        with mock.patch.object(game_watch, "registered_command", return_value=game_watch.run_command(exe)):
            self.assertTrue(game_watch.is_registered(exe))
            self.assertFalse(game_watch.is_registered(Path(r"D:\Other\Sakuya.exe")))
        with mock.patch.object(game_watch, "registered_command", return_value=None):
            self.assertFalse(game_watch.is_registered(exe))

    def test_from_source_the_watcher_does_nothing(self):
        with mock.patch.object(game_watch.sys, "frozen", False, create=True), mock.patch.object(game_watch, "watch") as watched:
            self.assertEqual(game_watch.run([game_watch.WATCH_ARGUMENT]), 0)
        watched.assert_not_called()


if __name__ == "__main__":
    unittest.main()
