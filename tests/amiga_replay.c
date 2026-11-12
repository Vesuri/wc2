/* Diagnostic only: replay original DOSBox events, never linked in a release.
 * Secret Weapons of Luftwaffe's, with X-Wing's P5 changes, adapted to WC2: no
 * joystick; the reference's VGA status (3DAh) and PIT counter (40h) reads
 * (trace/replay-ports.csv) are answered in their service intervals, as by the
 * host (tests/host_run.py); an interrupt at an overlay point takes the CS its
 * stub's word 10h holds. */
#include "runtime.h"
#include "platform.h"
#include "replay_data.h"
#ifndef REPLAY_REPS
#define REPLAY_REPS 0u
#endif
static uint32_t replay_rep_index, replay_rep_active;
#if REPLAY_REPS
static uint32_t replay_rep_offset;
/* The current record of the REP stream (replay_data.h: varints, zigzag
 * 16-bit differences, in record order). */
static struct replay_rep rep_record;
static const uint8_t *rep_cursor = replay_rep_stream;
static uint16_t rep_end_cx, rep_end_si, rep_end_di;
static int rep_cursor_started;

static uint32_t rep_varint(void)
{
    uint32_t value = 0;
    for (unsigned shift = 0;; shift += 7) {
        uint8_t byte = *rep_cursor++;
        value |= (uint32_t)(byte & 127) << shift;
        if (!(byte & 128)) return value;
    }
}

static uint16_t rep_delta(uint16_t base)
{
    uint32_t z = rep_varint();
    return (uint16_t)(base + ((z & 1) ? ~(z >> 1) : (z >> 1)));
}

static void rep_next(void)
{
    struct replay_rep *c = &rep_record;
    c->service += rep_varint();
    c->hits = rep_varint();
    c->point = (uint16_t)rep_varint();
    c->cx = rep_delta(rep_end_cx);
    c->si = rep_delta(rep_end_si);
    c->di = rep_delta(rep_end_di);
    c->end_cx = rep_delta(c->cx);
    c->end_si = rep_delta(c->si);
    c->end_di = rep_delta(c->di);
    uint32_t tail = rep_varint();
    c->restart = (uint16_t)(tail & 1);
    c->repeat = (uint16_t)(tail >> 1);
    rep_end_cx = c->end_cx; rep_end_si = c->end_si; rep_end_di = c->end_di;
}
#endif

volatile uint32_t replay_services, replay_interrupts, replay_steps;
volatile uint32_t replay_cs, replay_ip;
volatile uint32_t replay_vga_reads, replay_pit_reads, replay_dsp_reads;
static uint32_t retrace_index, retrace_used, pit_index, pit_used;
/* counts as objects: a fixture without reads compares without -Wtype-limits */
static const uint32_t retrace_count = REPLAY_RETRACE, pit_count = REPLAY_PIT;
/* the DSP status ports' runs (22Ch, 22Eh): next row, reads used of it */
static const struct replay_retrace *const dsp_runs[2] = {replay_dsp_write, replay_dsp_data};
static const uint32_t dsp_count[2] = {REPLAY_DSP_WRITE, REPLAY_DSP_DATA};
static uint32_t dsp_index[2], dsp_used[2];
static uint32_t service_hash = 2166136261u, step_hits, release_at;
static uint32_t visits[REPLAY_POINTS], epochs[REPLAY_POINTS];
static uint32_t pending[64], vectors[64], depth, makes;
static int32_t mouse_x, mouse_y;
static uint32_t mouse_buttons;

static void fail(const char *what, uint32_t a, uint32_t b)
{
    rt_stop(what, a, b);
}

static void hash_word(uint16_t word)
{
    service_hash = (service_hash ^ (word >> 8)) * 16777619u;
    service_hash = (service_hash ^ (word & 255)) * 16777619u;
}

/* A service inside IRQ0's handler (owner decision 2026-11-10, docs/design.md;
 * tests/host_run.py relocated): ours runs on the private stack RT_IRQ_SS:RT_IRQ_SP,
 * the reference on the interrupted SS:SP (rt_irq_saved). SS stands for the
 * interrupted SS; SP, and BP while it points into the private stack, are their
 * offsets below RT_IRQ_SP applied to the interrupted SP. */
static void service(const uint32_t *r, uint32_t vector, unsigned returning)
{
    uint16_t word[8], ss = G_SS;
    for (unsigned i = 0; i < 8; ++i) {
        unsigned k = i < 6 ? i : i + 6; /* d0-d5/a4-a5 */
        word[i] = (uint16_t)r[k] ^ (i == 4 || i == 5 ? 0x7fff : 0);
    }
    if (rt_irq0_running) {
        if (ss != RT_IRQ_SS) fail("replay service in IRQ0 off the private stack", ss, replay_services);
        uint16_t sp = *(const uint16_t *)(rt_irq_saved + RT_STATE_BYTES + 8);
        ss = *(const uint16_t *)(rt_irq_saved + 2);
        if (word[4] <= word[5] && word[5] <= RT_IRQ_SP) word[5] = (uint16_t)(word[5] - RT_IRQ_SP + sp);
        word[4] = (uint16_t)(word[4] - RT_IRQ_SP + sp);
    }
    for (unsigned i = 0; i < 8; ++i)
        hash_word(word[i]);
    hash_word(G_ES); hash_word(ss); hash_word(G_DS);
    hash_word(vector);
    hash_word((G_DF ? 0x400 : 0) | (G_IF ? 0x200 : 0));
    hash_word(returning);
    if (replay_services >= REPLAY_SERVICES)
        fail("replay service count", replay_services, service_hash);
    ++replay_services;
    /* The hash runs over every event, so a checkpoint every REPLAY_HASH_STEP
     * events and the last catch any difference; only its index is coarser. */
    if ((replay_services % REPLAY_HASH_STEP == 0 &&
            service_hash != replay_service_hashes[replay_services / REPLAY_HASH_STEP - 1]) ||
            (replay_services == REPLAY_SERVICES && service_hash != REPLAY_FINAL_HASH))
        fail("replay service state", replay_services, service_hash);
}

/* VROOMM's INT 3Fh has no return event: its handler resumes at the stub
 * entry or a redirected return, never after the INT (MEASURED: host-m1 21
 * and host-m1b 34 INT 3Fh events, none returned), so it opens no level. */
#define OVERLAY_VECTOR 0x3fu
void replay_enter(const uint32_t *r)
{
    if ((r[6] & 255) != OVERLAY_VECTOR) {
        if (depth == 64) fail("replay service depth", depth, 0);
        pending[depth] = *(const uint32_t *)((const uint8_t *)r + 66);
        vectors[depth++] = r[6] & 255;
    }
    service(r, r[6] & 255, 0);
}

void replay_return(const uint32_t *r)
{
    uint32_t address = *(const uint32_t *)((const uint8_t *)r + 66);
    if (depth && pending[depth - 1] == address)
        service(r, vectors[--depth], 1);
}

uint32_t replay_mouse(int32_t *dx, int32_t *dy)
{
    *dx = mouse_x; *dy = mouse_y;
    mouse_x = mouse_y = 0;
    return mouse_buttons;
}

static void post(void)
{
    const struct replay_irq *irq = &replay_irqs[replay_interrupts++];
    uint8_t vector = irq->vector;
    if (!G_IF) fail("replay interrupt with IF clear", replay_interrupts, vector);
    if (vector == 9) vector = (++makes & 1) ? 9 : 0x89;
    replay_cs = replay_points[irq->point].slot ? rd16(replay_points[irq->point].slot)
                                               : replay_points[irq->point].cs;
    replay_ip = replay_points[irq->point].ip;
    rt_irq_ring[rt_irq_tail++ % RT_IRQ_RING] = vector;
    RT_RAISE_IRQ();
}

/* Count execution only after any interrupt handler has returned. A handler
 * can itself execute this point or advance the service epoch. */
static void executed(uint32_t point)
{
    if (epochs[point] != replay_services + 1) {
        epochs[point] = replay_services + 1;
        visits[point] = 0;
    }
    ++visits[point];
}

/* Return group index+1, zero for no delivery, or -1 for the final snapshot. */
int32_t replay_point(uint32_t point)
{
    if (point >= REPLAY_POINTS) fail("replay point", point, 0);
    if (release_at && replay_services >= release_at) release_at = 0;
    if (replay_steps < REPLAY_STEPS && !release_at) {
        const struct replay_step *step = &replay_script[replay_steps];
        if (point == step->point && ++step_hits == step->hits) {
            ++replay_steps; step_hits = 0;
            switch (step->kind) {
            case 1: {
                static const uint8_t modifiers[] = {0x2a, 0x1d, 0x38};
                for (unsigned i = 0; i < 3; ++i)
                    if (step->value & (1u << (9 + i)))
                        rt_key_ring[rt_key_tail++ % RT_KEY_RING] = modifiers[i];
                /* One ring event per recorded IRQ9, including E0 prefixes. */
                if (step->value & RT_KEY_E0)
                    rt_key_ring[rt_key_tail++ % RT_KEY_RING] = 0xe0;
                rt_key_ring[rt_key_tail++ % RT_KEY_RING] = step->value & 0xff;
                if (step->value & RT_KEY_E0)
                    rt_key_ring[rt_key_tail++ % RT_KEY_RING] = 0xe0;
                rt_key_ring[rt_key_tail++ % RT_KEY_RING] = (step->value & 0xff) | 0x80;
                for (int i = 2; i >= 0; --i)
                    if (step->value & (1u << (9 + i)))
                        rt_key_ring[rt_key_tail++ % RT_KEY_RING] = modifiers[i] | 0x80;
                release_at = step->release;
                break;
            }
            case 2: mouse_x += step->value; break;
            case 3: mouse_y += step->value; break;
            case 4: mouse_buttons = step->value; break;
            case 0:
                if (replay_steps == REPLAY_STEPS) {
                    /* which: services 1, interrupts 2, depth 4, REP 8, active REP 16,
                     * VGA 32, PIT 64, DSP 128 */
                    uint32_t which = (replay_services != REPLAY_SERVICES) |
                        (replay_interrupts != REPLAY_IRQS) << 1 | (depth != 0) << 2 |
                        (replay_rep_index != REPLAY_REPS) << 3 | (replay_rep_active != 0) << 4 |
                        (replay_vga_reads != REPLAY_VGA_READS) << 5 |
                        (replay_pit_reads != REPLAY_PIT_READS) << 6 |
                        (replay_dsp_reads != REPLAY_DSP_READS) << 7;
                    if (which)
                        fail("replay incomplete", which, replay_pit_reads);
                    return -1;
                }
                break;
            default: fail("replay step kind", step->kind, point);
            }
        }
    }
    if (epochs[point] != replay_services + 1) {
        epochs[point] = replay_services + 1;
        visits[point] = 0;
    }
    if (replay_interrupts < REPLAY_IRQS) {
        const struct replay_irq *irq = &replay_irqs[replay_interrupts];
        if (replay_services > irq->service) fail("replay missed interrupt", replay_interrupts, point);
        if (replay_services == irq->service && point == irq->point && visits[point] == irq->hits) {
            uint32_t group = replay_interrupts + 1;
            post();
            return group;
        }
    }
    executed(point);
    return 0;
}

uint32_t replay_next(uint32_t group)
{
    if (replay_interrupts < REPLAY_IRQS) {
        const struct replay_irq *a = &replay_irqs[group - 1];
        const struct replay_irq *b = &replay_irqs[replay_interrupts];
        if (epochs[a->point] != replay_services + 1) {
            epochs[a->point] = replay_services + 1;
            visits[a->point] = 0;
        }
        /* IRET resumes before the instruction: recheck using handler work,
         * not the service/count saved before the first interrupt. */
        if (replay_services == b->service &&
                a->point == b->point && visits[a->point] == b->hits) {
            post();
            return 1;
        }
    }
    executed(replay_irqs[group - 1].point);
    return 0;
}

/* Observation-driven slice boundaries only; guest elements remain translator
 * output. A restart re-enters the existing diagnostic poll at the same IP. */
uint32_t replay_rep(uint32_t point, uint32_t done, const uint32_t *r)
{
#if REPLAY_REPS
    if (replay_rep_index >= REPLAY_REPS) fail("replay REP exhausted", point, done);
    if (!rep_cursor_started) {
        rep_cursor_started = 1;
        rep_next();
    }
    const struct replay_rep *c = &rep_record;
    uint32_t start_cx = (c->cx + replay_rep_offset * (c->end_cx - c->cx)) & 65535u;
    uint32_t start_si = (c->si + replay_rep_offset * (c->end_si - c->si)) & 65535u;
    uint32_t start_di = (c->di + replay_rep_offset * (c->end_di - c->di)) & 65535u;
    uint32_t end_cx = (c->end_cx + replay_rep_offset * (c->end_cx - c->cx)) & 65535u;
    uint32_t end_si = (c->end_si + replay_rep_offset * (c->end_si - c->si)) & 65535u;
    uint32_t end_di = (c->end_di + replay_rep_offset * (c->end_di - c->di)) & 65535u;
    uint32_t cx = r[1] & 65535u, si = r[12] & 65535u, di = r[13] & 65535u;
    if (point != c->point || replay_services != c->service ||
            epochs[point] != replay_services + 1 || visits[point] != c->hits + replay_rep_offset + 1)
        fail("replay REP epoch", point, replay_rep_index);
    if (!replay_rep_active) {
        if (cx != start_cx || si != start_si || di != start_di)
            fail("replay REP entry", point, replay_rep_index);
        replay_rep_active = 1;
    }
    if (done || (c->restart && cx == end_cx)) {
        if (cx != end_cx || si != end_si || di != end_di || !!done == !!c->restart)
            fail("replay REP end", point, replay_rep_index);
        uint32_t restart = c->restart;   /* c is the record rep_next replaces */
        ++replay_rep_index;
        if (++replay_rep_offset == c->repeat) {
            replay_rep_offset = 0;
            if (replay_rep_index < REPLAY_REPS) rep_next();
        }
        replay_rep_active = 0;
        return restart;
    }
    if (cx < end_cx) fail("replay REP progress", point, replay_rep_index);
    return 0;
#else
    (void)r;
    fail("unexpected replay REP", point, done);
    return 0;
#endif
}

/* The reference's next 3DAh value, read in the same service-event interval. */
uint8_t replay_vga_status(void)
{
    while (retrace_index < retrace_count && retrace_used == replay_retrace[retrace_index].repeat) {
        ++retrace_index;
        retrace_used = 0;
    }
    if (retrace_index == retrace_count) fail("replay VGA status after the last", replay_vga_reads, replay_services);
    const struct replay_retrace *r = &replay_retrace[retrace_index];
    if (r->service != replay_services) fail("replay VGA status interval", replay_vga_reads, replay_services);
    ++retrace_used;
    ++replay_vga_reads;
    return (uint8_t)r->value;
}

/* The reference's next read of DSP status port 22Ch or 22Eh, in the same
 * service-event interval. */
uint8_t replay_dsp_status(uint32_t port)
{
    uint32_t k = port == 0x22e;
    if (port != 0x22c && !k) fail("replay DSP port", port, replay_services);
    while (dsp_index[k] < dsp_count[k] && dsp_used[k] == dsp_runs[k][dsp_index[k]].repeat) {
        ++dsp_index[k];
        dsp_used[k] = 0;
    }
    if (dsp_index[k] == dsp_count[k]) fail("replay DSP status after the last", port, replay_services);
    const struct replay_retrace *r = &dsp_runs[k][dsp_index[k]];
    if (r->service != replay_services) fail("replay DSP status interval", replay_dsp_reads, replay_services);
    ++dsp_used[k];
    ++replay_dsp_reads;
    return (uint8_t)r->value;
}

/* The reference's next two 40h reads (low, high byte), in the same interval:
 * the count the latch took. */
static uint8_t pit_byte(void)
{
    while (pit_index < pit_count && pit_used == replay_pit[pit_index].repeat) {
        ++pit_index;
        pit_used = 0;
    }
    if (pit_index == pit_count) fail("replay PIT read after the last", replay_pit_reads, replay_services);
    const struct replay_retrace *r = &replay_pit[pit_index];
    if (r->service != replay_services) fail("replay PIT read interval", replay_pit_reads, replay_services);
    ++pit_used;
    ++replay_pit_reads;
    return (uint8_t)r->value;
}

uint16_t replay_pit_count(uint32_t ch)
{
    if (ch) fail("replay PIT channel", ch, replay_services);
    uint8_t lo = pit_byte();
    return (uint16_t)(lo | pit_byte() << 8);
}
