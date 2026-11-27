#ifndef WC2_DISPLAY_QUEUE_H
#define WC2_DISPLAY_QUEUE_H

#include <stdint.h>

// Main-thread dirty state for both physical bitmaps. The ISR only changes
// shown/pending. Call begin(), queue() and flip() with interrupts excluded.
// Withdrawing pending before conversion lets updates coalesce without ever
// writing the bitmap DMA is reading, or waiting before a guest poll point.
struct DisplayQueue {
    // Per bitmap and row, the 32-pixel blocks (bit k: x 32k) changed since
    // that bitmap's last conversion.
    uint16_t rows[2][200] = {};
    volatile uint16_t shown = 0;
    volatile int16_t pending = -1;

    uint16_t begin() {
        pending = -1;
        return shown ^ 1;
    }
    // x0, x1 multiples of 32
    void mark(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1) {
        uint16_t bits = (uint16_t)(((1u << (x1 / 32)) - 1) & ~((1u << (x0 / 32)) - 1));
        for (unsigned b = 0; b < 2; ++b) {
            for (unsigned y = y0; y < y1; ++y) {
                rows[b][y] |= bits;
            }
        }
    }
    void clear(uint16_t b, uint16_t y) {
#ifdef WC2_PLANT_BLOCK_INHERIT  // display audit plant: a conversion clears both bitmaps' marks
        rows[b ^ 1][y] = 0;
#endif
        rows[b][y] = 0;
    }
    void queue(uint16_t b) { pending = (int16_t)b; }
    int16_t flip() {
        int16_t b = pending;
        if (b >= 0) {
            shown = (uint16_t)b;
            pending = -1;
        }
        return b;
    }
};
#endif
