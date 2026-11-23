/* INT 67h EMS 4.0 as the reference machine answers it
 * (docs/external-surface.md). */
#include "runtime.h"

#define EMS_FRAME 0xe000
#define EMS_HANDLES 16
#define EMS_PHYS 4

/* Store pages live after the state block (RT_EMS_PAGES): they are the truth.
 * A frame page holds its mapped page's bytes only while it is live (EMS model,
 * docs/translator-design.md): a map writes a live page back and leaves the new
 * one in the store. An ES access to a page in the store goes there directly
 * (rt_ems_es_c); other accesses copy it in first, which the
 * runtime's own accessors (rt_ems_touch, runtime.h) and the translator's guard
 * before every ES access (rt_ems_es) report, or at once while DS or SS
 * addresses it (their accesses are not guarded: rt_ems_segments). A page mapped
 * at two frame pages is two copies (writes through one are not seen through
 * the other): the game's only map site slides a 4-page window, which aliases
 * one page only until the next call. Handles take store pages as DOSBox-X's
 * MEM_AllocatePages does, so after a release a handle's pages can be split
 * across free runs; a release leaves the frame mapped (tests/test_ems.py).
 * Only store pages below RT_EMS_STORE_PAGES have bytes; mapping any other
 * stops (runtime.h). */
#if RT_EMS_PAGES > 256
#error "store page numbers are bytes"
#endif
static uint16_t ems_free = RT_EMS_PAGES;
static uint16_t pages[EMS_HANDLES];   /* 0: free; handle 0 is the operating system's */
static uint8_t page_of[EMS_HANDLES][RT_EMS_PAGES], used[RT_EMS_PAGES];
uint16_t rt_ems_mapped[EMS_PHYS];     /* store page + 1, 0: none */
uint8_t rt_ems_live[EMS_PHYS];        /* the frame page holds the mapped page's bytes */
#define mapped rt_ems_mapped
#define live rt_ems_live
/* AH=47h/48h: a handle's saved frame mappings (DOSBox-X EMM_SavePageMap) */
static uint16_t saved_map[EMS_HANDLES][EMS_PHYS];
static uint8_t saved[EMS_HANDLES];

static uint8_t *store(uint16_t slot)
{
    return rt_guest + 1 + RT_STATE_BYTES + (uint32_t)(slot - 1) * RT_EMS_PAGE;
}

/* DOSBox-X BestMatch(1): the first free run of one page, else the first of
 * the shortest; RT_EMS_PAGES when none. *largest: the longest run. */
static uint16_t free_run(uint16_t *largest)
{
    uint16_t at = RT_EMS_PAGES, best = 0xffff, k = 0;
    *largest = 0;
    while (k < RT_EMS_PAGES) {
        uint16_t first = k;
        while (k < RT_EMS_PAGES && !used[k]) {
            ++k;
        }
        uint16_t n = k - first;
        if (n > *largest) {
            *largest = n;
        }
        if (n && n < best) {
            best = n;
            at = first;
        }
        k += k < RT_EMS_PAGES;
    }
    return at;
}

/* (rt_span itself: the frame is reached here without rt_ems_touch) */
static uint8_t *frame_page(uint8_t phys)
{
    return rt_guest - (lin(EMS_FRAME, 0) + (uint32_t)(phys + 1) * RT_EMS_PAGE) + 1;
}

/* One page. Frame pages and the store share their address mod 4 (both are
 * rt_guest + 1 mod 4), so after the head bytes both run long-aligned. */
static void copy(uint8_t *d, const uint8_t *s)
{
    uint32_t n = RT_EMS_PAGE;
    while (n && ((uintptr_t)d & 3)) {
        *d++ = *s++;
        --n;
    }
    if (n >= 32) {
        uint16_t k = n / 32 - 1;    /* dbra count, at most 511 */
        __asm__ volatile(
            "1:\tmove.l (%0)+,(%1)+\n\tmove.l (%0)+,(%1)+\n\t"
            "move.l (%0)+,(%1)+\n\tmove.l (%0)+,(%1)+\n\t"
            "move.l (%0)+,(%1)+\n\tmove.l (%0)+,(%1)+\n\t"
            "move.l (%0)+,(%1)+\n\tmove.l (%0)+,(%1)+\n\t"
            "dbra %2,1b"
            : "+a"(s), "+a"(d), "+d"(k) : : "memory");
    }
    for (n &= 31; n; --n) {
        *d++ = *s++;
    }
}

static uint8_t map_slot(uint8_t phys, uint16_t slot);

static uint8_t map(uint8_t phys, uint16_t page, uint16_t handle)
{
    if (phys >= EMS_PHYS) {
        return 0x8b;
    }
    if (page != 0xffff && (handle == 0 || handle >= EMS_HANDLES || !pages[handle])) {
        return 0x83;
    }
    if (page != 0xffff && page >= pages[handle]) {
        return 0x8a;
    }
    uint16_t slot = page == 0xffff ? 0 : page_of[handle][page] + 1;
    if (slot > RT_EMS_STORE_PAGES) {
        rt_stop("EMS page outside the store (logical page, store pages)", page, RT_EMS_STORE_PAGES);
    }
    return map_slot(phys, slot);
}

/* The frame page shows its mapped page's bytes from now on. */
static void expose(uint8_t phys)
{
    if (live[phys] || !mapped[phys]) {
        return;
    }
    rt_wrote(lin(EMS_FRAME, 0) + phys * RT_EMS_PAGE, RT_EMS_PAGE);
    copy(frame_page(phys), store(mapped[phys]));
    live[phys] = 1;
}

static int addresses(uint16_t seg, uint8_t phys)
{
    uint32_t first = lin(EMS_FRAME, 0) + phys * RT_EMS_PAGE;
    return lin(seg, 0) <= first + RT_EMS_PAGE - 1 && first <= lin(seg, 0xffff);
}

/* Frame page phys shows store slot (0: unmapped). */
static uint8_t map_slot(uint8_t phys, uint16_t slot)
{
    if (slot && mapped[phys] == slot) {
        /* Write-back then reload of the same page leaves the frame unchanged
         * (every remap writes back before the store is read), unless another
         * frame page holds an alias whose bytes the reload would bring in. */
        int alias = 0;
        for (int k = 0; k < EMS_PHYS; ++k) {
            alias |= k != phys && mapped[k] == slot;
        }
        if (!alias) {
            return 0;
        }
    }
    if (mapped[phys]) {
        /* an unmapped frame page keeps the bytes it showed */
        if (!slot) {
            expose(phys);
        }
        if (live[phys]) {
            copy(store(mapped[phys]), frame_page(phys));
        }
        mapped[phys] = 0;
    }
    live[phys] = 0;
    if (!slot) {
        return 0;
    }
    for (int k = 0; k < EMS_PHYS; ++k) {
        if (mapped[k] == slot && live[k]) {
            copy(store(slot), frame_page(k));   /* an alias's writes reach the new mapping */
        }
    }
    mapped[phys] = slot;
    for (int k = 0; k < EMS_PHYS; ++k) {
        if (mapped[k] == slot && (addresses(G_DS, (uint8_t)k) || addresses(G_SS, (uint8_t)k))) {
            expose((uint8_t)k);
        }
    }
    return 0;
}

/* The runtime is about to touch guest a..a+n-1. Only the frame pages it meets
 * are exposed: the ES guard also reports accesses that miss the frame (ES
 * D001h-DFFFh below it, the word at FFFFh wrapping to the base). */
void rt_ems_touch(uint32_t a, uint32_t n)
{
    uint32_t first = lin(EMS_FRAME, 0), last = first + EMS_PHYS * RT_EMS_PAGE - 1;
    if (!n || a > last || a + n - 1 < first) {
        return;
    }
    uint32_t lo = a < first ? first : a, hi = a + n - 1 > last ? last : a + n - 1;
    for (uint32_t p = (lo - first) / RT_EMS_PAGE; p <= (hi - first) / RT_EMS_PAGE; ++p) {
        expose((uint8_t)p);
    }
}

/* Translator guard (lower.py ems_guard): ES >= D001h before an access of `bytes`
 * at ES:offset; bytes 0: a string instruction, the whole ES window. Returns the
 * displacement the access adds to the ES base (rt_entry.s rt_ems_es): an access
 * that lies within one frame page whose mapped page is in the store only (not
 * live, no live alias) goes to the store page itself, without a copy; anything
 * else has its frame pages copied in and runs on the frame (0). */
int32_t rt_ems_es_c(uint32_t offset, uint32_t bytes)
{
    uint32_t base = lin(G_ES, 0), first = lin(EMS_FRAME, 0);
    offset &= 0xffff;
    if (bytes && offset + bytes <= 0x10000) {
        uint32_t a = base + offset, z = a + bytes - 1;
        if (a >= first && z < first + EMS_PHYS * RT_EMS_PAGE &&
            (a - first) / RT_EMS_PAGE == (z - first) / RT_EMS_PAGE) {
            uint8_t k = (uint8_t)((a - first) / RT_EMS_PAGE);
            int alias = 0;
            for (int j = 0; j < EMS_PHYS; ++j) {
                alias |= j != k && mapped[j] == mapped[k] && live[j];
            }
            if (mapped[k] && !live[k] && !alias) {
                return (int32_t)(store(mapped[k]) - frame_page(k));
            }
        }
    }
    if (!bytes) {
        rt_ems_touch(base, 0x10000);
    } else if (offset + bytes > 0x10000) {        /* the word at FFFFh wraps to 0 */
        rt_ems_touch(base + offset, 0x10000 - offset);
        rt_ems_touch(base, offset + bytes - 0x10000);
    } else {
        rt_ems_touch(base + offset, bytes);
    }
    return 0;
}

/* DS or SS may address the frame (a load of D001h or above, a service, an
 * interrupt's return): their pages are live while they do. */
void rt_ems_segments(void)
{
    for (uint8_t k = 0; k < EMS_PHYS; ++k) {
        if (addresses(G_DS, k) || addresses(G_SS, k)) {
            expose(k);
        }
    }
}

/* Every frame page shows its mapped page (a capture). */
void rt_ems_sync(void)
{
    for (uint8_t k = 0; k < EMS_PHYS; ++k) {
        expose(k);
    }
}

void rt_int67(void)
{
    switch (AH(rt_r.ax)) {
    case 0x40:  /* status */
        break;
    case 0x41:  /* page frame segment */
        rt_r.bx = EMS_FRAME;
        break;
    case 0x42:  /* free pages, and in DX the longest free run (DOSBox-X's "total") */
        rt_r.bx = ems_free;
        free_run(&rt_r.dx);
        break;
    case 0x43: {  /* allocate BX pages; 16 handles (DOSBox-X 200, the game opens 3) */
        uint16_t h = 1, n = rt_r.bx, largest;
        while (h < EMS_HANDLES && pages[h]) {
            ++h;
        }
        if (!n || n > ems_free || h == EMS_HANDLES) {
            SET_AH(rt_r.ax, !n ? 0x89 : n > ems_free ? 0x88 : 0x85);
            return;
        }
        for (uint16_t p = 0; p < n;) {
            for (uint16_t k = free_run(&largest); p < n && k < RT_EMS_PAGES && !used[k]; ++k) {
                used[k] = 1;
                page_of[h][p++] = (uint8_t)k;
            }
        }
        pages[h] = n;
        ems_free -= n;
        rt_r.dx = h;
        break;
    }
    case 0x44:  /* map logical page BX of handle DX at frame page AL */
        SET_AH(rt_r.ax, map(AL(rt_r.ax), rt_r.bx, rt_r.dx));
        return;
    case 0x45:  /* release handle DX; its frame pages stay mapped */
        if (rt_r.dx == 0) {     /* DOSBox-X frees the OS's pages, outside the store */
            rt_unsupported("EMS release of handle 0", 0x67, 0, 0);
            return;
        }
        if (rt_r.dx >= EMS_HANDLES || !pages[rt_r.dx]) {
            SET_AH(rt_r.ax, 0x83);
            return;
        }
        for (uint16_t p = 0; p < pages[rt_r.dx]; ++p) {
            used[page_of[rt_r.dx][p]] = 0;
        }
        ems_free += pages[rt_r.dx];
        pages[rt_r.dx] = 0;
        saved[rt_r.dx] = 0;
        break;
    case 0x46:  /* version 4.0 */
        rt_r.ax = 0x0040;
        return;
    case 0x47:  /* save the frame mappings in handle DX (0: the OS's) */
    case 0x48:  /* restore them */
        if (rt_r.dx >= EMS_HANDLES || (rt_r.dx && !pages[rt_r.dx])) {
            SET_AH(rt_r.ax, 0x83);
            return;
        }
        if (AH(rt_r.ax) == 0x47) {
            if (saved[rt_r.dx]) {
                SET_AH(rt_r.ax, 0x8d);
                return;
            }
            for (int k = 0; k < EMS_PHYS; ++k) {
                saved_map[rt_r.dx][k] = mapped[k];
            }
            saved[rt_r.dx] = 1;
        } else {
            if (!saved[rt_r.dx]) {
                SET_AH(rt_r.ax, 0x8e);
                return;
            }
            saved[rt_r.dx] = 0;
            for (int k = 0; k < EMS_PHYS; ++k) {
                map_slot((uint8_t)k, saved_map[rt_r.dx][k]);
            }
        }
        break;
    default:
        rt_unsupported("EMS function", 0x67, 0, 0);
    }
    SET_AH(rt_r.ax, 0);
}
