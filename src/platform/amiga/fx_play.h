/* Prerendered effect player (owner decision D13), X-Wing's fx_play: the
 * effects the runtime captured (sfx.c) and fm_effect rendered, played on Paula
 * while the game's effect slots play them, their OPL channels muted from the
 * FM re-hoster. Plain C, no Amiga headers, as fm_paula.c. */
#ifndef WC2_FX_PLAY_H
#define WC2_FX_PLAY_H

#include <stdint.h>
#include "fm_paula.h"

#define FX_IDS 56                   /* runtime.h RT_SFX_IDS */
#define FX_SLOTS 32                 /* runtime.h RT_SFX_SLOTS */
#define FX_PLAYS 3                  /* effects at once: the music keeps a Paula voice */
#define FX_FADE_FIELDS 3            /* an early stop's fade */
#define FX_FULL 0x7f                /* the slot volume the effects are captured at */
#define FX_NONE 0xff

/* The game's effect slots in one field (runtime.h rt_sfx_read): per slot
 * active, its record's id (FX_NONE past FX_IDS), its volume 0-127; per OPL
 * channel the slot its STRAX.DRV voice plays, FX_NONE none. */
struct fx_driver {
    uint8_t active[FX_SLOTS], id[FX_SLOTS], volume[FX_SLOTS], owner[9];
};

/* Effect id's sample: fm_effect's output in Chip (even length, at most
 * FX_EFFECT_BYTES: two Paula loops), played at FM_EFFECT_RATE with Paula
 * volume `volume`; `end` the samples to the game's release of it (its
 * capture's ticks, FX_TICK_SAMPLES each); `silence` 4 zero Chip bytes. An id
 * with no sample stays on the FM re-hoster. */
#define FX_EFFECT_BYTES 131068
#define FX_TICK_SAMPLES(ticks) ((ticks) * 21267u / 77u)   /* fm_paula.c FX_TICK_NUM / FX_TICK_DEN */
void fx_effect(uint8_t id, const int8_t *pcm, uint32_t bytes, uint8_t volume, uint32_t end,
               const int8_t *silence);
/* One-shot effects fm_effect does not match (tools/fm_effect_check.cpp, which
 * fails if one listed passes or one unlisted fails; MEASURED 2026-11-21, all
 * feedback-7 patches: 18 its 8-bit tail, 26, 39 and 44 pitch, 40 level): they
 * stay on the FM re-hoster, not captured (owner decision D14). */
#define FX_LIVE_IDS {18, 26, 39, 40, 44}
static inline int fx_live(uint8_t id)
{
    static const uint8_t live[] = FX_LIVE_IDS;
    for (unsigned k = 0; k < sizeof live; ++k) {
        if (live[k] == id) {
            return 1;
        }
    }
    return 0;
}
/* Every sample dropped and every play stopped (before the samples are freed). */
void fx_clear(void);
/* The Paula volume of fm_effect's peak: a full-scale voice is one channel
 * at 0 dB, louder mixes at full volume. */
uint8_t fx_effect_volume(uint32_t level);
/* One field: `d` the slots now, `starts` per id the starts that took a slot
 * (runtime.h rt_sfx_starts), `keyon` per OPL channel its key-on edges
 * (rt_opl_keyon), both wrapping. Fills voice[v] of each Paula voice an effect
 * holds; returns fm_field's mask: the OPL channels of the slots whose effect
 * has a sample, those a play still sounds on after its slot was released
 * until another key-on there, and FM_RESERVE of the voices held. */
uint16_t fx_field(const struct fx_driver *d, const uint8_t *starts, const uint8_t *keyon, struct fm_voice *voice);
/* Diagnostics: plays started; the last field's mask. */
extern uint32_t fx_started;
extern uint16_t fx_mask;

#endif
