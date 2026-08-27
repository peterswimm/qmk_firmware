#!/usr/bin/env python3
"""Host side of the QMK context bridge.

Sends context frames to a keyboard running the `toilville/context_bridge`
community module, and reports what the keyboard sends back.

The tool holds no mapping policy of its own. It either sets one context from
the command line, or reads newline-delimited JSON from stdin in `serve` mode so
whatever owns the mapping — the Grid Editor's context-bridge package, a window
manager hook, a shell script — can drive it without reimplementing HID access.

    context_bridge_host.py list
    context_bridge_host.py set --id 1 --name ableton/session --layer 2
    echo '{"id":1,"name":"ableton/session","layer":2}' | context_bridge_host.py serve

Requires the `hid` package, which QMK already depends on (requirements.txt).
"""

import argparse
import json
import sys

MAGIC = 0xC7
REPORT_SIZE = 32
NAME_OFFSET = 7
NAME_MAX = REPORT_SIZE - NAME_OFFSET - 1

LAYER_KEEP = 0xFF

CMD_SET_CONTEXT = 0x01
CMD_GET_CONTEXT = 0x02
CMD_PING = 0x03

REPORT_CONTEXT = 0x81
REPORT_PONG = 0x83
REPORT_LAYER = 0x84
REPORT_HELLO = 0x85

REPORT_NAMES = {
    REPORT_CONTEXT: "context",
    REPORT_PONG: "pong",
    REPORT_LAYER: "layer",
    REPORT_HELLO: "hello",
}

# Raw HID's usage page and usage, as QMK and VIA define them.
RAW_USAGE_PAGE = 0xFF60
RAW_USAGE = 0x61


def encode_set_context(context_id, name="", layer=LAYER_KEEP, color=(0, 0, 0)):
    """Build a SET_CONTEXT frame.

    The name is truncated to what one report can carry rather than split across
    frames: it is a label for a human, and the module treats it as a C string.
    """
    frame = bytearray(REPORT_SIZE)
    frame[0] = MAGIC
    frame[1] = CMD_SET_CONTEXT
    frame[2] = context_id & 0xFF
    frame[3] = layer & 0xFF
    frame[4], frame[5], frame[6] = (channel & 0xFF for channel in color)

    encoded = name.encode("utf-8")[:NAME_MAX]
    frame[NAME_OFFSET : NAME_OFFSET + len(encoded)] = encoded

    return bytes(frame)


def encode_simple(command):
    """Build a frame that carries nothing but its command."""
    frame = bytearray(REPORT_SIZE)
    frame[0] = MAGIC
    frame[1] = command
    return bytes(frame)


def decode_report(data):
    """Decode a report from the keyboard, or None if it is not ours."""
    if len(data) < 2 or data[0] != MAGIC:
        return None

    kind = REPORT_NAMES.get(data[1])
    if kind is None:
        return None

    report = {"type": kind}

    if data[1] == REPORT_CONTEXT:
        report["id"] = data[2]
        report["layer"] = data[3]
        report["color"] = [data[4], data[5], data[6]]
        report["name"] = (
            bytes(data[NAME_OFFSET:REPORT_SIZE]).split(b"\x00")[0].decode("utf-8", "replace")
        )
    elif data[1] == REPORT_LAYER:
        report["layer"] = data[2]
        report["state"] = data[3] | (data[4] << 8) | (data[5] << 16) | (data[6] << 24)

    return report


def find_devices(vendor_id=None, product_id=None):
    """Raw HID interfaces, optionally narrowed to one device."""
    import hid

    devices = []
    for info in hid.enumerate(vendor_id or 0, product_id or 0):
        if info.get("usage_page") != RAW_USAGE_PAGE or info.get("usage") != RAW_USAGE:
            continue
        devices.append(info)
    return devices


def open_device(vendor_id=None, product_id=None):
    import hid

    devices = find_devices(vendor_id, product_id)
    if not devices:
        raise SystemExit(
            "no raw HID interface found — check the keyboard is connected and built "
            "with RAW_ENABLE = yes"
        )
    if len(devices) > 1 and (vendor_id is None or product_id is None):
        listing = ", ".join(
            f"{d['vendor_id']:04x}:{d['product_id']:04x}" for d in devices
        )
        raise SystemExit(f"several raw HID interfaces found ({listing}) — pass --vid/--pid")

    device = hid.Device(path=devices[0]["path"])
    return device


def command_list(args):
    for info in find_devices(args.vid, args.pid):
        print(
            f"{info['vendor_id']:04x}:{info['product_id']:04x} "
            f"{info.get('manufacturer_string', '')} {info.get('product_string', '')}".strip()
        )
    return 0


def command_set(args):
    color = tuple(int(part) for part in args.color.split(",")) if args.color else (0, 0, 0)
    if len(color) != 3:
        raise SystemExit("--color takes three comma-separated values")

    device = open_device(args.vid, args.pid)
    device.write(encode_set_context(args.id, args.name, args.layer, color))
    return 0


def command_serve(args):
    """Pump contexts from stdin to the keyboard and reports back to stdout.

    A keyboard that reappears sends `hello`, which is answered with the context
    it missed — a replug or a reset should not leave the surface stale.
    """
    device = open_device(args.vid, args.pid)
    last = None

    def send(context):
        nonlocal last
        last = context
        device.write(
            encode_set_context(
                context.get("id", 0),
                context.get("name", ""),
                context.get("layer", LAYER_KEEP),
                tuple(context.get("color", (0, 0, 0))),
            )
        )

    for line in sys.stdin:
        line = line.strip()
        if not line:
            # A blank line is a chance to drain whatever the keyboard has said.
            while True:
                data = device.read(REPORT_SIZE, timeout=1)
                if not data:
                    break
                report = decode_report(data)
                if report is None:
                    continue
                print(json.dumps(report), flush=True)
                if report["type"] == "hello" and last is not None:
                    send(last)
            continue

        try:
            context = json.loads(line)
        except json.JSONDecodeError as error:
            print(json.dumps({"type": "error", "message": str(error)}), flush=True)
            continue

        send(context)

    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vid", type=lambda v: int(v, 16), help="vendor id, hex")
    parser.add_argument("--pid", type=lambda v: int(v, 16), help="product id, hex")

    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="list raw HID interfaces")

    setter = commands.add_parser("set", help="set one context and exit")
    setter.add_argument("--id", type=int, default=0)
    setter.add_argument("--name", default="")
    setter.add_argument("--layer", type=int, default=LAYER_KEEP)
    setter.add_argument("--color", help="r,g,b")

    commands.add_parser("serve", help="read contexts as JSON lines from stdin")

    args = parser.parse_args(argv)

    return {
        "list": command_list,
        "set": command_set,
        "serve": command_serve,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
