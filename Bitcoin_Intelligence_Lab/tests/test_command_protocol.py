import tempfile
import unittest

from bitcoinlab.command_protocol import build_command, publish_command, read_ack, serialize_command


class CommandProtocolTests(unittest.TestCase):
    def open_command(self, **kwargs):
        args = dict(command_id="btc-001", action="OPEN", symbol="BTC", side="BUY",
                    volume=0.01, stop_loss=65000, take_profit=68000, now=1000)
        args.update(kwargs)
        return build_command(**args)

    def test_command_is_expiring_eleven_field_envelope(self):
        fields = serialize_command(self.open_command()).strip().split("|")
        self.assertEqual(len(fields), 11)
        self.assertEqual(fields[0], "BTCIL1")
        self.assertEqual(int(fields[3]), 1060)

    def test_wrong_symbol_is_rejected(self):
        with self.assertRaises(ValueError):
            self.open_command(symbol="BTCUSD")

    def test_open_requires_stop_and_target(self):
        with self.assertRaises(ValueError):
            self.open_command(stop_loss=0)

    def test_expiry_is_bounded(self):
        with self.assertRaises(ValueError):
            self.open_command(ttl_seconds=1000)

    def test_close_requires_ticket_and_no_new_levels(self):
        command = build_command(command_id="close-1", action="CLOSE", symbol="BTC", position_ticket=123, now=1000)
        self.assertEqual(command["side"], "NONE")
        with self.assertRaises(ValueError):
            build_command(command_id="close-2", action="CLOSE", symbol="BTC", position_ticket=123, stop_loss=5)

    def test_publish_is_atomic_and_read_ack_defaults_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = publish_command(tmp, self.open_command())
            self.assertTrue(path.is_file())
            self.assertEqual(len(path.read_text(encoding="ascii").strip().split("|")), 11)
            self.assertEqual(read_ack(tmp), {})


if __name__ == "__main__":
    unittest.main()
