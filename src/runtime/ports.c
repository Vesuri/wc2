/* I/O ports the game touches (docs/external-surface.md), as devices of the
 * reference machine: PIC, PIT, AdLib, joystick, the VGA DAC and input status,
 * the Sound Blaster DSP and its DMA channel 1. Any other port stops. */
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
/* The effect capture's counter (sfx.c): it falls 40h a latch from FFFFh, as
 * tools/sfx_capture.py's, so STRAX.DRV's OPL delay loops end at once. */
static uint16_t capture_count = 0xffff;
void rt_sfx_pit_reset(void)
{
    capture_count = 0xffff;
}
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
/* OPL write delay (annotations/hle.csv opl_delay, rt_hle_opl_delay, D18): 1,
 * STRAX.DRV's settle wait is skipped (the Amiga production build sets it);
 * 0 runs the guest loop (host lockstep, the replay: the PIT reads replay). */
uint8_t rt_opl_delay_skip = 0;

/* Gameport: with rt_joystick, the trigger latches the axes and each read
 * counts; an axis bit stays 1 for its latched number of reads, so the game's
 * timing loop (WC2.EXE+14F5A) measures the latch on any CPU. Stick B's axes
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
        pit_latched[ch] = rt_sfx_capturing ? (capture_count = (uint16_t)(capture_count - 0x40)) : plat_pit_count(ch);
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

/* Sound Blaster DSP at 220h (reference/dosbox-x.conf, BLASTER A220 I7 D1) and
 * its DMA channel 1, as far as the game drives them (every reference milestone
 * m2-m6, MEASURED: DSP commands 40h, 14h, D1h; DMA mode 49h, page 5). The
 * detection (through its port helpers, WC2.EXE +6CB6, +6CC2, +6CCB) resets the
 * DSP (226h 1, 0), reads the ready bit (22Eh) and the AAh answer (22Ah), checks
 * the write status (22Ch) before each command byte and sends 40h A3h (time
 * constant) and D1h (speaker on). The speech plays blocks: DMA channel 1
 * programmed (mask, flip-flop, mode, address, page, count, unmask), then 14h
 * with the length; the DSP raises IRQ 7 when the block has played, and the
 * game's INT 0Fh handler (WC2.EXE +6F3F) programs the next. The exit (milestones
 * mx1, mx2, MEASURED) sends D0h (halt DMA) and D3h (speaker off) through the
 * same helper; a halt while a block plays would cancel its IRQ 7, which no
 * reference shows, so it stops. Status reads answer as the model stands;
 * plat_dsp_status adds the device's timing. */
static uint8_t dsp_reset, dsp_ready;
static uint8_t dsp_command, dsp_args, dsp_arg[2];   /* a command awaiting argument bytes */
static uint8_t dsp_time_constant;
uint8_t rt_sb_playing;      /* a block started and its IRQ 7 not yet taken (machine.c) */
uint8_t rt_sb_speaker;      /* D1h on, D3h off; off at reset (Paula speech volume) */

/* 8237 channel 1: base address and count (lo, hi through the flip-flop),
 * page (83h), mode (0Bh), single mask (0Ah; masked at reset). */
static uint8_t dma_flip, dma_masked = 1, dma_mode;
static uint16_t dma_address, dma_count;
static uint8_t dma_page;

static uint8_t dsp_in(uint16_t port)
{
    uint8_t v;
    switch (port) {
    case 0x22e: v = dsp_ready ? 0xaa : 0x2a; break;   /* bit 7: data available */
    case 0x22a:
        if (!dsp_ready) {
            rt_stop("DSP data read with none available", port, 0);
        }
        dsp_ready = 0;
        return 0xaa;
    case 0x22c: v = 0x2a; break;                     /* bit 7 clear: ready for a byte */
    default: rt_stop("unsupported DSP port in", port, 0);
    }
    return plat_dsp_status(port, v);
}

/* 14h's length is complete: the block from channel 1's address. */
static void dsp_dma_block(uint32_t length)
{
    if (dma_masked || dma_mode != 0x49) {
        rt_stop("DSP block without DMA channel 1 ready (mask, mode)", dma_masked, dma_mode);
    }
    if ((uint32_t)dma_count + 1 < length || (uint32_t)dma_address + length > 0x10000) {
        rt_stop("DSP block beyond DMA channel 1's count or page (count, length)", dma_count, length);
    }
    if (rt_sb_playing) {
        rt_stop("DSP block while one plays (length)", length, 0);
    }
    if (dsp_time_constant == 0) {
        rt_stop("DSP block without a time constant", length, 0);
    }
    rt_sb_playing = 1;
    plat_sb_block((uint32_t)dma_page << 16 | dma_address, length,
                  1000000u / (256u - dsp_time_constant));
}

static void dsp_out(uint16_t port, uint8_t v)
{
    if (port == 0x226) {
        if (v == 1) {
            dsp_reset = 1;
        } else if (v == 0 && dsp_reset) {
            dsp_reset = 0;
            dsp_ready = 1;
            rt_sb_speaker = 0;
        } else {
            rt_stop("DSP reset sequence", v, dsp_reset);
        }
        return;
    }
    if (dsp_args) {
        dsp_arg[--dsp_args] = v;
        if (dsp_args) {
            return;
        }
        if (dsp_command == 0x40) {
            dsp_time_constant = dsp_arg[0];
        } else {            /* 14h: length - 1, lo then hi */
            dsp_dma_block((uint32_t)(dsp_arg[1] | dsp_arg[0] << 8) + 1);
        }
        return;
    }
    switch (v) {
    case 0x40: dsp_command = v; dsp_args = 1; return;    /* time constant */
    case 0x14: dsp_command = v; dsp_args = 2; return;    /* 8-bit single-cycle DMA output */
    case 0xd1: rt_sb_speaker = 1; return;                /* speaker on */
    case 0xd3: rt_sb_speaker = 0; return;                /* speaker off */
    case 0xd0:                                           /* halt DMA */
        if (!rt_sb_playing) {
            return;
        }
        rt_stop("DSP halt while a block plays", v, 0);
    }
    rt_stop("unsupported DSP command", v, 0);
}

static void dma_out(uint16_t port, uint8_t v)
{
    switch (port) {
    case 0x02:
        dma_address = dma_flip ? (uint16_t)((dma_address & 0xff) | v << 8)
                               : (uint16_t)((dma_address & 0xff00) | v);
        dma_flip ^= 1;
        return;
    case 0x03:
        dma_count = dma_flip ? (uint16_t)((dma_count & 0xff) | v << 8)
                             : (uint16_t)((dma_count & 0xff00) | v);
        dma_flip ^= 1;
        return;
    case 0x0a:
        if ((v & 3) == 1) {
            dma_masked = (v & 4) != 0;
            return;
        }
        break;
    case 0x0b:
        if ((v & 3) == 1) {
            dma_mode = v;
            return;
        }
        break;
    case 0x0c: dma_flip = 0; return;
    case 0x83: dma_page = v; return;
    }
    rt_stop("unsupported DMA write (port, value)", port, v);
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
        case 0x02: case 0x03: case 0x0a: case 0x0b: case 0x0c: case 0x83:
            dma_out((uint16_t)port, v);
            return;
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
