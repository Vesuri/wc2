/* Effect capture for prerendering (owner decision D13, docs/drivers.md "FM
 * effects"), adapted from X-Wing's src/runtime/sfx.c. An effect is a chain of
 * 8-byte records in WC2.EXE's effect table (DS:0540h) the game steps on
 * STRAX.DRV's 60 Hz tick. At the return of the game's sound init
 * (WC2.EXE+13641, from the startup init: STRAX.DRV and WING2.TIM loaded, the
 * callback installed; HLE sfx_init, observe only), before the first scene,
 * with rt_sfx_prerender_on (owner decision D15), the platform is first asked
 * for samples kept under rt_sfx_key: a CRC-32 of every file byte the game
 * read up to there (the EXE image and its DOS reads), the capture's only
 * input from outside the build. Without them each
 * effect's OPL writes are captured by running the game's own effect code and
 * the driver with the tick held: every slot cleared, all notes off on the 16
 * MIDI channels, 120 ticks to let releases end; then per id from that state
 * the start (WC2.EXE+1254D: flags 0, volume 7Fh, pan 40h, group 1, one
 * channel, as its callers) and a driver tick at a time until the slot is
 * released, plus a 1.5 s tail, at most 8 s. Each tick is STRAX.DRV's (entry 4)
 * with its callback WC2.EXE+132CC gated to the effect tick alone (no fade, no
 * song: DGROUP A53Ch 0, A801h 1, A544h/A546h 0) and the BIOS chain after it
 * (WC2.EXE+10080) kept from the BIOS (its divider at 1, accumulator 0). PIT
 * counter 0 latches read a count falling 40h a latch (ports.c), so the
 * driver's OPL delay loops end at once. DGROUP, the driver, the divider and
 * the private stack are saved before and restored after; game time pauses.
 * Only writes that change a register are kept, from the chip as STRAX.DRV
 * initialises it (all 0, 01h = 20h); the writes go to rt_sfx_capture, not
 * rt_opl. tools/sfx_capture.py is the oracle (the same steps under Unicorn).
 *
 * In play, rt_sfx_read gives the effect player (fx_play.c) the game's effect
 * slots and the OPL channel each STRAX.DRV voice of theirs plays, and HLE
 * sfx_start (the RETF of the effect start WC2.EXE+1254D, observe only) counts
 * each id's starts in rt_sfx_starts. DERIVED by reading (docs/drivers.md). */
#include "platform.h"
#include "runtime.h"

/* WC2.EXE (link segments; the load segment is DS - DGROUP at the hook). */
#define DGROUP 0x1976
#define ROOT 0x1207                 /* the sound routines' segment */
#define START 0x04dd                /* WC2.EXE+1254D: start an effect */
#define CALLBACK 0x125c             /* WC2.EXE+132CC: STRAX.DRV's per-tick callback */
#define TIMER 0x0fd1                /* WC2.EXE+0FD10's segment: the BIOS chain's divider */
#define TIMER_INC 0x01b2            /* code words: its step and accumulator (WC2.EXE+10080) */
#define TIMER_ACC 0x01b8
#define FX_TABLE 0x0540             /* DS: the effect table, id k at + 8k */
#define SLOTS 0xa54c                /* DS: 32 effect slots of 14 bytes (WC2.EXE+1254D) */
#define SLOT_BYTES 14
#define SLOT_COUNT 32
#define SLOT_CHANNEL 1              /* byte: its first MIDI channel, 1-16; 0 free */
#define SLOT_CHANNEL2 2             /* byte: its second, 0 none */
#define SLOT_VOLUME 4
#define SLOT_RECORD 0x0a            /* far pointer: its record */
#define GATE_FADE 0xa53c            /* DS words: the callback's music fade step, */
#define GATE_SONG 0xa801            /* its song state and song pointer */
#define GATE_SONG_PTR 0xa544
#define DRV_CS 0xae56               /* DS words: STRAX.DRV's CS and its note entry (074Dh) */
#define DRV_NOTE 0xae54
/* STRAX.DRV (CS = its block, IP 0 its file offset 4DDh). */
#define DRV_BYTES 3986
#define DRV_TICK 0x0ddd             /* entry 4, the INT 08h tick */
#define DRV_CONTROL 0x0b61          /* entry 6: controller (value, controller, channel) */
#define DRV_NOTE_IP 0x074d
#define DRV_CALLBACK 0x001c         /* CS far pointer: the per-tick callback */
#define DRV_VOICES 0x0086           /* CS bytes: each voice's MIDI channel, 0-based; FFh free */
#define DRV_VOICE_COUNT 11
#define ALL_NOTES_OFF 0x7b
#define SETTLE 120
#define TAIL 90
#define TICKS_MAX 480               /* 8 s at 60 Hz */
#define STACK_BYTES 0x800           /* the private stack the capture runs on, below RT_IRQ_SP */
#define DGROUP_BYTES 0x10000u
#define SOUND_CARD 0xa52c           /* DS word: the sound init's driver kind, 0 none (WC2.EXE+13641) */
#define SENTINEL_CS RT_IRQ_SS
#define SENTINEL_IP RT_IRQ_SP

uint8_t rt_sfx_prerender_on;
volatile uint8_t rt_sfx_capturing;
__attribute__((aligned(4))) struct rt_sfx_write rt_sfx_capture[RT_SFX_WRITES];
__attribute__((aligned(4))) uint16_t rt_sfx_first[RT_SFX_IDS], rt_sfx_writes[RT_SFX_IDS], rt_sfx_ticks[RT_SFX_IDS];
__attribute__((aligned(4))) uint8_t rt_sfx_opl[256];
uint32_t rt_sfx_captures;
uint32_t rt_sfx_key;
__attribute__((aligned(4))) uint8_t rt_sfx_starts[RT_SFX_IDS];
static uint16_t capture_n, capture_tick, ds_seen, drv_seen;
static uint8_t recording, shadow[256], keyed;
static uint32_t crc_table[256], crc = 0xffffffffu;

/* The game's file bytes in the order it read them (machine.c's EXE image, dos.c's
 * reads), into rt_sfx_key's CRC-32 until the sound init's return. */
void rt_sfx_input(const uint8_t *p, uint32_t n)
{
    if (!rt_sfx_prerender_on || keyed) {
        return;
    }
    if (!crc_table[1]) {
        for (uint32_t k = 0; k < 256; ++k) {
            uint32_t c = k;
            for (int b = 0; b < 8; ++b) {
                c = c & 1 ? 0xedb88320u ^ c >> 1 : c >> 1;
            }
            crc_table[k] = c;
        }
    }
    uint32_t c = crc;
    while (n--) {
        c = crc_table[(c ^ *p++) & 0xff] ^ c >> 8;
    }
    crc = c;
}

uint32_t rt_guest_call(uint32_t sentinel);
void *rt_lookup(uint32_t cs, uint32_t ip, uint32_t far);

/* rt_out8 (rt_entry.s) while capturing: one OPL data write. */
void rt_sfx_write(uint32_t reg, uint32_t value)
{
    reg &= 0xff;
    value &= 0xff;
    if (shadow[reg] == value) {
        return;
    }
    shadow[reg] = (uint8_t)value;
    if (recording && capture_n < RT_SFX_WRITES) {
        rt_sfx_capture[capture_n].tick = capture_tick;
        rt_sfx_capture[capture_n].reg = (uint8_t)reg;
        rt_sfx_capture[capture_n].value = (uint8_t)value;
        ++capture_n;
    }
}

static void push(uint16_t v)
{
    rt_r.sp = (uint16_t)(rt_r.sp - 2);
    wr16(lin(G_SS, rt_r.sp), v);
}

/* Guest code at cs:ip on the private stack below the sentinel return, DS and
 * ES DGROUP: a far C call with n arguments (left to right), or (iret) an
 * interrupt frame. DX:AX after. */
static uint32_t guest(uint16_t ds, uint16_t cs, uint16_t ip, int iret, const uint16_t *arg, int n)
{
    G_SS = RT_IRQ_SS;
    G_DS = G_ES = ds;
    rt_r.sp = RT_IRQ_SP;
    if (iret) {
        push(0x0202);
        G_IF = 0;
    } else {
        while (n--) {
            push(arg[n]);
        }
        G_IF = 1;
    }
    G_TF = 0;
    push(SENTINEL_CS);
    push(SENTINEL_IP);
    rt_deliver_cs = cs;
    rt_deliver_ip = ip;
    rt_deliver_code = rt_lookup(cs, ip, 1);
    rt_guest_call((uint32_t)SENTINEL_CS << 16 | SENTINEL_IP);
    return (uint32_t)rt_r.dx << 16 | rt_r.ax;
}

/* One STRAX.DRV tick, its BIOS chain held back. */
static void tick(uint16_t ds, uint16_t drv, uint32_t timer)
{
    wr16(timer + TIMER_INC, 1);
    wr16(timer + TIMER_ACC, 0);
    guest(ds, drv, DRV_TICK, 1, 0, 0);
}

/* The bytes the capture changes: DGROUP, the driver, the divider, the stack. */
struct span { uint32_t at, n; };
static void spans(struct span *s, uint16_t ds, uint16_t drv, uint32_t timer)
{
    s[0] = (struct span){lin(ds, 0), DGROUP_BYTES};
    s[1] = (struct span){lin(drv, 0), DRV_BYTES};
    s[2] = (struct span){timer + TIMER_INC, TIMER_ACC + 2 - TIMER_INC};
    s[3] = (struct span){lin(RT_IRQ_SS, RT_IRQ_SP) - STACK_BYTES, STACK_BYTES};
}

static void memory(const struct span *s, uint8_t *save, int restore)
{
    for (int k = 0; k < 4; ++k) {
        uint8_t *span = restore ? rt_span_w(s[k].at, s[k].n) : rt_span(s[k].at, s[k].n);
        for (uint32_t i = 0; i < s[k].n; ++i) {
            if (restore) {
                span[i] = save[i];
            } else {
                save[i] = span[i];
            }
        }
        save += s[k].n;
    }
}

/* STRAX.DRV's CS, checked: DGROUP holds its note entry, it the game's callback. */
static uint16_t driver(uint16_t ds)
{
    uint16_t root = (uint16_t)(ds - DGROUP + ROOT), drv = rd16(lin(ds, DRV_CS));
    if (rd16(lin(ds, DRV_NOTE)) != DRV_NOTE_IP || rd16(lin(drv, DRV_CALLBACK)) != CALLBACK
        || rd16(lin(drv, DRV_CALLBACK + 2)) != root) {
        rt_stop("effect capture: DGROUP does not hold STRAX.DRV with the game's callback", drv, ds);
    }
    return drv;
}

static void capture(uint16_t ds)
{
    uint16_t load = (uint16_t)(ds - DGROUP), root = (uint16_t)(load + ROOT), drv = driver(ds);
    uint32_t timer = lin((uint16_t)(load + TIMER), 0);
    struct span s[4];
    spans(s, ds, drv, timer);
    uint32_t bytes = 0;
    for (int k = 0; k < 4; ++k) {
        bytes += s[k].n;
    }
    uint8_t *hook = plat_alloc(2 * bytes), *settled = hook + bytes;
    if (!hook) {
        rt_log("effect capture: no memory for the saved state; effects stay live");
        return;
    }
    uint8_t index = rt_opl_index, pair = rt_opl_pair;
    memory(s, hook, 0);
    rt_irq0_running = 1;            /* no tick delivered; the CIA's held */
    rt_sfx_capturing = 1;
    rt_sfx_pit_reset();
    for (unsigned r = 0; r < 256; ++r) {
        shadow[r] = 0;
    }
    shadow[1] = 0x20;
    recording = 0;
    capture_n = 0;
    wr16(lin(ds, GATE_FADE), 0);
    wr16(lin(ds, GATE_SONG), 1);
    wr32(lin(ds, GATE_SONG_PTR), 0);
    for (unsigned k = 0; k < SLOT_COUNT; ++k) {
        wr8(lin(ds, (uint16_t)(SLOTS + SLOT_BYTES * k + SLOT_CHANNEL)), 0);
    }
    for (uint16_t ch = 1; ch <= 16; ++ch) {
        const uint16_t arg[3] = {0, ALL_NOTES_OFF, ch};
        guest(ds, drv, DRV_CONTROL, 0, arg, 3);
    }
    for (unsigned t = 0; t < SETTLE; ++t) {
        tick(ds, drv, timer);
    }
    for (unsigned r = 0; r < 256; ++r) {
        rt_sfx_opl[r] = shadow[r];
    }
    memory(s, settled, 0);
    uint8_t settled_shadow[256];
    for (unsigned r = 0; r < 256; ++r) {
        settled_shadow[r] = shadow[r];
    }
    for (uint8_t id = 0; id < RT_SFX_IDS; ++id) {
        rt_sfx_first[id] = capture_n;
        rt_sfx_writes[id] = rt_sfx_ticks[id] = 0;
        /* a record a chain before it continues (flag bit 0) is no start */
        if (!id || (id > 1 && (rd8(lin(ds, (uint16_t)(FX_TABLE + 8 * (id - 1)))) & 1)) || !plat_sfx_wanted(id)) {
            continue;
        }
        memory(s, settled, 1);
        for (unsigned r = 0; r < 256; ++r) {
            shadow[r] = settled_shadow[r];
        }
        recording = 1;
        capture_tick = 0;
        const uint16_t arg[7] = {(uint16_t)(FX_TABLE + 8 * id), ds, 0, 0x7f, 0x40, 1, 1};
        uint32_t slot = guest(ds, root, START, 0, arg, 7);
        uint16_t released = 0;
        if (slot) {
            uint32_t channel = lin((uint16_t)(slot >> 16), (uint16_t)slot) + SLOT_CHANNEL;
            for (capture_tick = 1; capture_tick <= TICKS_MAX; ++capture_tick) {
                tick(ds, drv, timer);
                if (!released && !rd8(channel)) {
                    released = capture_tick;
                }
                if (released && capture_tick >= released + TAIL) {
                    break;
                }
            }
        }
        recording = 0;
        if (capture_n >= RT_SFX_WRITES) {
            rt_log("effect capture: the write buffer is full");
            break;
        }
        rt_sfx_writes[id] = (uint16_t)(capture_n - rt_sfx_first[id]);
        rt_sfx_ticks[id] = released;    /* 0: held (the game stops it), or no slot */
    }
    memory(s, hook, 1);
    rt_opl_index = index;
    rt_opl_pair = pair;
    plat_free(hook);
    ds_seen = ds;
    drv_seen = drv;
    ++rt_sfx_captures;
    plat_sfx_captured();            /* the prerender, game time still paused */
    rt_sfx_capturing = 0;
    rt_irq0_running = 0;
}

/* HLE sfx_init (rt_entry.s saves and restores the guest's registers and state
 * block around it): the RETF of the game's sound init WC2.EXE+13641, DS
 * DGROUP. Once, on the main thread, with a sound driver (SOUND_CARD; the init
 * returns early without one): the samples kept under rt_sfx_key, else the
 * capture and the prerender. */
void rt_sfx_init(void)
{
    if (!rt_sfx_prerender_on || keyed || rt_irq0_running) {
        return;
    }
    keyed = 1;
    rt_sfx_key = ~crc;
    uint16_t ds = G_DS;
    if (!rd16(lin(ds, SOUND_CARD))) {
        return;
    }
    uint16_t drv = driver(ds);
    if (plat_sfx_cached()) {
        ds_seen = ds;
        drv_seen = drv;
        return;
    }
    capture(ds);
}

/* HLE sfx_start (rt_entry.s as sfx_init): the RETF of WC2.EXE+1254D, DX:AX
 * the slot it took (0 none), its record's far pointer at SS:SP+4. The
 * capture's own starts return through it too: they are not the game's, so not
 * counted. */
void rt_sfx_start(void)
{
    if (rt_sfx_capturing) {
        return;
    }
    uint16_t ds = G_DS;
    uint32_t top = lin(G_SS, rt_r.sp);
    uint16_t off = rd16(top + 4), seg = rd16(top + 6);
    uint16_t id = (uint16_t)((off - FX_TABLE) / 8);
    if ((rt_r.ax || rt_r.dx) && seg == ds && off > FX_TABLE && !((off - FX_TABLE) & 7) && id < RT_SFX_IDS) {
        ++rt_sfx_starts[id];
    }
}

/* The game's effect slots now (any time after a capture; the field task calls
 * it with the tick masked): per slot active, its record's id (0xff none or
 * past RT_SFX_IDS) and volume; per OPL channel the slot whose MIDI channel
 * its STRAX.DRV voice plays (voice v on channel v, voices 9 and 10 on 8 and
 * 7: STRAX.DRV+0C64), 0xff none. 0 before the first capture. */
int rt_sfx_read(uint8_t *active, uint8_t *id, uint8_t *volume, uint8_t *owner)
{
    if (!ds_seen) {
        return 0;
    }
    uint8_t chan[RT_SFX_SLOTS][2];
    for (unsigned k = 0; k < RT_SFX_SLOTS; ++k) {
        uint32_t at = lin(ds_seen, (uint16_t)(SLOTS + SLOT_BYTES * k));
        uint16_t off = rd16(at + SLOT_RECORD), seg = rd16(at + SLOT_RECORD + 2);
        uint16_t n = (uint16_t)((off - FX_TABLE) / 8);
        chan[k][0] = rd8(at + SLOT_CHANNEL);
        chan[k][1] = rd8(at + SLOT_CHANNEL2);
        active[k] = chan[k][0] != 0;
        id[k] = seg == ds_seen && off > FX_TABLE && !((off - FX_TABLE) & 7) && n < RT_SFX_IDS ? (uint8_t)n : 0xff;
        volume[k] = rd8(at + SLOT_VOLUME);
    }
    for (unsigned c = 0; c < 9; ++c) {
        owner[c] = 0xff;
    }
    for (unsigned v = 0; v < DRV_VOICE_COUNT; ++v) {
        uint8_t midi = rd8(lin(drv_seen, (uint16_t)(DRV_VOICES + v))), c = (uint8_t)(v <= 8 ? v : 17 - v);
        if (midi == 0xff) {
            continue;
        }
        for (unsigned k = 0; k < RT_SFX_SLOTS; ++k) {
            if (active[k] && (chan[k][0] == midi + 1 || chan[k][1] == midi + 1)) {
                owner[c] = (uint8_t)k;
            }
        }
    }
    return 1;
}
