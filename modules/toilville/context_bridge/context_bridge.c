// Copyright 2026 toilville
// SPDX-License-Identifier: GPL-2.0-or-later
#include QMK_KEYBOARD_H

#include <string.h>

#include "raw_hid.h"
#include "context_bridge.h"

ASSERT_COMMUNITY_MODULES_MIN_API_VERSION(1, 1, 0);

static context_bridge_context_t current = {
    .id    = 0,
    .layer = CONTEXT_BRIDGE_LAYER_KEEP,
    .color = {0, 0, 0},
    .name  = "",
};

const context_bridge_context_t *context_bridge_context(void) {
    return &current;
}

uint8_t context_bridge_id(void) {
    return current.id;
}

const char *context_bridge_name(void) {
    return current.name;
}

__attribute__((weak)) void context_bridge_changed_user(const context_bridge_context_t *context) {}

static void send_frame(uint8_t report, const uint8_t *payload, uint8_t payload_length) {
    uint8_t frame[CONTEXT_BRIDGE_REPORT_SIZE] = {0};

    frame[0] = CONTEXT_BRIDGE_MAGIC;
    frame[1] = report;

    if (payload && payload_length > 0) {
        if (payload_length > CONTEXT_BRIDGE_REPORT_SIZE - 2) {
            payload_length = CONTEXT_BRIDGE_REPORT_SIZE - 2;
        }
        memcpy(&frame[2], payload, payload_length);
    }

    raw_hid_send(frame, sizeof(frame));
}

static void send_context(void) {
    uint8_t payload[CONTEXT_BRIDGE_REPORT_SIZE - 2] = {0};

    payload[0] = current.id;
    payload[1] = current.layer;
    payload[2] = current.color[0];
    payload[3] = current.color[1];
    payload[4] = current.color[2];
    // Offset 5 in the payload is offset 7 in the frame: the name field.
    memcpy(&payload[CONTEXT_BRIDGE_NAME_OFFSET - 2], current.name, strlen(current.name));

    send_frame(CONTEXT_BRIDGE_REPORT_CONTEXT, payload, sizeof(payload));
}

void context_bridge_request_context(void) {
    send_frame(CONTEXT_BRIDGE_REPORT_HELLO, NULL, 0);
}

static void apply_context(const uint8_t *data, uint8_t length) {
    current.id       = data[2];
    current.layer    = data[3];
    current.color[0] = data[4];
    current.color[1] = data[5];
    current.color[2] = data[6];

    // The host may send a shorter report than the endpoint size; copy only what
    // arrived, and always terminate — the name is used as a C string.
    memset(current.name, 0, sizeof(current.name));
    if (length > CONTEXT_BRIDGE_NAME_OFFSET) {
        uint8_t available = length - CONTEXT_BRIDGE_NAME_OFFSET;
        if (available > CONTEXT_BRIDGE_NAME_MAX) {
            available = CONTEXT_BRIDGE_NAME_MAX;
        }
        memcpy(current.name, &data[CONTEXT_BRIDGE_NAME_OFFSET], available);
    }

#ifndef NO_ACTION_LAYER
    if (current.layer != CONTEXT_BRIDGE_LAYER_KEEP) {
        layer_move(current.layer);
    }
#endif

    context_bridge_changed_user(&current);
}

bool context_bridge_handle_report(uint8_t *data, uint8_t length) {
    // A context frame is at least magic + command; a set also needs its fixed
    // fields. Anything shorter belongs to someone else.
    if (length < 2 || data[0] != CONTEXT_BRIDGE_MAGIC) {
        return false;
    }

    switch (data[1]) {
        case CONTEXT_BRIDGE_CMD_SET_CONTEXT:
            if (length < CONTEXT_BRIDGE_NAME_OFFSET) {
                return false;
            }
            apply_context(data, length);
            send_context();
            return true;

        case CONTEXT_BRIDGE_CMD_GET_CONTEXT:
            send_context();
            return true;

        case CONTEXT_BRIDGE_CMD_PING:
            send_frame(CONTEXT_BRIDGE_REPORT_PONG, NULL, 0);
            return true;

        default:
            return false;
    }
}

void keyboard_post_init_context_bridge(void) {
    keyboard_post_init_context_bridge_kb();

    // The host cannot know the keyboard reappeared after a replug or a reset,
    // so the keyboard asks rather than waiting to be told.
    context_bridge_request_context();
}

#ifndef NO_ACTION_LAYER
layer_state_t layer_state_set_context_bridge(layer_state_t state) {
    state = layer_state_set_context_bridge_kb(state);

    // Report layer moves the host did not cause — a momentary layer key, a
    // tri-layer combination — so its idea of the surface stays accurate.
    uint8_t payload[5] = {
        (uint8_t)get_highest_layer(state),
        (uint8_t)(state & 0xFF),
        (uint8_t)((state >> 8) & 0xFF),
        (uint8_t)((state >> 16) & 0xFF),
        (uint8_t)((state >> 24) & 0xFF),
    };
    send_frame(CONTEXT_BRIDGE_REPORT_LAYER, payload, sizeof(payload));

    return state;
}
#endif

#ifndef CONTEXT_BRIDGE_NO_RAW_HID_HANDLER

__attribute__((weak)) void raw_hid_receive_user(uint8_t *data, uint8_t length) {}

#    ifdef VIA_ENABLE
// VIA owns raw_hid_receive(); via_command_kb() is its hook for keyboard-level
// commands, and returning true means "handled, including the reply".
bool via_command_kb(uint8_t *data, uint8_t length) {
    return context_bridge_handle_report(data, length);
}
#    else
void raw_hid_receive(uint8_t *data, uint8_t length) {
    if (context_bridge_handle_report(data, length)) {
        return;
    }
    raw_hid_receive_user(data, length);
}
#    endif

#endif
