import unittest
from unittest.mock import Mock, patch
import hero_link


class LinkTests(unittest.TestCase):
    def test_exited_process_creation_time_is_not_trusted(self):
        kernel = Mock()
        kernel.OpenProcess.return_value = 123
        kernel.WaitForSingleObject.return_value = 0  # signaled: process exited
        with patch.object(hero_link.ctypes, 'WinDLL', return_value=kernel):
            self.assertIsNone(hero_link.process_start(8240))
        kernel.OpenProcess.assert_called_once_with(0x101000, False, 8240)
        kernel.GetProcessTimes.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(123)

    def windows(self, charts=(10,)):
        w = Mock()
        w.charts.return_value = list(charts)
        w.edits.return_value = [20]
        w.title.return_value = '[0600] 키움종합차트'
        w.text.return_value = '005930'
        w.matches_identity.return_value = False
        w.capture_identity.return_value = {}
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

    def test_stale_handle_recovers_only_same_verified_process(self):
        w = self.windows((10,11))
        w.rect.side_effect = lambda h: (-1000,0,0,0) if h == 10 else (1000,0,0,0)
        w.pid.side_effect = lambda h: 8240 if h == 10 else 19780
        with patch.object(hero_link, 'Windows', return_value=w), patch.object(hero_link, 'TARGET_FILE') as f, patch.object(hero_link, 'process_start', return_value=123):
            f.read_text.return_value = '{"handle":"99","account_suffix":"0311","pid":8240,"process_start":123}'
            self.assertEqual(hero_link.preferred(), '10')
            w.pid.return_value = 19780
            w.pid.side_effect = None
            self.assertEqual(hero_link.preferred(), '')

    def test_live_send_restricts_to_0311_process(self):
        w = self.windows((10, 11))
        w.pid.side_effect = lambda h: 8240 if h == 10 else 19780
        w.rect.return_value = (-1000, 0, 0, 0)
        with patch.object(hero_link, 'Windows', return_value=w), patch.object(hero_link, 'TARGET_FILE') as f, patch.object(hero_link, 'process_start', return_value=123):
            f.read_text.return_value = '{"handle":"10","account_suffix":"0311","pid":8240,"process_start":123}'
            self.assertEqual([t['handle'] for t in hero_link.targets()], ['10'])
            self.assertTrue(hero_link.send('005930', chart_handle='11')['ok'])
            w.edits.assert_called_with(10)
            f.read_text.return_value = '{"handle":"10","account_suffix":"0311","pid":8240,"process_start":999}'
            w.u.SendMessageTimeoutW.reset_mock()
            self.assertFalse(hero_link.send('005930', chart_handle='10')['ok'])
            w.u.SendMessageTimeoutW.assert_not_called()

    def test_bad_code_rejected(self):
        w = self.windows()
        with self.assertRaises(ValueError):
            hero_link.send('005930\n', w)
        w.charts.assert_not_called()

    def test_expired_session_has_actionable_diagnostic(self):
        with patch.object(hero_link, 'TARGET_FILE') as f, patch.object(hero_link, 'process_start', return_value=None):
            f.read_text.return_value = '{"account_suffix":"0311","pid":8240,"process_start":123}'
            self.assertEqual(hero_link.diagnostic()['state'], 'session_changed')

    def test_reconfirmation_rejects_other_account(self):
        with self.assertRaises(ValueError):
            hero_link.confirm_session('9999')

    def test_reconfirmation_never_chooses_between_expanded_charts(self):
        w = self.windows((10, 11))
        w.rect.return_value = (0, 0, 1000, 800)
        with patch.object(hero_link, 'Windows', return_value=w), patch.object(hero_link, 'TARGET_FILE') as f:
            self.assertFalse(hero_link.confirm_session('0311')['ok'])
            f.with_suffix.assert_not_called()

    def test_reconfirmation_ignores_minimized_chart_and_saves_current_session(self):
        w = self.windows((10, 11))
        w.rect.side_effect = lambda h: (-1000, 0, 0, 800 if h == 10 else 28)
        w.pid.return_value = 8240
        w.capture_identity.return_value = {'identity_salt':'salt','account_digest':'account-hash',
                                           'image_digest':'image-hash'}
        with patch.object(hero_link, 'Windows', return_value=w), patch.object(hero_link, 'TARGET_FILE') as f, patch.object(hero_link, 'process_start', return_value=123):
            self.assertTrue(hero_link.confirm_session('0311')['ok'])
            import json
            saved = json.loads(f.with_suffix.return_value.write_text.call_args.args[0])
            self.assertEqual((saved['pid'], saved['process_start'], saved['handle']), (8240,123,'10'))
            f.with_suffix.return_value.replace.assert_called_once_with(f)
            w.u.SendMessageTimeoutW.assert_not_called()

    def test_reconfirmation_without_visible_0311_identity_is_rejected(self):
        w = self.windows()
        w.rect.return_value = (-1000, 0, 0, 800)
        w.pid.return_value = 8240
        with patch.object(hero_link, 'Windows', return_value=w), patch.object(hero_link, 'TARGET_FILE') as f, patch.object(hero_link, 'process_start', return_value=123):
            self.assertFalse(hero_link.confirm_session('0311')['ok'])
            f.with_suffix.assert_not_called()

    def test_same_process_account_change_blocks_link(self):
        w = self.windows()
        w.pid.return_value = 8240
        with patch.object(hero_link, 'TARGET_FILE') as f, patch.object(hero_link, 'process_start', return_value=123):
            f.read_text.return_value = '{"account_suffix":"0311","pid":8240,"process_start":123,"account_digest":"account-hash"}'
            self.assertEqual(hero_link.authorized_charts(w), [])
            w.matches_identity.assert_called_once()

    def recovery(self, matches=(10,)):
        w = self.windows((10, 11))
        w.pid.side_effect = lambda h: h
        w.rect.return_value = (-1000, 0, 0, 800)
        w.matches_identity.side_effect = lambda pid, saved: pid in matches
        return w

    def test_restart_recovers_only_matching_identity_and_side(self):
        w = self.recovery()
        with patch.object(hero_link, 'TARGET_FILE') as f, patch.object(hero_link, 'process_start', side_effect=lambda pid: None if pid == 99 else 456):
            f.read_text.return_value = '{"account_suffix":"0311","pid":99,"process_start":123,"side":"left"}'
            self.assertEqual(hero_link.authorized_charts(w), [10])
            import json
            saved = json.loads(f.with_suffix.return_value.write_text.call_args.args[0])
            self.assertEqual((saved['pid'], saved['process_start'], saved['handle']), (10,456,'10'))
            w.u.SendMessageTimeoutW.assert_not_called()

    def test_restart_with_two_matching_processes_never_rebinds(self):
        w = self.recovery((10,11))
        with patch.object(hero_link, 'TARGET_FILE') as f, patch.object(hero_link, 'process_start', return_value=None):
            f.read_text.return_value = '{"account_suffix":"0311","pid":99,"process_start":123,"side":"left"}'
            self.assertEqual(hero_link.authorized_charts(w), [])
            f.with_suffix.assert_not_called()

    def test_restart_without_identity_never_rebinds(self):
        w = self.recovery(())
        with patch.object(hero_link, 'TARGET_FILE') as f, patch.object(hero_link, 'process_start', return_value=None):
            f.read_text.return_value = '{"account_suffix":"0311","pid":99,"process_start":123,"side":"left"}'
            self.assertEqual(hero_link.authorized_charts(w), [])
            f.with_suffix.assert_not_called()

    def test_restart_wrong_monitor_side_never_rebinds(self):
        w = self.recovery()
        w.rect.return_value = (1000,0,2000,800)
        with patch.object(hero_link, 'TARGET_FILE') as f, patch.object(hero_link, 'process_start', return_value=None):
            f.read_text.return_value = '{"account_suffix":"0311","pid":99,"process_start":123,"side":"left"}'
            self.assertEqual(hero_link.authorized_charts(w), [])
            f.with_suffix.assert_not_called()

    def test_process_changes_during_recovery_never_persists(self):
        w = self.recovery()
        with patch.object(hero_link, 'TARGET_FILE') as f, patch.object(hero_link, 'process_start', side_effect=[None,456,789]):
            f.read_text.return_value = '{"account_suffix":"0311","pid":99,"process_start":123,"side":"left"}'
            self.assertEqual(hero_link.authorized_charts(w), [])
            f.with_suffix.assert_not_called()

    def test_full_account_is_not_stored_in_identity(self):
        w = hero_link.Windows.__new__(hero_link.Windows)
        w.account_values = Mock(return_value=['1234-0311','1234-0311'])
        with patch.object(hero_link, 'process_image', return_value='image-hash'):
            result = w.capture_identity(10)
            self.assertEqual(result['image_digest'], 'image-hash')
            self.assertNotIn('1234-0311', str(result))
            self.assertTrue(w.matches_identity(10,result))
            w.account_values.return_value = ['9999-0311','9999-0311']
            self.assertFalse(w.matches_identity(10,result))


if __name__ == '__main__':
    unittest.main()
