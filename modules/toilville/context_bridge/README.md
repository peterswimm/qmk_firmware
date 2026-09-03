# Context Bridge

Host-driven context switching over raw HID. A host-side mapping bridge tells the
keyboard which desktop context is active — which application has focus, which
document, which mode — and the keyboard moves to a matching layer and keeps the
context available to the keymap.

The module owns the transport and the state. What a context should *look* like is
left to the keymap, because only the keymap knows what its LEDs and displays are
for.

## Adding it to a keymap

`keymap.json`:

```json
{
  "modules": ["toilville/context_bridge"]
}
```

The module's `rules.mk` enables `RAW_ENABLE`. It requires community modules API
1.1.0 or newer.

## Using the context in a keymap

```c
#include "context_bridge.h"

// Called after the host sets a new context.
void context_bridge_changed_user(const context_bridge_context_t *context) {
    dprintf("context %u: %s\n", context->id, context->name);
}

bool rgb_matrix_indicators_user(void) {
    const context_bridge_context_t *context = context_bridge_context();
    if (context->id != 0) {
        rgb_matrix_set_color(0, context->color[0], context->color[1], context->color[2]);
    }
    return true;
}
```

`context_bridge_id()` and `context_bridge_name()` are shorthands for the same
state. The context is valid from boot, with id 0 meaning "the host has not said
yet".

## Wire format

Fixed 32 byte raw HID reports. Every frame starts with `0xC7` so the bridge
coexists with other raw HID users on the same interface.

| Byte | Host → keyboard | Keyboard → host |
| --- | --- | --- |
| 0 | `0xC7` | `0xC7` |
| 1 | command | report |
| 2 | context id | context id / highest layer |
| 3 | layer, or `0xFF` to keep the current one | layer / layer state byte 0 |
| 4–6 | r, g, b | r, g, b / layer state bytes 1–3 |
| 7–31 | context name, NUL-terminated | context name |

| Command | | Report | |
| --- | --- | --- | --- |
| `0x01` | set context | `0x81` | context (echoed after a set, or on request) |
| `0x02` | get context | `0x83` | pong |
| `0x03` | ping | `0x84` | layer changed |
| | | `0x85` | hello — sent at boot |

The keyboard sends `hello` when it boots, because the host cannot know it
reappeared after a replug or a reset; answer it by re-sending the current
context. It sends `layer changed` for layer moves the host did not cause — a
momentary layer key, a tri-layer combination — so the host's idea of the surface
stays accurate.

## The host tool

`host/context_bridge_host.py` sends frames and reports what comes back. It holds
no mapping policy: either set one context from the command line, or feed it
newline-delimited JSON so whatever owns the mapping drives it without
reimplementing HID access.

```sh
host/context_bridge_host.py list
host/context_bridge_host.py set --id 1 --name ableton/session --layer 2
echo '{"id":1,"name":"ableton/session","layer":2}' | host/context_bridge_host.py serve
```

In `serve` mode it prints the keyboard's reports as JSON lines and re-sends the
last context whenever the keyboard says hello. It needs the `hid` package, which
QMK already depends on.

```sh
python3 -m unittest discover -s host
```

The frame tests run without hardware, and include a check that the constants in
`context_bridge.h` and the Python tool still agree.

## Coexisting with other raw HID users

- **VIA builds.** The module hooks `via_command_kb()`, which VIA consults before
  its own command switch, so bridge frames are consumed first. VIA's command ids
  stop at `0x15`, well clear of the `0xC7` magic.
- **Keymaps with their own handler.** Without VIA the module defines
  `raw_hid_receive()` and chains anything it does not recognise to
  `raw_hid_receive_user()`. If your keymap already defines `raw_hid_receive()`,
  define `CONTEXT_BRIDGE_NO_RAW_HID_HANDLER` and call
  `context_bridge_handle_report()` yourself:

  ```c
  void raw_hid_receive(uint8_t *data, uint8_t length) {
      if (context_bridge_handle_report(data, length)) {
          return;
      }
      // your own commands
  }
  ```
