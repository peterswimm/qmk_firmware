// Copyright 2026 toilville
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <stdbool.h>
#include <stdint.h>

/**
 * \file
 *
 * Host-driven context switching over raw HID.
 *
 * A host-side mapping bridge tells the keyboard which desktop context is
 * active — which application has focus, which document, which mode. The
 * keyboard keeps that context, optionally moves to a matching layer, and
 * reports its layer state back so the host and the hardware agree.
 *
 * The module owns the transport and the state. What the context should *look*
 * like is left to the keymap: read the context in an indicator callback, or
 * implement context_bridge_changed_user().
 */

/** Every frame starts with this byte, so the bridge coexists with other raw HID users. */
#define CONTEXT_BRIDGE_MAGIC 0xC7

/** Raw HID reports are a fixed size (RAW_EPSIZE). */
#define CONTEXT_BRIDGE_REPORT_SIZE 32

/** Offset of the context name within a frame, and the space left for it. */
#define CONTEXT_BRIDGE_NAME_OFFSET 7
#define CONTEXT_BRIDGE_NAME_MAX (CONTEXT_BRIDGE_REPORT_SIZE - CONTEXT_BRIDGE_NAME_OFFSET - 1)

/** Layer value meaning "keep the layer you are on". */
#define CONTEXT_BRIDGE_LAYER_KEEP 0xFF

/** Host -> keyboard commands. */
enum context_bridge_command {
    CONTEXT_BRIDGE_CMD_SET_CONTEXT = 0x01,
    CONTEXT_BRIDGE_CMD_GET_CONTEXT = 0x02,
    CONTEXT_BRIDGE_CMD_PING        = 0x03,
};

/** Keyboard -> host reports. A reply carries the request's command with bit 7 set. */
enum context_bridge_report {
    CONTEXT_BRIDGE_REPORT_CONTEXT = 0x81,
    CONTEXT_BRIDGE_REPORT_PONG    = 0x83,
    CONTEXT_BRIDGE_REPORT_LAYER   = 0x84,
    CONTEXT_BRIDGE_REPORT_HELLO   = 0x85,
};

typedef struct {
    uint8_t id;
    uint8_t layer;
    uint8_t color[3];
    char    name[CONTEXT_BRIDGE_NAME_MAX + 1];
} context_bridge_context_t;

/** The context the host last set. Valid from boot; id 0 means "no context yet". */
const context_bridge_context_t *context_bridge_context(void);

/** Shorthand for the current context id. */
uint8_t context_bridge_id(void);

/** Shorthand for the current context name. Never NULL; empty before the first set. */
const char *context_bridge_name(void);

/**
 * Handle one raw HID report.
 *
 * Returns true when the report was a context bridge frame and has been dealt
 * with, false when it belongs to something else. Call this from your own
 * raw_hid_receive() if you define CONTEXT_BRIDGE_NO_RAW_HID_HANDLER.
 */
bool context_bridge_handle_report(uint8_t *data, uint8_t length);

/** Ask the host for the current context. Sent automatically at boot. */
void context_bridge_request_context(void);

/** Called after the host sets a new context. Override in your keymap. */
void context_bridge_changed_user(const context_bridge_context_t *context);

#ifndef CONTEXT_BRIDGE_NO_RAW_HID_HANDLER
/** Chained to for reports the bridge does not recognise. Override in your keymap. */
void raw_hid_receive_user(uint8_t *data, uint8_t length);
#endif
