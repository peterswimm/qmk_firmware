#!/usr/bin/env python3
"""Frame-level tests for the context bridge host tool.

No hardware and no `hid` package needed: only the encode/decode functions are
exercised, which is where a mismatch with the firmware would hide.

    python3 -m unittest discover -s modules/toilville/context_bridge/host
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import context_bridge_host as host


class TestEncodeSetContext(unittest.TestCase):
    def test_frame_is_report_sized(self):
        self.assertEqual(len(host.encode_set_context(1, "live")), host.REPORT_SIZE)

    def test_header_and_fields(self):
        frame = host.encode_set_context(3, "live", 2, (10, 20, 30))
        self.assertEqual(frame[0], host.MAGIC)
        self.assertEqual(frame[1], host.CMD_SET_CONTEXT)
        self.assertEqual(frame[2], 3)
        self.assertEqual(frame[3], 2)
        self.assertEqual(tuple(frame[4:7]), (10, 20, 30))

    def test_name_is_nul_terminated_within_the_frame(self):
        frame = host.encode_set_context(1, "live")
        self.assertEqual(frame[host.NAME_OFFSET : host.NAME_OFFSET + 4], b"live")
        # The firmware reads the name as a C string, so there must be a NUL.
        self.assertEqual(frame[host.NAME_OFFSET + 4], 0)

    def test_layer_defaults_to_keep(self):
        self.assertEqual(host.encode_set_context(1, "live")[3], host.LAYER_KEEP)

    def test_long_name_is_truncated_rather_than_overrunning(self):
        frame = host.encode_set_context(1, "x" * 100)
        self.assertEqual(len(frame), host.REPORT_SIZE)
        self.assertEqual(frame[host.NAME_OFFSET:].count(b"x"[0]), host.NAME_MAX)
        self.assertEqual(frame[host.REPORT_SIZE - 1], 0)

    def test_multibyte_name_is_truncated_on_bytes_not_characters(self):
        frame = host.encode_set_context(1, "é" * 40)
        self.assertEqual(len(frame), host.REPORT_SIZE)

    def test_out_of_range_values_are_masked(self):
        frame = host.encode_set_context(300, "x", 300, (300, 300, 300))
        self.assertEqual(frame[2], 300 & 0xFF)
        self.assertEqual(frame[3], 300 & 0xFF)


class TestEncodeSimple(unittest.TestCase):
    def test_ping(self):
        frame = host.encode_simple(host.CMD_PING)
        self.assertEqual(len(frame), host.REPORT_SIZE)
        self.assertEqual(frame[:2], bytes([host.MAGIC, host.CMD_PING]))
        self.assertEqual(set(frame[2:]), {0})


class TestDecodeReport(unittest.TestCase):
    def test_context_report(self):
        data = bytes([host.MAGIC, host.REPORT_CONTEXT, 3, 2, 10, 20, 30])
        data += b"ableton/session" + bytes(host.REPORT_SIZE - len(data) - 15)
        self.assertEqual(
            host.decode_report(data),
            {
                "type": "context",
                "id": 3,
                "layer": 2,
                "color": [10, 20, 30],
                "name": "ableton/session",
            },
        )

    def test_layer_report_reassembles_the_bitmask(self):
        data = bytes([host.MAGIC, host.REPORT_LAYER, 9, 0x01, 0x02, 0x00, 0x80])
        data += bytes(host.REPORT_SIZE - len(data))
        report = host.decode_report(data)
        self.assertEqual(report["layer"], 9)
        self.assertEqual(report["state"], 0x80000201)

    def test_hello_and_pong(self):
        for command, kind in ((host.REPORT_HELLO, "hello"), (host.REPORT_PONG, "pong")):
            data = bytes([host.MAGIC, command]) + bytes(host.REPORT_SIZE - 2)
            self.assertEqual(host.decode_report(data), {"type": kind})

    def test_foreign_reports_are_ignored(self):
        for data in (
            b"",
            b"\xc7",
            bytes([0x01, host.REPORT_CONTEXT]) + bytes(30),
            bytes([host.MAGIC, 0x7F]) + bytes(30),
        ):
            self.assertIsNone(host.decode_report(data))

    def test_a_name_with_invalid_utf8_does_not_raise(self):
        data = bytes([host.MAGIC, host.REPORT_CONTEXT, 1, 0, 0, 0, 0, 0xFF, 0xFE])
        data += bytes(host.REPORT_SIZE - len(data))
        self.assertIsInstance(host.decode_report(data)["name"], str)


class TestRoundTrip(unittest.TestCase):
    def test_a_set_frame_decodes_as_the_keyboard_would_echo_it(self):
        """The keyboard echoes a context report with the same field layout."""
        sent = host.encode_set_context(4, "davinci/color", 3, (1, 2, 3))
        echoed = bytearray(sent)
        echoed[1] = host.REPORT_CONTEXT

        self.assertEqual(
            host.decode_report(bytes(echoed)),
            {
                "type": "context",
                "id": 4,
                "layer": 3,
                "color": [1, 2, 3],
                "name": "davinci/color",
            },
        )


class TestConstantsMatchFirmware(unittest.TestCase):
    """The firmware header is the other half of this contract."""

    @classmethod
    def setUpClass(cls):
        header = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "context_bridge.h")
        with open(header, encoding="utf-8") as handle:
            cls.header = handle.read()

    def test_magic_and_sizes(self):
        self.assertIn(f"#define CONTEXT_BRIDGE_MAGIC 0x{host.MAGIC:02X}", self.header)
        self.assertIn(f"#define CONTEXT_BRIDGE_REPORT_SIZE {host.REPORT_SIZE}", self.header)
        self.assertIn(f"#define CONTEXT_BRIDGE_NAME_OFFSET {host.NAME_OFFSET}", self.header)
        self.assertIn(f"#define CONTEXT_BRIDGE_LAYER_KEEP 0x{host.LAYER_KEEP:02X}", self.header)

    def test_commands(self):
        for name, value in (
            ("CONTEXT_BRIDGE_CMD_SET_CONTEXT", host.CMD_SET_CONTEXT),
            ("CONTEXT_BRIDGE_CMD_GET_CONTEXT", host.CMD_GET_CONTEXT),
            ("CONTEXT_BRIDGE_CMD_PING", host.CMD_PING),
            ("CONTEXT_BRIDGE_REPORT_CONTEXT", host.REPORT_CONTEXT),
            ("CONTEXT_BRIDGE_REPORT_PONG", host.REPORT_PONG),
            ("CONTEXT_BRIDGE_REPORT_LAYER", host.REPORT_LAYER),
            ("CONTEXT_BRIDGE_REPORT_HELLO", host.REPORT_HELLO),
        ):
            # The header aligns its `=` signs, so match loosely on whitespace.
            self.assertRegex(self.header, rf"{name}\s*=\s*0x{value:02X},")


if __name__ == "__main__":
    unittest.main()
