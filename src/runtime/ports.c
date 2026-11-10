/* I/O ports the game touches (docs/external-surface.md), as devices of the
 * reference machine: PIC, PIT, AdLib, joystick, the VGA DAC and input status,
 * the Sound Blaster DSP's detection. Any other port stops. */
#include "runtime.h"
#include "platform.h"

/* PIC: the mask register (reference mask F8h: IRQ 0-2 enabled); the
 * non-specific EOI is answered in rt_out8 (rt_entry.s). */
static uint8_t pic_mask = 0xf8;

/* PIT: per channel the access mode of its control word (1 lo, 2 hi, 3 lo/hi)
 * and the lo/hi toggle; channel 0's reload (0 = 65536) sets the tick rate.
 * BIOS start state: all channels lo/hi. */
static uint8_t pit_access[3] = {3, 3, 3}, pit_high[3];
/* Counter latch (control word access 0): the count plat_pit_count gave and
 * the bytes of it still to read (2 lo/hi, 1 for access 1 or 2). WC2's delay
 * loops (WC2.EXE +56D40, STRAX.DRV +714) latch channel 0 and read lo, hi. */
static uint16_t pit_latched[3];
static uint8_t pit_latch_left[3];
static uint16_t pit_reload[3];
uint32_t rt_pit_divisor = 0x10000;

/* AdLib: index register, the written OPL2 register file (D10) and the key-on
 * edges per channel (fm_paula.c); rt_out8 (rt_entry.s) answers its byte
 * writes. */
uint8_t rt_opl_index;
uint8_t rt_opl[256];
uint8_t rt_opl_keyon[9];
/* Music skip (annotations/hle.csv music_skip, rt_hle_music_skip): 1, a play
 * of a music record starts no song; 0 runs the guest code. Music stays
 * enabled by default (user 2026-10-15; docs/sound-plan.md). */
uint8_t rt_music_skip = 0;

/* Gameport: with rt_joystick, the trigger latches the axes and each read
 * counts; an axis bit stays 1 for its latched number of reads, so the game's
 * timing loop (root +04466) measures the latch on any CPU. Stick B's axes
 * never time out and its buttons read released, as the reference's. */
uint8_t rt_joystick;
volatile uint16_t rt_joystick_axis[2];
volatile uint8_t rt_joystick_buttons;
static uint16_t joystick_latch[2], joystick_reads;

static uint8_t joystick_in(void)
{
    if (joystick_reads < 0xffff) {
        ++joystick_reads;
    }
    return (uint8_t)(0xcc | (~rt_joystick_buttons & 3) << 4 |
                     (joystick_reads <= joystick_latch[0]) |
                     (joystick_reads <= joystick_latch[1]) << 1);
}

static void pit_control(uint8_t v)
{
    uint8_t ch = v >> 6, access = (v >> 4) & 3;
    if (ch == 3) {
        rt_stop("PIT read-back command", v, 0);
    }
    if (access == 0) {
        if (ch != 0) {
            rt_stop("PIT latch of another channel than 0", v, 0);
        }
        pit_latched[ch] = plat_pit_count(ch);
        pit_latch_left[ch] = pit_access[ch] == 3 ? 2 : 1;
        return;
    }
    pit_access[ch] = access;
    pit_high[ch] = 0;
}

static void pit_data(uint8_t ch, uint8_t v)
{
    uint8_t access = pit_access[ch];
    int high = access == 2 || (access == 3 && pit_high[ch]);
    pit_reload[ch] = high ? (uint16_t)((pit_reload[ch] & 0x00ff) | v << 8)
                          : (uint16_t)((pit_reload[ch] & 0xff00) | v);
    if (access == 3) {
        pit_high[ch] ^= 1;
    }
    if (ch == 0 && (access != 3 || !pit_high[ch])) {
        rt_pit_divisor = pit_reload[0] ? pit_reload[0] : 0x10000;
        plat_timer_rate(rt_pit_divisor);
        if (rt_bench) {
            rt_bench_watch();
        }
    }
}

/* Sound Blaster DSP at 220h (reference/dosbox-x.conf, BLASTER A220): the
 * game's detection (through its port helpers, WC2.EXE +6CB6, +6CC2, +6CCB) resets it (226h 1, 0), reads the ready bit
 * (22Eh) and the AAh answer (22Ah), checks the write status (22Ch) before
 * each command byte and sends 40h A3h (time constant) and D1h (speaker on).
 * Reads answer as the reference's; playback is P6's (speech, D3). */
static uint8_t dsp_reset, dsp_ready;

static uint8_t dsp_in(uint16_t port)
{
    switch (port) {
    case 0x22e: return dsp_ready ? 0xaa : 0x2a;   /* bit 7: data available */
    case 0x22a:
        if (!dsp_ready) {
            rt_stop("DSP data read with none available", port, 0);
        }
        dsp_ready = 0;
        return 0xaa;
    case 0x22c: return 0x2a;                     /* bit 7 clear: ready for a byte */
    }
    rt_stop("unsupported DSP port in", port, 0);
}

static void dsp_out(uint16_t port, uint8_t v)
{
    if (port == 0x226) {
        if (v == 1) {
            dsp_reset = 1;
        } else if (v == 0 && dsp_reset) {
            dsp_reset = 0;
            dsp_ready = 1;
        } else {
            rt_stop("DSP reset sequence", v, dsp_reset);
        }
        return;
    }
    if (port == 0x22c && (v == 0x40 || v == 0xa3 || v == 0xd1)) {
        return;     /* the detection's time constant and speaker on */
    }
    rt_stop("unsupported DSP command (port, value)", port, v);
}

/* A counter read: the latched count's next byte (lo first in access 3). */
static uint8_t pit_read(uint8_t ch)
{
    if (!pit_latch_left[ch]) {
        rt_stop("PIT counter read without a latch (channel)", ch, 0);
    }
    uint8_t access = pit_access[ch];
    int high = access == 2 || (access == 3 && pit_latch_left[ch] == 1);
    --pit_latch_left[ch];
    return (uint8_t)(high ? pit_latched[ch] >> 8 : pit_latched[ch]);
}

uint32_t rt_port_in(uint32_t port, uint32_t width)
{
    port &= 0xffff;
    if (width == 8) {
        switch (port) {
        case 0x21: return pic_mask;
        case 0x40: case 0x41: case 0x42: return pit_read((uint8_t)(port - 0x40));
        case 0x22a: case 0x22c: case 0x22e: return dsp_in((uint16_t)port);
        case 0x3c9: return rt_dac_in();
        case 0x3da: return plat_vga_status();
        case 0x201: return rt_joystick ? joystick_in() : 0xff;  /* reference: no joystick, axes never time out */
        }
    }
    rt_stop("unsupported port in (port, width)", port, width);
}

void rt_port_out(uint32_t port, uint32_t value, uint32_t width)
{
    port &= 0xffff;
    uint8_t v = (uint8_t)value;
    if (width == 8) {
        switch (port) {
        case 0x21: pic_mask = v; return;
        case 0x40: case 0x41: case 0x42: pit_data((uint8_t)(port - 0x40), v); return;
        case 0x43: pit_control(v); return;
        case 0x226: case 0x22c: dsp_out((uint16_t)port, v); return;
        case 0x3c7: case 0x3c8: case 0x3c9: rt_dac_out((uint16_t)port, v); return;
        case 0x201:                 /* joystick one-shots */
            joystick_latch[0] = rt_joystick_axis[0];
            joystick_latch[1] = rt_joystick_axis[1];
            joystick_reads = 0;
            return;
        }
    }
    rt_stop("unsupported port out (port, width)", port, width);
}
