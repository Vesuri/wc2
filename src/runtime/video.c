/* INT 10h video BIOS as the reference machine answers it: chained mode 13h
 * at A000:0000 (guest RAM) and the DAC (docs/external-surface.md). Display
 * (D9): the graphics driver's stores to A000h mark changed rows
 * (rt_vram_mark). The game's mouse poll (INT 33h AX=3, once per pass of its
 * loop, after the frame's drawing) is the frame boundary: the frame is
 * presented there if a vertical blank is due, else at the next blank unless
 * a driver call changed rows first (then the next poll's frame). Between
 * polls nothing is shown, so a cockpit gauge's erase and redraw (two driver
 * calls) never reach the screen apart. Before the first poll and once a
 * second of IRQ0 ticks passes without one, a frame is published when the
 * outermost driver call returns and presented at the first vertical blank
 * after that while no driver call runs. A platform that counts vertical
 * blanks may cap the loop at one drawn frame per field (rt_frame_cap): a poll
 * with rows published since the previous poll returns at most once per
 * field. DAC block sets reach the platform at once, as on the VGA; port
 * writes only when they change an entry. The vertical blank's work runs at a poll point or in
 * the platform's field task (an interrupt, docs/irq-plan.md I5); `busy`
 * keeps it off the main thread's display path. */
#include "runtime.h"
#include "platform.h"

uint8_t rt_dac[768];            /* 6-bit R, G, B per entry */

/* IBM VGA BIOS default 256-colour palette, entries 0-247; mode 13h set leaves
 * 248-255 as they were (zero from power-on). Checked against the reference
 * DAC after the mode set. */
static const uint8_t default_palette[248 * 3] = {
    0x00,0x00,0x00,0x00,0x00,0x2a,0x00,0x2a,0x00,0x00,0x2a,0x2a,0x2a,0x00,0x00,0x2a,0x00,0x2a,0x2a,0x15,0x00,0x2a,0x2a,0x2a,
    0x15,0x15,0x15,0x15,0x15,0x3f,0x15,0x3f,0x15,0x15,0x3f,0x3f,0x3f,0x15,0x15,0x3f,0x15,0x3f,0x3f,0x3f,0x15,0x3f,0x3f,0x3f,
    0x00,0x00,0x00,0x05,0x05,0x05,0x08,0x08,0x08,0x0b,0x0b,0x0b,0x0e,0x0e,0x0e,0x11,0x11,0x11,0x14,0x14,0x14,0x18,0x18,0x18,
    0x1c,0x1c,0x1c,0x20,0x20,0x20,0x24,0x24,0x24,0x28,0x28,0x28,0x2d,0x2d,0x2d,0x32,0x32,0x32,0x38,0x38,0x38,0x3f,0x3f,0x3f,
    0x00,0x00,0x3f,0x10,0x00,0x3f,0x1f,0x00,0x3f,0x2f,0x00,0x3f,0x3f,0x00,0x3f,0x3f,0x00,0x2f,0x3f,0x00,0x1f,0x3f,0x00,0x10,
    0x3f,0x00,0x00,0x3f,0x10,0x00,0x3f,0x1f,0x00,0x3f,0x2f,0x00,0x3f,0x3f,0x00,0x2f,0x3f,0x00,0x1f,0x3f,0x00,0x10,0x3f,0x00,
    0x00,0x3f,0x00,0x00,0x3f,0x10,0x00,0x3f,0x1f,0x00,0x3f,0x2f,0x00,0x3f,0x3f,0x00,0x2f,0x3f,0x00,0x1f,0x3f,0x00,0x10,0x3f,
    0x1f,0x1f,0x3f,0x27,0x1f,0x3f,0x2f,0x1f,0x3f,0x37,0x1f,0x3f,0x3f,0x1f,0x3f,0x3f,0x1f,0x37,0x3f,0x1f,0x2f,0x3f,0x1f,0x27,
    0x3f,0x1f,0x1f,0x3f,0x27,0x1f,0x3f,0x2f,0x1f,0x3f,0x37,0x1f,0x3f,0x3f,0x1f,0x37,0x3f,0x1f,0x2f,0x3f,0x1f,0x27,0x3f,0x1f,
    0x1f,0x3f,0x1f,0x1f,0x3f,0x27,0x1f,0x3f,0x2f,0x1f,0x3f,0x37,0x1f,0x3f,0x3f,0x1f,0x37,0x3f,0x1f,0x2f,0x3f,0x1f,0x27,0x3f,
    0x2d,0x2d,0x3f,0x31,0x2d,0x3f,0x36,0x2d,0x3f,0x3a,0x2d,0x3f,0x3f,0x2d,0x3f,0x3f,0x2d,0x3a,0x3f,0x2d,0x36,0x3f,0x2d,0x31,
    0x3f,0x2d,0x2d,0x3f,0x31,0x2d,0x3f,0x36,0x2d,0x3f,0x3a,0x2d,0x3f,0x3f,0x2d,0x3a,0x3f,0x2d,0x36,0x3f,0x2d,0x31,0x3f,0x2d,
    0x2d,0x3f,0x2d,0x2d,0x3f,0x31,0x2d,0x3f,0x36,0x2d,0x3f,0x3a,0x2d,0x3f,0x3f,0x2d,0x3a,0x3f,0x2d,0x36,0x3f,0x2d,0x31,0x3f,
    0x00,0x00,0x1c,0x07,0x00,0x1c,0x0e,0x00,0x1c,0x15,0x00,0x1c,0x1c,0x00,0x1c,0x1c,0x00,0x15,0x1c,0x00,0x0e,0x1c,0x00,0x07,
    0x1c,0x00,0x00,0x1c,0x07,0x00,0x1c,0x0e,0x00,0x1c,0x15,0x00,0x1c,0x1c,0x00,0x15,0x1c,0x00,0x0e,0x1c,0x00,0x07,0x1c,0x00,
    0x00,0x1c,0x00,0x00,0x1c,0x07,0x00,0x1c,0x0e,0x00,0x1c,0x15,0x00,0x1c,0x1c,0x00,0x15,0x1c,0x00,0x0e,0x1c,0x00,0x07,0x1c,
    0x0e,0x0e,0x1c,0x11,0x0e,0x1c,0x15,0x0e,0x1c,0x18,0x0e,0x1c,0x1c,0x0e,0x1c,0x1c,0x0e,0x18,0x1c,0x0e,0x15,0x1c,0x0e,0x11,
    0x1c,0x0e,0x0e,0x1c,0x11,0x0e,0x1c,0x15,0x0e,0x1c,0x18,0x0e,0x1c,0x1c,0x0e,0x18,0x1c,0x0e,0x15,0x1c,0x0e,0x11,0x1c,0x0e,
    0x0e,0x1c,0x0e,0x0e,0x1c,0x11,0x0e,0x1c,0x15,0x0e,0x1c,0x18,0x0e,0x1c,0x1c,0x0e,0x18,0x1c,0x0e,0x15,0x1c,0x0e,0x11,0x1c,
    0x14,0x14,0x1c,0x16,0x14,0x1c,0x18,0x14,0x1c,0x1a,0x14,0x1c,0x1c,0x14,0x1c,0x1c,0x14,0x1a,0x1c,0x14,0x18,0x1c,0x14,0x16,
    0x1c,0x14,0x14,0x1c,0x16,0x14,0x1c,0x18,0x14,0x1c,0x1a,0x14,0x1c,0x1c,0x14,0x1a,0x1c,0x14,0x18,0x1c,0x14,0x16,0x1c,0x14,
    0x14,0x1c,0x14,0x14,0x1c,0x16,0x14,0x1c,0x18,0x14,0x1c,0x1a,0x14,0x1c,0x1c,0x14,0x1a,0x1c,0x14,0x18,0x1c,0x14,0x16,0x1c,
    0x00,0x00,0x10,0x04,0x00,0x10,0x08,0x00,0x10,0x0c,0x00,0x10,0x10,0x00,0x10,0x10,0x00,0x0c,0x10,0x00,0x08,0x10,0x00,0x04,
    0x10,0x00,0x00,0x10,0x04,0x00,0x10,0x08,0x00,0x10,0x0c,0x00,0x10,0x10,0x00,0x0c,0x10,0x00,0x08,0x10,0x00,0x04,0x10,0x00,
    0x00,0x10,0x00,0x00,0x10,0x04,0x00,0x10,0x08,0x00,0x10,0x0c,0x00,0x10,0x10,0x00,0x0c,0x10,0x00,0x08,0x10,0x00,0x04,0x10,
    0x08,0x08,0x10,0x0a,0x08,0x10,0x0c,0x08,0x10,0x0e,0x08,0x10,0x10,0x08,0x10,0x10,0x08,0x0e,0x10,0x08,0x0c,0x10,0x08,0x0a,
    0x10,0x08,0x08,0x10,0x0a,0x08,0x10,0x0c,0x08,0x10,0x0e,0x08,0x10,0x10,0x08,0x0e,0x10,0x08,0x0c,0x10,0x08,0x0a,0x10,0x08,
    0x08,0x10,0x08,0x08,0x10,0x0a,0x08,0x10,0x0c,0x08,0x10,0x0e,0x08,0x10,0x10,0x08,0x0e,0x10,0x08,0x0c,0x10,0x08,0x0a,0x10,
    0x0b,0x0b,0x10,0x0c,0x0b,0x10,0x0d,0x0b,0x10,0x0f,0x0b,0x10,0x10,0x0b,0x10,0x10,0x0b,0x0f,0x10,0x0b,0x0d,0x10,0x0b,0x0c,
    0x10,0x0b,0x0b,0x10,0x0c,0x0b,0x10,0x0d,0x0b,0x10,0x0f,0x0b,0x10,0x10,0x0b,0x0f,0x10,0x0b,0x0d,0x10,0x0b,0x0c,0x10,0x0b,
    0x0b,0x10,0x0b,0x0b,0x10,0x0c,0x0b,0x10,0x0d,0x0b,0x10,0x0f,0x0b,0x10,0x10,0x0b,0x0f,0x10,0x0b,0x0d,0x10,0x0b,0x0c,0x10,
};

/* BIOS data area */
#define BDA_MODE      0x449
#define BDA_COLUMNS   0x44a
#define BDA_PAGE_SIZE 0x44c
#define BDA_PAGE_OFF  0x44e
#define BDA_CURSOR    0x450
#define BDA_PAGE      0x462
#define BDA_ROWS      0x484
#define BDA_CHAR_H    0x485

static void bda_mode(uint8_t mode, uint16_t columns, uint16_t page_size, uint16_t char_h)
{
    wr8(BDA_MODE, mode);
    wr16(BDA_COLUMNS, columns);
    wr16(BDA_PAGE_SIZE, page_size);
    wr16(BDA_PAGE_OFF, 0);
    for (uint32_t a = BDA_CURSOR; a < BDA_CURSOR + 16; ++a) {
        wr8(a, 0);
    }
    wr8(BDA_PAGE, 0);
    wr8(BDA_ROWS, 24);
    wr16(BDA_CHAR_H, char_h);
}

static void set_mode(void)
{
    if (AL(rt_r.ax) != 0x13) {
        rt_unsupported("video mode", 0x10, 0, 0);
    }
    bda_mode(0x13, 40, 0x2000, 8);
    for (uint32_t a = 0xa0000; a < 0xb0000; ++a) {
        wr8(a, 0);
    }
    for (int k = 0; k < 248 * 3; ++k) {
        rt_dac[k] = default_palette[k];
    }
}

/* Changed columns [lo, hi) per row (hi 0: none) over rows [top, bottom);
 * written by rt_vram_mark (rt_entry.s) */
struct vram_row { uint16_t lo, hi; };
struct vram_row rt_vram_rows[200];
uint16_t rt_vram_top = 200, rt_vram_bottom = 0;
uint16_t rt_vdrv_depth;          /* calls into the graphics driver in progress */
static uint8_t published;        /* a driver call that changed rows has returned */
static uint8_t drawn;            /* ... since the last poll: the poll ends a drawn frame */
static uint8_t polled;           /* the game polls the mouse: frames end there */
static uint8_t ready;            /* rows unchanged since the poll's frame */
static uint32_t poll_irq0;       /* IRQ0 deliveries at the last poll */
volatile uint8_t rt_present_due;
volatile uint32_t rt_fields;
uint8_t rt_frame_cap;
static uint32_t frame_field;     /* rt_fields when the last drawn frame's poll returned */
static uint8_t dac_index, dac_component;  /* rt_dac_out, rt_dac_in */
static uint8_t dac_changed;      /* port writes not yet shown (present) */
static volatile uint8_t busy;    /* the main thread presents or sets the video mode or DAC */
static struct plat_rect rects[200];
/* Persistent guest-order pixels, plus 32 bytes of Kalms C2P lookahead. */
static uint32_t frame[16000 + 8];

/* The display path's memory accesses stay inside busy (a compiler barrier on
 * each side). */
static inline void set_busy(uint8_t on)
{
    __asm__ volatile("" ::: "memory");
    busy = on;
    __asm__ volatile("" ::: "memory");
}

void rt_vram_stray(uint32_t at) __attribute__((noreturn));
/* at: the store's generated code, as its return address less rt_vram_mark's
 * (rt_entry.s), so the stop names it in any build's map (production has no
 * guest IP). */
void rt_vram_stray(uint32_t at)
{
    rt_stop("video memory store outside a graphics driver call, rt_vram_mark+", at >> 16, at & 0xffff);
}

static void vram_all(void)
{
    for (int r = 0; r < 200; ++r) {
        rt_vram_rows[r].lo = 0;
        rt_vram_rows[r].hi = 320;
    }
    rt_vram_top = 0;
    rt_vram_bottom = 200;
}

/* The changed rows as rectangles of whole 32-pixel groups (the c2p's
 * unit), rows with equal columns merged; the marks are cleared. */
static void present(void)
{
    if (dac_changed) {
        dac_changed = 0;
        plat_palette(rt_dac);
    }
    int32_t n = 0;
    /* The pointer masked at the last present: from VGA memory again (pointer.c). */
    for (uint16_t y = rt_pointer.masked_y0; y < rt_pointer.masked_y1; ++y) {
        struct vram_row *row = &rt_vram_rows[y];
        uint16_t lo = rt_pointer.masked_x0, hi = rt_pointer.masked_x1;
        row->lo = row->hi && row->lo < lo ? row->lo : lo;
        row->hi = row->hi > hi ? row->hi : hi;
    }
    if (rt_pointer.masked_y1) {
        rt_vram_top = rt_vram_top < rt_pointer.masked_y0 ? rt_vram_top : rt_pointer.masked_y0;
        rt_vram_bottom = rt_vram_bottom > rt_pointer.masked_y1 ? rt_vram_bottom : rt_pointer.masked_y1;
        rt_pointer.masked_y1 = 0;
    }
    for (int r = rt_vram_top; r < rt_vram_bottom; ++r) {
        RT_FIELD_POINT();
        struct vram_row *row = &rt_vram_rows[r];
        if (!row->hi) {
            continue;
        }
        uint16_t x0 = row->lo & ~31, x1 = (row->hi + 31) & ~31;
        row->hi = 0;
        if (n && rects[n - 1].y1 == r && rects[n - 1].x0 == x0 && rects[n - 1].x1 == x1) {
            rects[n - 1].y1 = (uint16_t)(r + 1);
        } else {
            rects[n++] = (struct plat_rect){x0, (uint16_t)r, x1, (uint16_t)(r + 1)};
        }
    }
    rt_vram_top = 200;
    rt_vram_bottom = 0;
    published = 0;
    ready = 0;
    rt_present_due = 0;
    if (n && rd8(BDA_MODE) == 0x13) {
        /* Rows are whole 32-pixel groups and guest memory is reversed at a
         * long-aligned TOP + 1 (runtime.h): each long, byte-swapped, is four
         * pixels in guest order. */
        for (int32_t k = 0; k < n; ++k) {
            uint32_t w = (uint32_t)(rects[k].x1 - rects[k].x0) / 4;
            for (uint16_t y = rects[k].y0; y < rects[k].y1; ++y) {
                uint32_t o = y * 320u + rects[k].x0;
                const uint32_t *s = (const uint32_t *)rt_span(0xa0000 + o, w * 4);
                uint32_t *d = frame + o / 4 + w;
                for (uint32_t c = w; c; --c) {
                    *--d = __builtin_bswap32(*s++);
                }
            }
        }
        rt_pointer_mask((uint8_t *)frame);
        plat_present((const uint8_t *)frame, rects, n);
    }
}

#ifdef WC2_REPLAY
/* Diagnostic replay (tests/amiga_replay.s rt_replay_done): the rows stored since
 * the last present are shown before the capture, so a milestone label inside a
 * frame compares the reference's live VGA memory with the same conversion. */
void rt_video_flush(void)
{
    present();
}
#endif

/* Frames end at the game's mouse poll: polled within the last second of
 * IRQ0 deliveries at the programmed rate. */
static int framed(void)
{
    return polled && rt_irq0_runs + rt_irq0_bios - poll_irq0 < 1193182u / rt_pit_divisor;
}

/* After a vertical blank, at a poll point (rt_present_due 1) or in the field
 * task: the platform's own work once, then the frame if published, the main
 * thread is outside the driver and the display path, and (while frames end
 * at the poll) the rows are the poll's; otherwise it stays due (2). */
void rt_video_refresh(void)
{
    plat_service();
    rt_present_due = 2;
    if (published && !rt_vdrv_depth && !busy && (ready || !framed())) {
        present();
    }
}

/* rt_vdrv_return: the outermost driver call returned with rows changed. */
void rt_video_publish(void)
{
    set_busy(1);
    published = 1;
    drawn = 1;
    ready = 0;
    if (rt_present_due && !framed()) {
        present();
    }
    set_busy(0);
}

/* Capped: a poll that ends a drawn frame returns at most once per field (a
 * poll with nothing drawn since the previous one, as the game's second poll
 * of a flight frame, returns at once; user 2026-11-27). The wait holds no tick: the
 * guest's IRQ0 handler touches no runtime state (docs/irq-plan.md), and its
 * delivery saves the service's registers. */
static void pace(void)
{
    if (rt_fields == frame_field && rt_irq_mask == 1 && !rt_irq0_running) {
        --rt_irq_mask;
        while (rt_fields == frame_field) {
            RT_FIELD_POINT();
        }
        ++rt_irq_mask;
    }
}

/* INT 33h AX=3: the frame the game drew since its last poll is finished. */
void rt_video_frame(void)
{
    uint8_t ends = drawn;
    if (rt_frame_cap && ends) {
        pace();
    }
    drawn = 0;
    polled = 1;
    poll_irq0 = rt_irq0_runs + rt_irq0_bios;
    if (published) {
        set_busy(1);
        if (rt_present_due) {
            present();
        } else {
            ready = 1;
        }
        set_busy(0);
    }
    if (ends) {
        frame_field = rt_fields;
    }
}

/* VGA DAC ports: 3C8h the write index, 3C7h the read index (component 0),
 * 3C9h the next component written or read, the index advancing after blue.
 * Writes that change an entry reach the platform at the next present (the
 * driver writes whole palettes component by component; in flight it rewrites
 * entries 249-254 unchanged every frame, MEASURED 2026-11-27). */
void rt_dac_out(uint16_t port, uint8_t v)
{
    if (port == 0x3c8 || port == 0x3c7) {
        dac_index = v;
        dac_component = 0;
        return;
    }
    uint8_t *e = &rt_dac[dac_index * 3 + dac_component];
    if (*e != (v & 0x3f)) {
        *e = v & 0x3f;
        dac_changed = 1;
    }
    if (++dac_component == 3) {
        dac_component = 0;
        ++dac_index;
    }
}

uint8_t rt_dac_in(void)
{
    uint8_t v = rt_dac[dac_index * 3 + dac_component];
    if (++dac_component == 3) {
        dac_component = 0;
        ++dac_index;
    }
    return v;
}

static void dac_block(int set)
{
    uint32_t first = rt_r.bx, n = rt_r.cx, a = lin(G_ES, rt_r.dx);
    if (first + n > 256) {
        rt_unsupported("DAC block past entry 255", 0x10, 0, 0);
    }
    for (uint32_t k = first * 3; k < (first + n) * 3; ++k, ++a) {
        if (set) {
            rt_dac[k] = rd8(a) & 0x3f;
        } else {
            wr8(a, rt_dac[k]);
        }
    }
}

void rt_int10(void)
{
    set_busy(1);
    switch (AH(rt_r.ax)) {
    case 0x00:
        if (AL(rt_r.ax) == 0x03) {
            /* The exit (SWOTL+047DD) restores the mode AH=0Fh read at start:
             * the BIOS fields as DOSBox-X sets them (c26); text memory and
             * the display are not modelled, nothing reads them after. */
            bda_mode(0x03, 80, 0x1000, 16);
            break;
        }
        set_mode();
        vram_all();
        plat_palette(rt_dac);
        break;
    case 0x08:  /* character and attribute at the cursor: text memory is not
                 * modelled; the reference's text screen is blank there (0720h) */
        if (rd8(BDA_MODE) != 0x03) {
            rt_unsupported("video BIOS character read outside text mode", 0x10, 0, 0);
        }
        rt_r.ax = 0x0720;
        break;
    case 0x12:  /* EGA information (BL=10h): colour, 256 KiB, the reference's
                 * switches and feature bits */
        if ((uint8_t)rt_r.bx != 0x10) {
            rt_unsupported("video BIOS alternate select other than BL=10h", 0x10, 0, 0);
        }
        rt_r.bx = 0x0003;
        rt_r.cx = 0x0f09;
        break;
    case 0x0f:  /* current mode, columns, page */
        rt_r.ax = (uint16_t)(rd8(BDA_COLUMNS) << 8 | rd8(BDA_MODE));
        SET_AH(rt_r.bx, rd8(BDA_PAGE));
        break;
    case 0x10:
        if (AL(rt_r.ax) == 0x12) {
            dac_block(1);
            plat_palette(rt_dac);
        } else if (AL(rt_r.ax) == 0x17) {
            dac_block(0);
        } else {
            rt_unsupported("video BIOS palette function", 0x10, 0, 0);
        }
        break;
    default:
        rt_unsupported("video BIOS function", 0x10, 0, 0);
    }
    set_busy(0);
}
