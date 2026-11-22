/* Sound Blaster speech player (X-Wing baea334, port-plan P6b.2):
 * the DSP model's 8-bit single-cycle blocks (ports.c, platform.h
 * plat_sb_block) on Paula voice SB_VOICE, which the FM re-hoster and the
 * effect player give up while a block plays. The block's end, counted in
 * samples a field from its rate, ends the voice; IRQ 7 comes from the DSP's
 * own time on a CIA-B timer (amiga_platform.c). Plain C, no Amiga headers,
 * as fx_play.c. */
#ifndef WC2_SB_PLAY_H
#define WC2_SB_PLAY_H

#include <stdint.h>
#include "fm_paula.h"

#define SB_VOICE 3                  /* left; the effect player takes voices from 0 up */
#define SB_BLOCK_BYTES 65536u       /* the 8237's 16-bit count */
#define SB_VOLUME 64

/* A block: `pcm` its samples converted to signed in Chip (bytes, padded with
 * a zero to an even length), played at `rate` Hz from the next field. */
void sb_block(const int8_t *pcm, uint32_t bytes, uint32_t rate, const int8_t *silence);
/* DSP D0h (1): the block holds where it is, silent; D4h (0): it plays on
 * from there. */
void sb_pause(uint32_t paused);
/* No block plays (before the samples are freed). */
void sb_clear(void);
/* One field: `speaker` the DSP's speaker (D1h on, D3h off). Fills
 * voice[SB_VOICE] while a block plays and returns FM_RESERVE(SB_VOICE), else
 * 0; *ended is set when the block's last sample has played this field. */
uint16_t sb_field(uint8_t speaker, struct fm_voice *voice, uint8_t *ended);
/* Diagnostics: blocks started and ended. */
extern uint32_t sb_started, sb_ended;

#endif
