/* Sound Blaster speech player (sb_play.h). A block plays as fx_play.c plays
 * an effect: in equal chunks of at most one Paula loop, the first restarted,
 * each next latched a field after the one before it starts; the samples a
 * field advance it (24.8) from the rate's Paula period, PAL (313 lines of 227
 * colour clocks) or NTSC (263 of 227.5). A pause keeps the samples played and
 * a continue restarts the voice at the next one. A block that comes at the
 * same rate while one plays is queued and latched behind its last chunk, in
 * place of the silence, so Paula plays it on without a restart (WC2: the game
 * starts each block at the last one's IRQ 7, which comes up to a field before
 * Paula has played the last one out; a restart cut that tail, MEASURED: 6 of
 * 41 intro blocks ended). */
#include "sb_play.h"

#define SILENCE_BYTES 4
#define LOOP_BYTES 65534u           /* Paula's 16-bit word count */
#define CLOCK_PAL 3546895u
#define CLOCK_NTSC 3579545u
#define PERIOD_FLOOR 124

enum { IDLE, PLAY, PAUSED };
static struct {
    const int8_t *pcm;
    uint32_t bytes, rate;
    uint32_t base;                  /* the sample the voice restarted at */
    int32_t elapsed;                /* samples since then, 24.8; below 0 while
                                       the block before it plays out */
    uint32_t chunk;                 /* bytes a chunk from base, even */
    uint8_t chunks, segment, phase;
} b;
static struct {
    const int8_t *pcm;
    uint32_t bytes;
    uint8_t valid;
} q;                                /* the block queued behind the playing one */
static uint8_t handover;            /* the block before the playing one not yet out */
static const int8_t *silence;
uint32_t sb_started, sb_ended;

static void restart_at(uint32_t base)
{
    uint32_t left = b.bytes - base;
    b.base = base;
    b.elapsed = 0;
    b.segment = 0;
    b.chunks = (uint8_t)((left + LOOP_BYTES - 1) / LOOP_BYTES);
    b.chunk = ((left + b.chunks - 1) / b.chunks + 1) & ~1u;
}

void sb_block(const int8_t *pcm, uint32_t bytes, uint32_t rate, const int8_t *zero)
{
    silence = zero;
    ++sb_started;
    if (b.phase == PLAY && rate == b.rate && !q.valid) {
        q.pcm = pcm;
        q.bytes = (bytes + 1) & ~1u;
        q.valid = 1;
        return;
    }
    q.valid = 0;
    handover = 0;
    b.pcm = pcm;
    b.bytes = (bytes + 1) & ~1u;
    b.rate = rate;
    restart_at(0);
    b.phase = PLAY;
}

void sb_pause(uint32_t paused)
{
    if (paused && b.phase == PLAY) {
        b.phase = PAUSED;
    } else if (!paused && b.phase == PAUSED) {
        uint32_t at = b.base + (b.elapsed > 0 ? (uint32_t)b.elapsed >> 8 : 0);
        if (at + 2 > b.bytes) {
            at = b.bytes - 2;
        }
        restart_at(at & ~1u);
        b.phase = PLAY;
    }
}

void sb_clear(void)
{
    b.phase = IDLE;
    q.valid = 0;
    handover = 0;
}

/* The queued block becomes the playing one: `restart` 1 from the next field,
 * 0 latched behind the last, `left` (24.8) the samples the last has to play. */
static void take_queued(int restart, int32_t left)
{
    b.pcm = q.pcm;
    b.bytes = q.bytes;
    q.valid = 0;
    restart_at(0);
    b.elapsed = restart ? 0 : -left;
    b.segment = restart ? 0 : 1;
    handover = !restart;
}

uint16_t sb_field(uint8_t speaker, struct fm_voice *voice, uint8_t *ended)
{
    struct fm_voice *v = &voice[SB_VOICE];
    uint32_t clock = fm_ntsc ? CLOCK_NTSC : CLOCK_PAL;
    uint32_t period = (clock + b.rate / 2) / (b.rate ? b.rate : 1);
    uint32_t field;
    int32_t at;
    *ended = 0;
    if (b.phase == IDLE) {
        return 0;
    }
    if (period < PERIOD_FLOOR) {
        period = PERIOD_FLOOR;
    }
    field = fm_ntsc ? 128u * 119665u / period : 256u * 71051u / period;
    v->channel = -1;
    v->period = (uint16_t)period;
    if (b.phase == PAUSED) {
        v->restart = 0;
        v->loop = silence;
        v->bytes = SILENCE_BYTES;
        v->volume = 0;
        return FM_RESERVE(SB_VOICE);
    }
    if (b.segment) {
        b.elapsed += (int32_t)field;
        at = b.elapsed >> 8;
        if (handover && b.elapsed >= 0) {
            handover = 0;           /* the block before has played out */
            *ended = 1;
            ++sb_ended;
        }
        /* the latched chunk has played a field: latch the next */
        if (b.segment <= b.chunks && at >= (int32_t)((b.segment - 1) * b.chunk + (field >> 8))) {
            ++b.segment;
        }
        if (at >= 0 && b.base + (uint32_t)at >= b.bytes) {
            *ended = 1;
            ++sb_ended;
            if (q.valid) {
                take_queued(1, 0);  /* it came too late to follow on: restart */
            } else {
                b.phase = IDLE;
                v->restart = 0;
                v->loop = silence;
                v->bytes = SILENCE_BYTES;
                v->volume = 0;
                return FM_RESERVE(SB_VOICE);
            }
        } else if (q.valid && b.segment > b.chunks) {
            /* the last chunk is latched and playing: the queued block follows it */
            take_queued(0, (int32_t)((b.bytes - b.base) << 8) - b.elapsed);
        }
    }
    v->restart = b.segment == 0;
    if (!b.segment) {
        b.segment = 1;
    }
    if (b.segment <= b.chunks) {
        uint32_t off = (uint32_t)(b.segment - 1) * b.chunk;
        uint32_t left = b.bytes - b.base - off;
        v->loop = b.pcm + b.base + off;
        v->bytes = (uint16_t)(left < b.chunk ? left : b.chunk);
    } else {
        v->loop = silence;
        v->bytes = SILENCE_BYTES;
    }
    v->volume = speaker ? SB_VOLUME : 0;
    return FM_RESERVE(SB_VOICE);
}
