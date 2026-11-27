"""2026-11-27 memory protection for heavy broadcast workers."""
import sys
import unittest
from datetime import datetime

import broadcast_audio as a
from kiwoom import KST


def at(hour, minute=0):
    return datetime(2026, 11, 27, hour, minute, tzinfo=KST)


class BroadcastGuard(unittest.TestCase):
    def test_no_start_during_market_hours(self):
        for board in (False, True):
            self.assertIsNotNone(a.start_blocked(board, at(8), (10, 10)))
            self.assertIsNotNone(a.start_blocked(board, at(14), (10, 10)))
            self.assertIsNotNone(a.start_blocked(board, at(20, 59), (10, 10)))

    def test_start_at_night_with_memory(self):
        self.assertIsNone(a.start_blocked(True, at(21), (40, 8)))
        self.assertIsNone(a.start_blocked(False, at(7, 59), (74.9, 3.0)))

    def test_memory_blocks_start(self):
        self.assertIsNotNone(a.start_blocked(False, at(23), (75, 8)))
        self.assertIsNotNone(a.start_blocked(True, at(2), (40, 2.9)))

    def test_running_worker_stops(self):
        a.guard(at(23), (89.9, 1))
        with self.assertRaises(a.Deferred):
            a.guard(at(8), (10, 10))
        with self.assertRaises(a.Deferred):
            a.guard(at(3), (90, 10))

    def test_memory_reading(self):
        value = a.memory_status()
        if sys.platform == 'win32':
            self.assertTrue(value and 0 < value[0] <= 100)
        else:
            self.assertIsNone(value)


if __name__ == '__main__':
    unittest.main()
