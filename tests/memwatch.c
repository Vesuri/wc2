/* Memory-access filter for tests/host_run.py: Unicorn memory hooks in C that
 * pass an access to the Python hook only when a byte it touches is one the
 * host run's checks act on, so Python sees exactly the accesses it acts on
 * (a superset: the Python hooks keep their own tests).
 *
 * Reads: a machine byte (host_run.machine_ranges), a byte the IRQ monitor
 * marks with any of `rbits` (irq_monitor.WRITTEN: a handler-written byte).
 * Writes: a masked dead-stack byte, the dead PUSHF word's address, a byte the
 * monitor marks with any of `wbits` (ACCESSED; BUFFER, a byte a handler read
 * through a runtime-class pointer). Inside a delivered handler (`all`) every access goes to Python.
 * VRAM writes in mode 13h (BDA 0449h) are recorded here, one byte per pixel.
 * Guest memory is reversed: linear byte a is at address top - a. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef bool (*mem_cb)(void *uc, int type, uint64_t addr, int size, int64_t value, void *user);
typedef int (*mem_read_fn)(void *uc, uint64_t addr, void *buf, size_t size);

struct watch {
    uint64_t top;
    uint64_t size;              /* guest bytes */
    const uint8_t *mon;         /* the monitor's mask, NULL before its layout */
    const uint8_t *machine;
    const uint8_t *dead;        /* masked dead-stack bytes */
    uint8_t *vram;              /* 64000: stored in mode 13h since the last present */
    mem_cb read_cb;
    mem_cb write_cb;
    mem_read_fn mem_read;
    int64_t dead_flags;         /* the dead PUSHF word's linear address, -1 none */
    int64_t all;
    int64_t rbits, wbits;
    int64_t seen[2], passed[2]; /* reads, writes */
};

bool watch_read(void *uc, int type, uint64_t addr, int size, int64_t value, struct watch *w)
{
    uint64_t lin = w->top - addr - (uint64_t)size + 1;
    ++w->seen[0];
    if (!w->all) {
        bool hit = false;
        for (int k = 0; k < size && !hit; ++k) {
            uint64_t a = lin + (uint64_t)k;
            hit = a < w->size && (w->machine[a] || (w->mon && (w->mon[a] & w->rbits)));
        }
        if (!hit) {
            return true;
        }
    }
    ++w->passed[0];
    return w->read_cb(uc, type, addr, size, value, NULL);
}

bool watch_write(void *uc, int type, uint64_t addr, int size, int64_t value, struct watch *w)
{
    int64_t lin = (int64_t)(w->top - addr - (uint64_t)size + 1);
    ++w->seen[1];
    if (!w->all && !(w->dead_flags >= lin && w->dead_flags < lin + size)) {
        bool hit = false;
        for (int k = 0; k < size && !hit; ++k) {
            uint64_t a = (uint64_t)lin + (uint64_t)k;
            hit = a < w->size && (w->dead[a] || (w->mon && (w->mon[a] & w->wbits)));
        }
        if (!hit) {
            return true;
        }
    }
    ++w->passed[1];
    return w->write_cb(uc, type, addr, size, value, NULL);
}

bool watch_vram(void *uc, int type, uint64_t addr, int size, int64_t value, struct watch *w)
{
    uint8_t mode = 0;
    (void)type;
    (void)value;
    if (w->mem_read(uc, w->top - 0x449, &mode, 1) || mode != 0x13) {
        return true;
    }
    int64_t off = (int64_t)(w->top - addr - (uint64_t)size + 1) - 0xA0000;
    for (int k = 0; k < size; ++k) {
        if (off + k >= 0 && off + k < 64000) {
            w->vram[off + k] = 1;
        }
    }
    return true;
}
