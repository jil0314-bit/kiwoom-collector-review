import unittest
from unittest.mock import Mock, patch
import hero_link


class LinkTests(unittest.TestCase):
    def windows(self, charts=(10,)):
        w = Mock()
        w.charts.return_value = list(charts)
        w.edits.return_value = [20]
        w.title.return_value = '[0600] 키움종합차트'
        w.text.return_value = '005930'
        return w

    def test_ambiguous_charts_never_write(self):
        w = self.windows((10, 11))
        self.assertFalse(hero_link.send('005930', w)['ok'])
        w.u.SendMessageTimeoutW.assert_not_called()

    def test_explicit_chart_only(self):
        w = self.windows((10, 11))
        self.assertTrue(hero_link.send('005930', w, '11')['ok'])
        w.edits.assert_called_with(11)
        self.assertEqual(w.u.SendMessageTimeoutW.call_args.args[:2], (20, 0x000C))
        self.assertEqual([c.args[:3] for c in w.u.PostMessageW.call_args_list], [(20, 0x0100, 13), (20, 0x0101, 13)])

    def test_closed_chart_and_order_window_blocked(self):
        w = self.windows()
        self.assertFalse(hero_link.send('005930', w, '99')['ok'])
        w.title.return_value = '[2000] 주문'
        self.assertFalse(hero_link.send('005930', w)['ok'])
        w.u.SendMessageTimeoutW.assert_not_called()

    def test_failed_write_never_sends_enter(self):
        w = self.windows()
        w.text.return_value = '000660'
        self.assertFalse(hero_link.send('005930', w)['ok'])
        w.u.PostMessageW.assert_not_called()

    def test_stale_handle_recovers_only_unique_saved_side(self):
        w = self.windows((10,11))
        w.rect.side_effect = lambda h: (-1000,0,0,0) if h == 10 else (1000,0,0,0)
        with patch.object(hero_link, 'Windows', return_value=w), patch.object(hero_link, 'TARGET_FILE') as f:
            f.read_text.return_value = '{"handle":"99","side":"left"}'
            self.assertEqual(hero_link.preferred(), '10')
            w.charts.return_value = [10,12]
            w.rect.side_effect = lambda h: (-1000,0,0,0)
            self.assertEqual(hero_link.preferred(), '')

    def test_bad_code_rejected(self):
        w = self.windows()
        with self.assertRaises(ValueError):
            hero_link.send('005930\n', w)
        w.charts.assert_not_called()


if __name__ == '__main__':
    unittest.main()
