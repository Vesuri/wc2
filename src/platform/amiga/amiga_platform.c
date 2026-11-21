/* Platform services for the runtime on AmigaOS: the game's files through
 * dos.library (each call in an I/O window of the takeover, Wc2.cpp), the
 * PIT on a CIA-B timer (none in the frame bench, argument BENCH), the
 * diagnostic key script, the music skip (off; argument MUSIC keeps it off), and the
 * run of the translated program on its own native stack. Game files are read from the current directory (the game's
 * own data files, supplied by the user; from Workbench, the icon's drawer). */
#include <proto/exec.h>
#include <proto/dos.h>
#include <proto/cia.h>
#include <proto/icon.h>
#include <exec/memory.h>
#include <dos/dos.h>
#include <workbench/startup.h>
#include <hardware/cia.h>
#include <hardware/intbits.h>
#include <resources/cia.h>
#include "runtime.h"
#include "platform.h"
#include "amiga_platform.h"
#include "FileDate.h"
#ifdef WC2_REPLAY
#include "replay_clocks.h"
uint16_t replay_pit_count(uint32_t ch);   /* tests/amiga_replay.c */
uint8_t replay_vga_status(void);
uint8_t replay_dsp_status(uint32_t port);
void replay_sb_block(uint32_t linear, uint32_t length, uint32_t rate);
#endif

struct DosLibrary *DOSBase = 0;
struct Library *IconBase = 0;

#define MAX_FILES 16
#define PATH_BYTES 128
#define GUEST_STACK_BYTES 0x10000

static BPTR files[MAX_FILES];
static char file_paths[MAX_FILES][PATH_BYTES];
static uint8_t file_stamped[MAX_FILES], file_modified[MAX_FILES];
static struct DateStamp file_stamps[MAX_FILES];

int32_t amiga_guest_call(void *stack_top);
static void key_script_step(void);
static uint8_t *guest_block = 0;
static uint8_t *guest_stack = 0;

void *plat_alloc(uint32_t bytes)
{
    amiga_io_begin();
    void *p = AllocVec(bytes, MEMF_ANY);
    amiga_io_end();
    return p;
}

void plat_free(void *p)
{
    amiga_io_begin();
    FreeVec(p);
    amiga_io_end();
}

/* WHDLoad's kickfs has no ACTION_CHANGE_MODE or ACTION_SET_FILE_SIZE and
 * crashes on a packet it does not know (docs/whdload.md). A new or emptied
 * file is therefore made with MODE_NEWFILE, closed and opened again with
 * MODE_OLDFILE: DOS permits another open (including an attribute query)
 * while a created file is live, and MODE_NEWFILE starts exclusive. */
static BPTR open_new(const char *path)
{
    BPTR f = Open((CONST_STRPTR)path, MODE_NEWFILE);
    if (!f) {
        return 0;
    }
    Close(f);
    return Open((CONST_STRPTR)path, MODE_OLDFILE);
}

static int32_t open_as(const char *path, LONG mode)
{
    for (int32_t k = 0; k < MAX_FILES; ++k) {
        if (!files[k]) {
            int n = 0;
            while (path[n] && n < PATH_BYTES - 1) {
                file_paths[k][n] = path[n];
                ++n;
            }
            if (path[n]) {
                return -1;
            }
            file_paths[k][n] = 0;
            BPTR f = mode == MODE_NEWFILE ? open_new(path) : Open((CONST_STRPTR)path, mode);
            if (!f) {
                return -1;
            }
            files[k] = f;
            file_stamped[k] = 0;
            file_modified[k] = mode == MODE_NEWFILE;
            return k;
        }
    }
    return -1;
}

/* DOS write of 0 bytes: truncate at the position. The game's C library opens
 * for writing with O_TRUNC so (AX=3D01h, then 40h with CX=0 at position 0):
 * the file is made anew in place, no temporary file or rename. MODE_NEWFILE
 * fails while another handle holds the file on a disk filesystem, which has
 * SetFileSize; kickfs grants it always. Elsewhere only SetFileSize, which
 * kickfs lacks and no reference run needs. */
static int32_t truncate_at(int32_t handle)
{
    if (Seek(files[handle], 0, OFFSET_CURRENT) != 0) {
        return SetFileSize(files[handle], 0, OFFSET_CURRENT) < 0 ? -1 : 0;
    }
    Close(files[handle]);
    files[handle] = open_new(file_paths[handle]);
    if (files[handle]) {
        return 0;
    }
    files[handle] = Open((CONST_STRPTR)file_paths[handle], MODE_OLDFILE);
    return !files[handle] ? -1 : SetFileSize(files[handle], 0, OFFSET_CURRENT) < 0 ? -1 : 0;
}

/* Diagnostic key script (below): the file a step waits for (fNAME), set by
 * the field task, and whether the guest has opened it since. */
static const char *volatile script_file = 0;
static volatile int script_file_n = 0;
static volatile UBYTE script_file_seen = 0;

static void script_opened(const char *path)
{
    const char *name = path, *want = script_file;
    int n = script_file_n;
    for (const char *p = path; *p; ++p) {
        if (*p == '/' || *p == '\\' || *p == ':') {
            name = p + 1;
        }
    }
    if (!want) {
        return;
    }
    int k = 0;
    while (k < n && name[k] && (name[k] | 0x20) == (want[k] | 0x20)) {
        ++k;
    }
    if (k == n && !name[k]) {
        script_file_seen = 1;
    }
}

/* MODE_OLDFILE reads and writes an existing file. */
int32_t plat_open(const char *path, int32_t mode)
{
    (void)mode;
    script_opened(path);
    amiga_io_begin();
    int32_t handle = open_as(path, MODE_OLDFILE);
    amiga_io_end();
    return handle;
}

int32_t plat_create(const char *path)
{
    amiga_io_begin();
    int32_t handle = open_as(path, MODE_NEWFILE);
    amiga_io_end();
    return handle;
}

int32_t plat_write(int32_t handle, const void *buffer, uint32_t length)
{
    amiga_io_begin();
    int32_t n = length ? Write(files[handle], (APTR)buffer, (LONG)length) : truncate_at(handle);
    if (n >= 0) file_modified[handle] = 1;
    amiga_io_end();
    if (!files[handle]) rt_stop("cannot reopen a truncated file", handle, 0);
    return n;
}

int32_t plat_delete(const char *path)
{
    amiga_io_begin();
    int32_t result = DeleteFile((CONST_STRPTR)path) ? 0 : -1;
    amiga_io_end();
    return result;
}

int32_t plat_read(int32_t handle, void *buffer, uint32_t length)
{
    amiga_io_begin();
    int32_t n = Read(files[handle], buffer, (LONG)length);
    amiga_io_end();
    return n;
}

int32_t plat_seek(int32_t handle, int32_t offset, int32_t whence)
{
    static const LONG mode[3] = {OFFSET_BEGINNING, OFFSET_CURRENT, OFFSET_END};
    int32_t position = -1;
    amiga_io_begin();
    if (whence >= 0 && whence <= 2 && Seek(files[handle], offset, mode[whence]) >= 0) {
        position = Seek(files[handle], 0, OFFSET_CURRENT);  /* Seek returns the old position */
    }
    amiga_io_end();
    return position;
}

uint32_t plat_calendar_date(void)
{
#ifdef WC2_REPLAY
    if (REPLAY_CALENDAR_DATE) return REPLAY_CALENDAR_DATE;
#endif
    struct DateStamp stamp;
    uint16_t time, date;
    amiga_io_begin();
    DateStamp(&stamp);
    amiga_io_end();
    amiga_file_date(stamp.ds_Days, stamp.ds_Minute, stamp.ds_Tick, &time, &date);
    return (uint32_t)(1980 + (date >> 9)) << 16 |
           (uint32_t)((date >> 5) & 15) << 8 | (date & 31);
}

void plat_file_stamp(int32_t handle, uint32_t time, uint32_t date)
{
    amiga_date_stamp((uint16_t)time, (uint16_t)date,
                     &file_stamps[handle].ds_Days, &file_stamps[handle].ds_Minute,
                     &file_stamps[handle].ds_Tick);
    file_stamped[handle] = 1;
}

void plat_close(int32_t handle)
{
#ifdef WC2_REPLAY
    if (REPLAY_FILE_DATE && file_modified[handle] && !file_stamped[handle])
        plat_file_stamp(handle, REPLAY_FILE_TIME, REPLAY_FILE_DATE);
#endif
    amiga_io_begin();
    /* After Close, so its filesystem stamp cannot overwrite the DOS timestamp.
     * By the opened path: NameFromFH needs ACTION_PARENT_FH, which kickfs
     * lacks; the current directory changes only around the run. kickfs
     * accepts SetFileDate without setting the date. */
    int closed = Close(files[handle]);
    int stamped = !file_stamped[handle] ||
                  (closed && SetFileDate((CONST_STRPTR)file_paths[handle], &file_stamps[handle]));
    amiga_io_end();
    files[handle] = 0;
    if (!stamped) rt_stop("cannot set file timestamp", handle, 0);
}

int32_t plat_dir_names(const char *dir, char *buffer, uint32_t size)
{
    int32_t bytes = 0;
    amiga_io_begin();
    BPTR lock = Lock((CONST_STRPTR)dir, ACCESS_READ);
    struct FileInfoBlock *fib = AllocDosObject(DOS_FIB, 0);
    if (lock && fib && Examine(lock, fib)) {
        while (ExNext(lock, fib)) {
            int k = 0;
            while (fib->fib_FileName[k] && k <= 12) {
                ++k;
            }
            if (fib->fib_DirEntryType >= 0 || k > 12) {  /* longer: not 8.3 */
                continue;
            }
            if ((uint32_t)bytes + k + 1 <= size) {
                for (int c = 0; c <= k; ++c) {
                    buffer[bytes + c] = fib->fib_FileName[c];
                }
            }
            bytes += k + 1;
        }
    }
    if (fib) {
        FreeDosObject(DOS_FIB, fib);
    }
    if (lock) {
        UnLock(lock);
    }
    amiga_io_end();
    return bytes;
}

int32_t plat_file_info(const char *path, struct plat_file_info *info)
{
    int32_t found = -1;
    amiga_io_begin();
    BPTR lock = Lock((CONST_STRPTR)path, ACCESS_READ);
    struct FileInfoBlock *fib = AllocDosObject(DOS_FIB, 0);
    if (lock && fib && Examine(lock, fib) && fib->fib_DirEntryType < 0) {
        info->size = (uint32_t)fib->fib_Size;
        amiga_file_date(fib->fib_Date.ds_Days, fib->fib_Date.ds_Minute,
                        fib->fib_Date.ds_Tick, &info->dos_time, &info->dos_date);
        found = 0;
    }
    if (fib) {
        FreeDosObject(DOS_FIB, fib);
    }
    if (lock) {
        UnLock(lock);
    }
    amiga_io_end();
    return found;
}

/* PIT channel 0 on a CIA-B timer (D8): one CIA period per PIT period, the
 * latch scaled from the PIT clock (1193182 Hz) to the E-clock: PAL 709379 Hz,
 * 35469/59659 within 1e-5; NTSC 715909 Hz, 3/5 (both colour clock / 5). The
 * interrupt runs the guest handler at once when the runtime allows it
 * (docs/irq-plan.md I6), with EXTER acknowledged and the mask lowered to 2 so
 * the vertical blank preempts a long tick (a nested tick is posted); else it
 * posts vector 08h for the next poll point. Replay builds post only
 * (deliveries at the recorded polls). */
#define CIAB ((volatile struct CIA *)0xbfd000)
static struct Library *cia_base = 0;
static struct Interrupt cia_interrupt;
static WORD cia_bit = -1;

/* CIA ticks, and of them those run at once (fixtures: amiga/display_audit.gdb). */
volatile ULONG amiga_ticks = 0, amiga_ticks_async = 0;

static ULONG cia_tick(void)
{
    ++amiga_ticks;
    if (rt_sfx_capturing) {
        return 0;               /* the effect capture holds the tick: game time pauses */
    }
#ifndef WC2_SYNC
    /* Production has no poll checks (docs/irq-plan.md I8): ticks posted while
     * IRQ0 could not run go first, then this one. */
    int current = rt_irq0_ready();  /* else this tick waits behind posted ones */
    if (current || rt_irq0_take()) {
        UWORD sr;
        *(volatile UWORD *)0xdff09c = INTF_EXTER;
        __asm__ volatile("move.w %%sr,%0" : "=d"(sr) : : "memory");
        __asm__ volatile("move.w %0,%%sr" : : "d"((UWORD)((sr & ~0x0700) | 0x0200)) : "memory");
        for (;;) {
            rt_irq0_running = 1;
            ++amiga_ticks_async;
            rt_irq_interrupt();
            if (rt_irq0_take()) {
                continue;
            }
            if (!current && rt_irq0_ready()) {
                current = 1;
                continue;
            }
            break;
        }
        __asm__ volatile("move.w %0,%%sr" : : "d"(sr) : "memory");
        if (current) {
            return 0;
        }
    }
#endif
    rt_irq_ring[rt_irq_tail % RT_IRQ_RING] = 8;
    ++rt_irq_tail;
    RT_RAISE_IRQ();
    return 0;
}

static void cia_load(uint32_t divisor)
{
    uint32_t latch = amiga_ntsc ? (divisor * 3u + 2u) / 5u : (divisor * 35469u + 29829u) / 59659u;
    volatile UBYTE *cr = cia_bit == CIAICRB_TA ? &CIAB->ciacra : &CIAB->ciacrb;
    volatile UBYTE *lo = cia_bit == CIAICRB_TA ? &CIAB->ciatalo : &CIAB->ciatblo;
    volatile UBYTE *hi = cia_bit == CIAICRB_TA ? &CIAB->ciatahi : &CIAB->ciatbhi;
    *cr &= cia_bit == CIAICRB_TA ? 0xc0 : 0x80;    /* stop; keep TOD/serial bits */
    *lo = (UBYTE)latch;
    *hi = (UBYTE)(latch >> 8);
    *cr |= CIACRAF_LOAD | CIACRAF_START;          /* continuous */
}

/* The DSP block's end (plat_sb_block) on CIA-B's other timer, one-shot, in
 * runs of at most FFFFh E-clocks: length / rate after the 14h command (the
 * reference acknowledged IRQ 7 within 3.0 ms of it, docs/pc-reference-loop.md).
 * Production then runs INT 0Fh's guest handler at once when the runtime allows
 * it (machine.c rt_irq7_ready), as cia_tick runs IRQ0's, else retries after
 * SB_RETRY E-clocks (about 1 ms); the sync bench posts vector 0Fh for the next
 * poll point. No sound yet (open-work 19). */
#define SB_RETRY 709u
static struct Interrupt sb_interrupt;
static WORD sb_bit = -1;
static volatile uint32_t sb_left;  /* E-clocks of the block still to time */
static volatile UBYTE sb_due;      /* the block's IRQ 7 is not yet delivered */
/* Blocks timed, IRQ 7 tries the runtime deferred, and the most for one block
 * (fixtures: each try is SB_RETRY E-clocks late). */
volatile ULONG amiga_sb_blocks = 0, amiga_sb_retries = 0, amiga_sb_retry_max = 0;
#ifndef WC2_SYNC
static ULONG sb_tries;
#endif

static void sb_load(uint32_t ticks)
{
    volatile UBYTE *cr = sb_bit == CIAICRB_TA ? &CIAB->ciacra : &CIAB->ciacrb;
    volatile UBYTE *lo = sb_bit == CIAICRB_TA ? &CIAB->ciatalo : &CIAB->ciatblo;
    volatile UBYTE *hi = sb_bit == CIAICRB_TA ? &CIAB->ciatahi : &CIAB->ciatbhi;
    if (ticks == 0) {
        ticks = 1;
    }
    *cr &= sb_bit == CIAICRB_TA ? 0xc0 : 0x80;    /* stop; keep TOD/serial bits */
    *lo = (UBYTE)ticks;
    *hi = (UBYTE)(ticks >> 8);
    *cr |= CIACRAF_LOAD | CIACRAF_RUNMODE | CIACRAF_START;  /* one-shot */
}

static void sb_arm(void)
{
    uint32_t run = sb_left > 0xffffu ? 0xffffu : sb_left;
    sb_left -= run;
    sb_load(run);
}

static ULONG sb_timer(void)
{
    if (sb_left) {
        sb_arm();
        return 0;
    }
    if (!sb_due) {
        return 0;
    }
#ifdef WC2_SYNC
    sb_due = 0;
    rt_irq_ring[rt_irq_tail % RT_IRQ_RING] = 0x0f;
    ++rt_irq_tail;
    RT_RAISE_IRQ();
#else
    if (!rt_irq7_ready()) {
        ++amiga_sb_retries;
        ++sb_tries;
        sb_load(SB_RETRY);
        return 0;
    }
    if (sb_tries > amiga_sb_retry_max) {
        amiga_sb_retry_max = sb_tries;
    }
    sb_tries = 0;
    sb_due = 0;
    UWORD sr;
    *(volatile UWORD *)0xdff09c = INTF_EXTER;
    __asm__ volatile("move.w %%sr,%0" : "=d"(sr) : : "memory");
    __asm__ volatile("move.w %0,%%sr" : : "d"((UWORD)((sr & ~0x0700) | 0x0200)) : "memory");
    rt_irq0_running = 1;
    rt_irq7_interrupt();            /* may start the next block (plat_sb_block) */
    __asm__ volatile("move.w %0,%%sr" : : "d"(sr) : "memory");
#endif
    return 0;
}

static int timer_open(void)
{
    cia_base = (struct Library *)OpenResource((CONST_STRPTR)CIABNAME);
    if (!cia_base) {
        return 0;
    }
    cia_interrupt.is_Node.ln_Type = NT_INTERRUPT;
    cia_interrupt.is_Node.ln_Name = (char *)"WC2 PIT";
    cia_interrupt.is_Code = (void (*)(void))cia_tick;
    for (WORD bit = CIAICRB_TA; bit <= CIAICRB_TB; ++bit) {
        if (!AddICRVector(cia_base, bit, &cia_interrupt)) {
            cia_bit = bit;
            cia_load(0x10000);
            sb_interrupt.is_Node.ln_Type = NT_INTERRUPT;
            sb_interrupt.is_Node.ln_Name = (char *)"WC2 DSP block";
            sb_interrupt.is_Code = (void (*)(void))sb_timer;
            WORD other = bit == CIAICRB_TA ? CIAICRB_TB : CIAICRB_TA;
            if (!AddICRVector(cia_base, other, &sb_interrupt)) {
                sb_bit = other;     /* else a DSP block stops (plat_sb_block) */
            }
            return 1;
        }
    }
    return 0;
}

static void timer_close(void)
{
    if (sb_bit >= 0) {
        *(sb_bit == CIAICRB_TA ? &CIAB->ciacra : &CIAB->ciacrb) &= ~CIACRAF_START;
        RemICRVector(cia_base, sb_bit, &sb_interrupt);
        sb_bit = -1;
    }
    if (cia_bit >= 0) {
        *(cia_bit == CIAICRB_TA ? &CIAB->ciacra : &CIAB->ciacrb) &= ~CIACRAF_START;
        RemICRVector(cia_base, cia_bit, &cia_interrupt);
        cia_bit = -1;
    }
}

void plat_timer_rate(uint32_t divisor)
{
    if (cia_bit >= 0) {
        Disable();
        cia_load(divisor);
        Enable();
    }
}

/* PIT channel 0 from the CIA timer that stands in for it: the CIA counts its
 * latch down once per tick, the PIT (mode 3, as the game programs it) its
 * divisor down by two twice per tick. Other channels stop (ports.c latches
 * channel 0 only). */
uint16_t plat_pit_count(uint32_t ch)
{
#ifdef WC2_REPLAY
    return replay_pit_count(ch);    /* the reference's reads (tests/amiga_replay.c) */
#else
    if (ch != 0 || cia_bit < 0) {
        rt_stop("PIT count without the CIA timer (channel)", ch, 0);
    }
    volatile UBYTE *lo = cia_bit == CIAICRB_TA ? &CIAB->ciatalo : &CIAB->ciatblo;
    volatile UBYTE *hi = cia_bit == CIAICRB_TA ? &CIAB->ciatahi : &CIAB->ciatbhi;
    uint32_t divisor = rt_pit_divisor;
    uint32_t latch = amiga_ntsc ? (divisor * 3u + 2u) / 5u : (divisor * 35469u + 29829u) / 59659u;
    UBYTE h, l;
    do {
        h = *hi;
        l = *lo;
    } while (h != *hi);
    uint32_t left = (uint32_t)(h << 8 | l);         /* CIA counts this tick still has */
    uint32_t count = (2u * left * divisor / (latch ? latch : 1)) % divisor;
    return (uint16_t)(count & ~1u);
#endif
}

/* VGA input status from the beam: bit 3 (and 0) in the vertical blank, bit 0
 * in the horizontal blank, around the 200-line display window. */
uint8_t plat_vga_status(void)
{
#ifdef WC2_REPLAY
    return replay_vga_status();     /* the reference's reads (tests/amiga_replay.c) */
#else
    ULONG beam = *(volatile ULONG *)0xdff004;       /* VPOSR:VHPOSR */
    UWORD v = (UWORD)((beam >> 8) & 0x1ff), h = (UWORD)(beam & 0xff);
    UWORD top = AMIGA_TOP_LINE;
    int vblank = v < top || v >= top + 200;
    return (uint8_t)((vblank ? 0x09 : 0) | (h < 0x38 || h >= 0xd8 ? 0x01 : 0));
#endif
}

/* The DSP answers at once: the model's status (ports.c). */
uint8_t plat_dsp_status(uint32_t port, uint32_t value)
{
#ifdef WC2_REPLAY
    (void)value;
    return replay_dsp_status(port);     /* the reference's reads (tests/amiga_replay.c) */
#else
    (void)port;
    return (uint8_t)value;
#endif
}

/* A DSP block is timed silently and ends with IRQ 7 (sb_timer); speech on
 * Paula is open-work 19. The diagnostic replay checks the block against the
 * reference's and replays its IRQ 7. */
void plat_sb_block(uint32_t linear, uint32_t length, uint32_t rate)
{
#ifdef WC2_REPLAY
    replay_sb_block(linear, length, rate);
#else
    if (sb_bit < 0 || rate == 0) {
        rt_stop("Sound Blaster block without the CIA-B block timer (linear, length)", linear, length);
    }
    /* E-clocks per byte in 24.8: rate >= 3906 Hz (time constant 0) keeps
     * length (<= 65536) times it inside 32 bits */
    uint32_t eclock = amiga_ntsc ? 715909u : 709379u;
    uint32_t ticks = length * ((eclock << 8) / rate) >> 8;
    Disable();
    sb_due = 1;
    sb_left = ticks;
    sb_arm();
    Enable();
    ++amiga_sb_blocks;
#endif
}

/* Diagnostic key script (argument KEYS=when:key,..., quoted when it holds
 * ax=/ay=: ReadArgs ends an unquoted item at '=' and the start fails; when is a frame from
 * the start, or pN: N guest mouse reads after the previous step, which waits
 * for a screen that is polling rather than for a time the host load moves;
 * kN: N guest keyboard polls after the previous step (rt_key_polls: a prompt
 * that reads keys, as pN for a screen that reads the mouse); dN: N frames after the previous step;
 * tN: N CIA ticks after the previous step (the guest timer's rate: a reference
 * milestone's WC2.EXE+fd10#N counts, reference/milestones.csv); fNAME: the guest opens file NAME
 * after the previous step (a screen's own data: the reference's open order);
 * uNAME:KEY: KEY now and every SCRIPT_REPEAT frames until the guest opens NAME
 * (Esc through a cinematic's scenes, however long each takes to load);
 * keys a-z 0-9 enter esc space up down left right or $hex raw codes, mouse
 * buttons lmb rmb, port 2's stick ju jd jl jr (directions) jf jg (buttons 1
 * and 2), alt+KEY, ctrl+KEY or shift+KEY with the left Alt, Ctrl or Shift held around it, a held step name*N (N frames), the proportional stick's pot counts
 * ax=N ay=N (0-255, kept until changed; ax=- the pots again),
 * mouse motion mx+N mx-N my+N my-N counts; shot and quit call
 * amiga_script_mark for a debugger fixture; unknown names are logged at the
 * start and skipped): fed from the field task at each vertical blank into
 * the keyboard and mouse paths of Input.cpp; a key
 * is released 5 frames after it is pressed, a button once the guest has
 * also read the mouse twice (buttons are polled levels, keys reach the BIOS
 * buffer). */
#define SCRIPT_LMB 0x100
#define SCRIPT_RMB 0x101
#define SCRIPT_JOY 0x200            /* | the amiga_joystick_script bit */
static ULONG script_joystick = 0;
static const char *key_script = 0;
static ULONG key_up_frame = 0;
static ULONG key_up_reads = 0;
static ULONG step_reads = 0;    /* amiga_mouse_reads at the previous step */
static ULONG step_frame = 0;    /* amiga_frames at the previous step */
static ULONG step_polls = 0;    /* rt_key_polls at the previous step */
static ULONG step_ticks = 0;    /* amiga_ticks at the previous step */
#define SCRIPT_REPEAT 60
static ULONG repeat_frame = 0;  /* amiga_frames at a u step's last press */
static int key_up = -1;         /* the held raw key or SCRIPT_LMB/RMB */
static int key_mod = -1;        /* the modifier held around it */
#define RAW_LALT 0x64
#define RAW_CTRL 0x63
#define RAW_LSHIFT 0x60

/* alt+KEY or ctrl+KEY: the modifier's raw code, the name advanced past it;
 * -1 none. */
static int modifier(const char **name, int *n)
{
    static const struct { char word[7]; UBYTE raw; } mods[3] = {
        {"alt+", RAW_LALT}, {"ctrl+", RAW_CTRL}, {"shift+", RAW_LSHIFT}};
    for (int m = 0; m < 3; ++m) {
        int k = 0;
        while (mods[m].word[k] && k < *n && (*name)[k] == mods[m].word[k]) {
            ++k;
        }
        if (!mods[m].word[k] && *n > k) {
            *name += k;
            *n -= k;
            return mods[m].raw;
        }
    }
    return -1;
}

void __attribute__((noinline)) amiga_script_mark(int quit)
{
    __asm__ volatile("" : : "r"(quit) : "memory");
}

static void script_event(int code, int up)
{
    if (code == SCRIPT_LMB || code == SCRIPT_RMB) {
        amiga_mouse_script_buttons(up ? 0 : code == SCRIPT_LMB ? 1 : 2);
    } else if (code >= SCRIPT_JOY) {
        ULONG bit = 1u << (code - SCRIPT_JOY);
        script_joystick = up ? script_joystick & ~bit : script_joystick | bit;
        amiga_joystick_script(script_joystick);
    } else {
        amiga_key(code, up);
    }
}

static int named(const char *name, int n, const char *word)
{
    int k = 0;
    while (k < n && word[k] == name[k]) {
        ++k;
    }
    return k == n && !word[k];
}

static int raw_of(const char *name, int n)
{
    static const char rows[4][11] = {"1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"};
    static const UBYTE base[4] = {0x01, 0x10, 0x20, 0x31};
    if (n == 1) {
        for (int r = 0; r < 4; ++r) {
            for (int k = 0; rows[r][k]; ++k) {
                if (rows[r][k] == name[0]) {
                    return base[r] + k;
                }
            }
        }
    }
    static const char *const stick[6] = {"ju", "jd", "jl", "jr", "jf", "jg"};
    for (int k = 0; k < 6; ++k) {
        if (named(name, n, stick[k])) return SCRIPT_JOY + k;
    }
    if (named(name, n, "up")) return 0x4c;
    if (named(name, n, "down")) return 0x4d;
    if (named(name, n, "right")) return 0x4e;
    if (named(name, n, "left")) return 0x4f;
    if (named(name, n, "enter")) return 0x44;
    if (named(name, n, "esc")) return 0x45;
    if (named(name, n, "space")) return 0x40;
    if (named(name, n, "lmb")) return SCRIPT_LMB;
    if (named(name, n, "rmb")) return SCRIPT_RMB;
    if (n == 3 && name[0] == '$') {
        int v = 0;
        for (int k = 1; k < 3; ++k) {
            char c = name[k];
            v = v * 16 + (c <= '9' ? c - '0' : (c | 0x20) - 'a' + 10);
        }
        return v;
    }
    return -1;
}

static int motion(const char *name, int n)
{
    return n > 3 && name[0] == 'm' && (name[1] == 'x' || name[1] == 'y') &&
           (name[2] == '+' || name[2] == '-');
}

static int axis(const char *name, int n)
{
    return n > 3 && name[0] == 'a' && (name[1] == 'x' || name[1] == 'y') && name[2] == '=';
}

/* A step's name without its hold suffix *N; *hold the frames (5 without). */
static int held(const char *name, int n, ULONG *hold)
{
    *hold = 5;
    for (int k = 0; k < n; ++k) {
        if (name[k] == '*') {
            ULONG v = 0;
            for (int j = k + 1; j < n && name[j] >= '0' && name[j] <= '9'; ++j) {
                v = v * 10 + (ULONG)(name[j] - '0');
            }
            *hold = v;
            return k;
        }
    }
    return n;
}

static int known(const char *name, int n)
{
    ULONG hold;
    modifier(&name, &n);
    return motion(name, n) || axis(name, n) || named(name, n, "shot") ||
           named(name, n, "quit") || raw_of(name, held(name, n, &hold)) >= 0;
}

/* At the start (main program): the field task cannot log. */
static void key_script_check(void)
{
    for (const char *p = key_script; p && *p > ' ';) {
        while (*p > ' ' && *p != ',' && *p != ':') {
            ++p;
        }
        const char *name = *p == ':' ? ++p : p;
        while (*p > ' ' && *p != ',') {
            ++p;
        }
        if (!known(name, (int)(p - name))) {
            plat_log("WC2 KEYS: unknown key");
        }
        p += *p == ',';
    }
}

static void script_press(const char *name, int n)
{
    ULONG hold;
    int mod = modifier(&name, &n);
    int code = raw_of(name, held(name, n, &hold));
    if (code < 0) {
        return;
    }
    if (mod >= 0) {
        script_event(mod, 0);
        key_mod = mod;
    }
    script_event(code, 0);
    key_up = code;
    key_up_frame = amiga_frames + hold;
    key_up_reads = amiga_mouse_reads + (code == SCRIPT_LMB || code == SCRIPT_RMB ? 2 : 0);
}

/* A u step's KEY (after the ':' at p), every SCRIPT_REPEAT frames. */
static void script_repeat(const char *p)
{
    if (amiga_frames - repeat_frame < SCRIPT_REPEAT) {
        return;
    }
    repeat_frame = amiga_frames;
    const char *name = *p == ':' ? p + 1 : p;
    const char *end = name;
    while (*end > ' ' && *end != ',') {
        ++end;
    }
    script_press(name, (int)(end - name));
}

/* A u step is done: past its KEY, the baselines for the next step. */
static void script_skip(const char *p)
{
    while (*p > ' ' && *p != ',') {
        ++p;
    }
    key_script = *p == ',' ? p + 1 : p;
    step_reads = amiga_mouse_reads;
    step_frame = amiga_frames;
    step_polls = rt_key_polls;
    step_ticks = amiga_ticks;
}

static void key_script_step(void)
{
    if (key_up >= 0 && amiga_frames >= key_up_frame && amiga_mouse_reads >= key_up_reads) {
        script_event(key_up, 1);
        key_up = -1;
        if (key_mod >= 0) {
            script_event(key_mod, 1);
            key_mod = -1;
        }
    }
    if (!key_script || *key_script <= ' ' || key_up >= 0) {
        return;
    }
    ULONG when = 0;
    const char *p = key_script;
    char kind = *p >= '0' && *p <= '9' ? 0 : *p++;
    if (kind == 'f' || kind == 'u') {
        const char *file = p;
        while (*p > ' ' && *p != ',' && *p != ':') {
            ++p;
        }
        if (script_file != file) {
            script_file_seen = 0;
            script_file_n = (int)(p - file);
            script_file = file;
            if (kind == 'u') {
                repeat_frame = amiga_frames - SCRIPT_REPEAT;
            }
        }
        if (!script_file_seen) {
            if (kind == 'u') {
                script_repeat(p);
            }
            return;
        }
        script_file = 0;
        if (kind == 'u') {
            script_skip(p);
            return;
        }
    } else {
        while (*p >= '0' && *p <= '9') {
            when = when * 10 + (ULONG)(*p++ - '0');
        }
        if (kind == 'p' ? amiga_mouse_reads - step_reads < when :
                kind == 'k' ? rt_key_polls - step_polls < when :
                kind == 't' ? amiga_ticks - step_ticks < when :
                kind == 'd' ? amiga_frames - step_frame < when : amiga_frames < when) {
            return;
        }
    }
    step_reads = amiga_mouse_reads;
    step_frame = amiga_frames;
    step_polls = rt_key_polls;
    step_ticks = amiga_ticks;
    const char *name = *p == ':' ? ++p : p;
    while (*p > ' ' && *p != ',') {
        ++p;
    }
    int n = (int)(p - name);
    key_script = *p == ',' ? p + 1 : p;
    if (motion(name, n)) {
        WORD v = 0;
        for (int k = 3; k < n; ++k) {
            v = (WORD)(v * 10 + name[k] - '0');
        }
        v = name[2] == '-' ? (WORD)-v : v;
        amiga_mouse_move(name[1] == 'x' ? v : 0, name[1] == 'y' ? v : 0);
        return;
    }
    if (axis(name, n)) {
        int v = 0;
        for (int k = 3; k < n && name[k] >= '0' && name[k] <= '9'; ++k) {
            v = v * 10 + name[k] - '0';
        }
        amiga_joystick_script_axis(name[1] == 'y', name[3] == '-' ? -1 : v);
        return;
    }
    if (named(name, n, "shot") || named(name, n, "quit")) {
        amiga_script_mark(name[0] == 'q');
        return;
    }
    script_press(name, n);
}

/* Effect capture (runtime.h rt_sfx_*): every effect when Audio has its Chip;
 * the prerender follows in Audio (fx_play.c, owner decision D13). */
extern int amiga_audio_effect_wanted(uint8_t id);
extern void amiga_audio_effects(void);
__attribute__((aligned(4))) volatile uint32_t amiga_sfx_capture_fields;  /* the capture's fields (diagnostics) */
int plat_sfx_wanted(uint8_t id)
{
    if (id == 1) {
        amiga_sfx_capture_fields = amiga_frames;
    }
    return amiga_audio_effect_wanted(id);
}

void plat_sfx_captured(void)
{
    amiga_sfx_capture_fields = amiga_frames - amiga_sfx_capture_fields;
    amiga_audio_effects();
}

void plat_service(void)
{
    key_script_step();
    amiga_audio_service();
}

/* Shell start: the Shell's output; Workbench start: none. */
void plat_console(const void *buffer, uint32_t length)
{
    amiga_io_begin();
    BPTR out = Output();
    if (out && length) {
        Write(out, (APTR)buffer, (LONG)length);
    }
    amiga_io_end();
}

void plat_log(const char *line)
{
    LONG n = 0;
    while (line[n]) {
        ++n;
    }
    amiga_io_begin();
    BPTR out = Output();
    if (out) {
        Write(out, (APTR)line, n);
        Write(out, (APTR)"\n", 1);
    }
    amiga_io_end();
}

/* Workbench start (L84): the icon's drawer becomes the current directory
 * (a Shell's is its own) and the icon's tool types are the arguments, the
 * same keywords; KEYS= is copied, the icon is freed before the run. The
 * release image reads ANALOGJOYSTICK only. */
static BPTR wb_old_dir = 0;
static char *wb_keys = 0;
static ULONG wb_keys_bytes = 0;

static int wb_options(void)
{
    struct WBArg *tool = amiga_wb_startup->sm_ArgList;
    wb_old_dir = CurrentDir(tool->wa_Lock);
    IconBase = OpenLibrary((CONST_STRPTR)"icon.library", 37);
    if (!IconBase) {
        return 1;
    }
    struct DiskObject *icon = GetDiskObject((STRPTR)tool->wa_Name);
    int ok = 1;
    if (icon) {
        STRPTR *types = (STRPTR *)icon->do_ToolTypes;
        if (FindToolType(types, (STRPTR)"ANALOGJOYSTICK")) rt_joystick = 1;
#ifndef WC2_RELEASE
        if (FindToolType(types, (STRPTR)"BENCH")) rt_bench = 1;
        if (FindToolType(types, (STRPTR)"MUSIC")) rt_music_skip = 0;
        const char *keys = (const char *)FindToolType(types, (STRPTR)"KEYS");
        if (keys) {
            ULONG n = 0;
            while (keys[n]) {
                ++n;
            }
            wb_keys_bytes = n + 1;
            wb_keys = (char *)AllocMem(wb_keys_bytes, MEMF_ANY);
            if (wb_keys) {
                for (ULONG k = 0; k < wb_keys_bytes; ++k) {
                    wb_keys[k] = keys[k];
                }
                key_script = wb_keys;
            } else {
                plat_log("WC2 not enough memory");
                ok = 0;
            }
        }
#endif
        FreeDiskObject(icon);
    }
    CloseLibrary(IconBase);
    IconBase = 0;
    return ok;
}

/* Shell start: ReadArgs, so the keywords are case-insensitive, `?` prompts
 * with the template and a bad line fails with the DOS error. ReadArgs reads
 * the line from Input()'s buffer, where the Shell and the WHDLoad slave's
 * RunCommand put it. KEYS points into the RDArgs until the close. */
static struct RDArgs *shell_args = 0;

#ifdef WC2_RELEASE
/* The release image (make amiga-release): the player's options only. */
#define SHELL_TEMPLATE "ANALOGJOYSTICK/S"
enum { ARG_ANALOGJOYSTICK, ARG_COUNT };
#else
#define SHELL_TEMPLATE "ANALOGJOYSTICK/S,MUSIC/S,BENCH/S,KEYS/K"
enum { ARG_ANALOGJOYSTICK, ARG_MUSIC, ARG_BENCH, ARG_KEYS, ARG_COUNT };
#endif

static int shell_options(void)
{
    LONG values[ARG_COUNT] = {0};
    shell_args = ReadArgs((CONST_STRPTR)SHELL_TEMPLATE, values, 0);
    if (!shell_args) {
        amiga_io_begin();
        PrintFault(IoErr(), (CONST_STRPTR)"WC2");
        amiga_io_end();
        return 0;
    }
    if (values[ARG_ANALOGJOYSTICK]) rt_joystick = 1;   /* proportional stick in port 2; joystick argument Y */
#ifndef WC2_RELEASE
    if (values[ARG_MUSIC]) rt_music_skip = 0;   /* diagnostic: music records start their songs */
    if (values[ARG_BENCH]) rt_bench = 1;        /* frame bench: ticks from guest progress, no CIA timer */
    if (values[ARG_KEYS]) key_script = (const char *)values[ARG_KEYS];
#endif
    return 1;
}

/* The empty image (no translated program yet): fields the takeover stays live. */
#define EMPTY_FIELDS 200
static int empty_image = 0;

int amiga_guest_open(void)
{
    DOSBase = (struct DosLibrary *)OpenLibrary((CONST_STRPTR)"dos.library", 39);
    if (!DOSBase) {
        return 0;
    }
    if (amiga_wb_startup && !wb_options()) {
        return 0;
    }
    if (!amiga_wb_startup && !shell_options()) {
        return 0;
    }
    key_script_check();
    rt_sfx_prerender_on = 1;    /* effects prerendered at the first effect start (runtime.h) */
    if (!dispatch_count) {
        /* WC2 before port-plan P1.4: no translated program. The takeover runs
         * EMPTY_FIELDS fields and hands back (make smoke). */
        empty_image = 1;
        plat_log("WC2 empty image: no translated program");
        return 1;
    }
#ifndef WC2_SYNC
    if (rt_bench) {         /* production takes no tick at a poll point (irq-plan I8) */
        plat_log("WC2 frame bench needs the sync image (make amiga-sync)");
        return 0;
    }
    rt_frame_cap = 1;       /* one game frame per field (runtime.h) */
    rt_mouse_scale = 1;     /* flight mouse at a fixed frame time (runtime.h) */
    rt_mickeys_y = 1;       /* vertical counts 1:1, as a real PC mouse (runtime.h) */
#endif
    /* Guest RAM, the state block below it and the EMS store after it; Fast RAM
     * when present (D15). */
    guest_block = (uint8_t *)AllocMem(RT_STATE_BYTES + RT_GUEST_BYTES + RT_EMS_BYTES, MEMF_ANY | MEMF_CLEAR);
    guest_stack = (uint8_t *)AllocMem(GUEST_STACK_BYTES, MEMF_ANY);
    if (!guest_block || !guest_stack) {
        plat_log("WC2 not enough memory");
        return 0;
    }
    plat_log("WC2 guest start");
    rt_start(guest_block);
#ifdef WC2_REPLAY
    (void)timer_open;
    plat_log("WC2 diagnostic reference replay");
#else
    if (rt_bench) {
        plat_log("WC2 frame bench");
    } else if (!timer_open()) {
        plat_log("WC2 no CIA-B timer");
    }
#endif
    return 1;
}

long amiga_guest_run(void)
{
    if (empty_image) {
        uint32_t start = amiga_frames;
        while (amiga_frames - start < EMPTY_FIELDS) {
        }
        return 0;
    }
    return amiga_guest_call(guest_stack + GUEST_STACK_BYTES);
}

void amiga_guest_close(void)
{
    timer_close();
    rt_dos_close();
    for (int32_t k = 0; k < MAX_FILES; ++k) {
        if (files[k]) {
            plat_close(k);
        }
    }
    if (guest_stack) {
        FreeMem(guest_stack, GUEST_STACK_BYTES);
        guest_stack = 0;
    }
    if (guest_block) {
        FreeMem(guest_block, RT_STATE_BYTES + RT_GUEST_BYTES + RT_EMS_BYTES);
        guest_block = 0;
    }
    if (wb_keys) {
        FreeMem(wb_keys, wb_keys_bytes);
        wb_keys = 0;
    }
    if (shell_args) {
        FreeArgs(shell_args);
        shell_args = 0;
    }
    if (DOSBase && amiga_wb_startup) {
        CurrentDir(wb_old_dir);
    }
    if (DOSBase) {
        CloseLibrary((struct Library *)DOSBase);
        DOSBase = 0;
    }
}
