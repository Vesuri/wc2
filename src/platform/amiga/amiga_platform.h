#ifndef WC2_AMIGA_PLATFORM_H
#define WC2_AMIGA_PLATFORM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The Workbench start message (start.c), 0 from a Shell or the slave. */
struct WBStartup;
extern struct WBStartup *amiga_wb_startup;

/* The translated program's lifetime (amiga_platform.c). open: dos.library,
 * the arguments (from Workbench the icon's tool types and drawer), guest
 * memory, the machine model and the PIT; 0 on failure; call it before the
 * takeover. run: from the program entry until it stops;
 * returns the plat_exit code. close: after the hand-back. */
int amiga_guest_open(void);
long amiga_guest_run(void);
void amiga_guest_close(void);

/* An I/O window around DOS calls (Wc2.cpp); nests, no-op outside the
 * takeover. */
void amiga_io_begin(void);
void amiga_io_end(void);

/* Keyboard and mouse input from the diagnostic key script (Input.cpp): an
 * Amiga raw key edge, mouse counts, the script's held buttons (bit 0 left,
 * 1 right). */
void amiga_key(int raw, int up);
void amiga_mouse_move(int16_t dx, int16_t dy);
void amiga_mouse_script_buttons(uint32_t buttons);
void amiga_joystick_script(uint32_t bits);      /* key script: directions 0-3, buttons 4-5 */
void amiga_joystick_script_axis(int axis, int count);  /* pot count, -1 the pots */

/* The FM re-hoster's next commands (Audio.cpp), from plat_service. */
void amiga_audio_service(void);

/* 1 for an NTSC display (60 Hz fields, NTSC clocks), from graphics'
 * DisplayFlags at Wc2's open: the mode LoadView(NULL) gives at the
 * takeover, whatever the Workbench screen's. Display, CIA timer, FM, TFH
 * and key repeat follow it. */
extern uint8_t amiga_ntsc;
/* Beam line of the display's first row (Wc2.cpp window, Pointer.cpp
 * sprites): PAL $38; NTSC $2C, the standard 200-line window $2C-$F4. */
#define AMIGA_TOP_LINE (amiga_ntsc ? 0x2c : 0x38)

extern volatile uint32_t amiga_frames;
extern volatile uint32_t amiga_io_frames;
extern volatile uint32_t amiga_mouse_reads;
/* 1 from the VERTB handler's first statement (before its acknowledge) to its
 * end. While it is set or VERTB is requested, a CIA tick posts and the DSP
 * block's IRQ 7 retries (amiga_platform.c vblank_owed). Their guest handlers
 * run with the mask lowered to 2; run over an interrupted blank, VERTB was
 * taken again nested and the interrupted blank resumed after the guest
 * handler: the field counted twice, its sprites past the deadline (MEASURED:
 * two entries at line 0 in one field, the interrupted one resumed at line 42;
 * amiga/display_audit.sh). */
extern volatile uint8_t amiga_vblank_busy;
/* The blank's entry line (Wc2::verticalBlank) and, at the last late sprite
 * write, its line and the entry line (Pointer.cpp; display_audit.gdb). */
extern volatile uint16_t amiga_vblank_entry;
extern volatile uint16_t amiga_sprite_late_line, amiga_sprite_late_entry;

#ifdef __cplusplus
}
#endif

#endif
