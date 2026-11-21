/* Prerendered effect player (fx_play.h), X-Wing's (the effect half of Secret
 * Weapons of the Luftwaffe's tfh_paula.c), its iMUSE players replaced by the
 * game's effect slots (WC2.EXE+1254D). A slot that starts an effect with a
 * sample at the captured volume (FX_FULL; every caller's) gets a play: its
 * sample once at its level, in equal chunks of at most one Paula loop, each
 * latched a field after the one before it starts, on a Paula voice the FM
 * re-hoster gives up; its OPL channels are muted while the slot plays it, and
 * after the slot's release while the sample still sounds, until another
 * key-on on the channel (the slot frees at the note-off: the release is the
 * sample's). A stop before the game's release fades out over FX_FADE_FIELDS;
 * at most FX_PLAYS play, the oldest giving way. A start that reuses a slot
 * within one field is seen in the start counts. Another slot volume stays on
 * FM. */
#include "fx_play.h"

#define SILENCE_BYTES 4
#define VOLUME_FULL 64
/* Paula period and samples a field (24.8) for FM_EFFECT_RATE, PAL (313 lines
 * of 227 colour clocks) and NTSC (263 of 227.5). */
#define EFFECT_PERIOD_PAL 214
#define EFFECT_PERIOD_NTSC 216
#define EFFECT_FIELD_PAL (256u * 71051u / EFFECT_PERIOD_PAL)
#define EFFECT_FIELD_NTSC (128u * 119665u / EFFECT_PERIOD_NTSC)
#define EFFECT_LOOP_BYTES 65534u    /* Paula's 16-bit word count */

struct effect {
    const int8_t *pcm;
    uint32_t bytes, end;
    uint16_t chunk;                 /* bytes a chunk, even; the last may be shorter */
    uint8_t chunks, volume;
};
enum { IDLE, PLAY, FADE };
struct play {
    const struct effect *e;
    uint32_t elapsed;               /* samples since the start, 24.8 */
    uint32_t order;                 /* its start's: the oldest gives way */
    uint8_t phase, segment, fade;
    uint8_t player;                 /* FX_NONE once the slot stopped it */
    uint8_t voice;
    uint16_t channels;              /* the slot's OPL channels when last seen */
    uint8_t keys[9];                /* their key-on counts then */
};

static struct effect effects[FX_IDS];
static struct play plays[FX_PLAYS];
static uint8_t tracked[FX_SLOTS];
static uint8_t tracking;            /* tracked[] set to FX_NONE */
static uint8_t seen[FX_IDS];
static uint32_t order;
static const int8_t *silence;
uint32_t fx_started;
uint16_t fx_mask;

void fx_effect(uint8_t id, const int8_t *pcm, uint32_t bytes, uint8_t volume, uint32_t end,
               const int8_t *zero)
{
    struct effect *e = &effects[id];
    if (id >= FX_IDS || bytes < 2 || bytes > FX_EFFECT_BYTES) {
        return;
    }
    if (!silence) {
        silence = zero;
    }
    e->bytes = bytes;
    e->end = end;
    e->chunks = (uint8_t)((bytes + EFFECT_LOOP_BYTES - 1) / EFFECT_LOOP_BYTES);
    e->chunk = (uint16_t)(((bytes + e->chunks - 1) / e->chunks + 1) & ~1u);
    e->volume = volume;
    e->pcm = pcm;                   /* last: the field task may be reading */
}

void fx_clear(void)
{
    uint8_t k;
    for (k = 0; k < FX_IDS; ++k) {
        effects[k].pcm = 0;
    }
    for (k = 0; k < FX_PLAYS; ++k) {
        plays[k].phase = IDLE;
    }
    tracking = 0;
}

uint8_t fx_effect_volume(uint32_t level)
{
    uint32_t v = (level * VOLUME_FULL + FM_EFFECT_FULL / 2) / FM_EFFECT_FULL;
    return (uint8_t)(v > VOLUME_FULL ? VOLUME_FULL : v ? v : 1);
}

static struct play *play_of(uint8_t player)
{
    uint8_t k;
    for (k = 0; k < FX_PLAYS; ++k) {
        if (plays[k].phase != IDLE && plays[k].player == player) {
            return &plays[k];
        }
    }
    return 0;
}

/* Slot p stopped its effect (or plays another): before the game's release of
 * it the play fades, else its tail plays out. */
static void stop(uint8_t player, uint32_t field)
{
    struct play *p = play_of(player);
    if (!p) {
        return;
    }
    p->player = FX_NONE;
    if (p->phase == PLAY && (p->elapsed >> 8) + 2 * (field >> 8) < p->e->end) {
        p->phase = FADE;
        p->fade = FX_FADE_FIELDS;
    }
}

/* Player p starts effect e: its play from the first sample, on the voice it
 * had, else a free one, else the oldest play's. */
static void start(uint8_t player, const struct effect *e)
{
    struct play *p = play_of(player), *oldest = 0;
    uint8_t k, used = 0;
    if (!p) {
        for (k = 0; k < FX_PLAYS; ++k) {
            if (plays[k].phase == IDLE) {
                if (!p) {
                    p = &plays[k];
                }
            } else {
                used = (uint8_t)(used | 1u << plays[k].voice);
                if (!oldest || plays[k].order < oldest->order) {
                    oldest = &plays[k];
                }
            }
        }
        if (p) {
            for (k = 0; used >> k & 1; ++k) {
            }
            p->voice = k;
        } else {
            p = oldest;
        }
    }
    p->e = e;
    p->player = player;
    p->channels = 0;
    p->phase = PLAY;
    p->segment = 0;
    p->elapsed = 0;
    p->order = ++order;
    ++fx_started;
}

/* One field of play p on its voice v. */
static void play_field(struct play *p, struct fm_voice *v, uint32_t field)
{
    const struct effect *e = p->e;
    uint32_t at, volume;
    v->channel = -1;
    v->restart = p->segment == 0;
    v->period = fm_ntsc ? EFFECT_PERIOD_NTSC : EFFECT_PERIOD_PAL;
    if (p->segment) {
        p->elapsed += field;
        at = p->elapsed >> 8;
        /* the latched chunk has played a field: latch the next */
        if (p->segment <= e->chunks && at >= (uint32_t)(p->segment - 1) * e->chunk + (field >> 8)) {
            ++p->segment;
        }
        if (p->segment > e->chunks && at >= e->bytes + (field >> 8)) {
            p->phase = IDLE;
        }
    }
    volume = e->volume;
    if (p->phase == FADE) {
        if (!p->fade) {
            p->phase = IDLE;
        } else {
            volume = volume * p->fade-- / (FX_FADE_FIELDS + 1);
        }
    }
    if (p->phase == IDLE) {
        v->loop = silence;
        v->bytes = SILENCE_BYTES;
        v->volume = 0;
        return;
    }
    if (p->segment == 0) {
        p->segment = 1;
    }
    if (p->segment <= e->chunks) {
        uint32_t off = (uint32_t)(p->segment - 1) * e->chunk;
        v->loop = e->pcm + off;
        v->bytes = (uint16_t)(e->bytes - off < e->chunk ? e->bytes - off : e->chunk);
    } else {
        v->loop = silence;
        v->bytes = SILENCE_BYTES;
    }
    v->volume = (uint8_t)volume;
}

uint16_t fx_field(const struct fx_driver *d, const uint8_t *starts, const uint8_t *keyon, struct fm_voice *voice)
{
    uint32_t field = fm_ntsc ? EFFECT_FIELD_NTSC : EFFECT_FIELD_PAL;
    uint8_t fresh[FX_IDS], appeared[FX_SLOTS], k, c;
    uint16_t mask = 0;
    if (!tracking) {
        for (k = 0; k < FX_SLOTS; ++k) {
            tracked[k] = FX_NONE;
        }
        tracking = 1;
    }
    for (k = 0; k < FX_IDS; ++k) {
        fresh[k] = (uint8_t)(starts[k] - seen[k]);
        seen[k] = starts[k];
    }
    /* A slot that now plays another effect, or none, stopped its own; one
     * that newly plays an effect started it. */
    for (k = 0; k < FX_SLOTS; ++k) {
        uint8_t id = d->active[k] && d->id[k] < FX_IDS && d->volume[k] == FX_FULL && effects[d->id[k]].pcm
                   ? d->id[k] : FX_NONE;
        appeared[k] = id != FX_NONE && id != tracked[k];
        if (tracked[k] != FX_NONE && id != tracked[k]) {
            stop(k, field);
        }
        if (appeared[k] && fresh[id]) {
            --fresh[id];
        }
        tracked[k] = id;
    }
    /* A start left over: a slot that stopped and started the same effect
     * within the field (a start no new slot shows). */
    for (k = 0; k < FX_SLOTS; ++k) {
        if (tracked[k] != FX_NONE && !appeared[k] && fresh[tracked[k]]) {
            --fresh[tracked[k]];
            appeared[k] = 1;
        }
    }
    for (k = 0; k < FX_SLOTS; ++k) {
        if (appeared[k]) {
            start(k, &effects[tracked[k]]);
        }
    }
    for (k = 0; k < 9; ++k) {
        if (d->owner[k] < FX_SLOTS && tracked[d->owner[k]] != FX_NONE) {
            mask = (uint16_t)(mask | 1u << k);
        }
    }
    for (k = 0; k < FX_PLAYS; ++k) {
        struct play *p = &plays[k];
        if (p->phase == IDLE) {
            continue;
        }
        if (p->player != FX_NONE) {     /* its slot's channels now */
            p->channels = 0;
            for (c = 0; c < 9; ++c) {
                if (d->owner[c] == p->player) {
                    p->channels = (uint16_t)(p->channels | 1u << c);
                    p->keys[c] = keyon[c];
                }
            }
        } else {                        /* released: its channels until a key-on there */
            for (c = 0; c < 9; ++c) {
                if (p->channels >> c & 1 && keyon[c] != p->keys[c]) {
                    p->channels = (uint16_t)(p->channels & ~(1u << c));
                }
            }
        }
        play_field(p, &voice[p->voice], field);
        if (p->phase != IDLE) {
            mask = (uint16_t)(mask | p->channels);
        }
        if (p->phase != IDLE) {
            mask = (uint16_t)(mask | FM_RESERVE(p->voice));
        }
    }
    fx_mask = mask;
    return mask;
}
