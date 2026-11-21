; WHDLoad/Kickstart 3.1 launcher for the Amiga port. Cross-assembled with vasm.
; The executable uses Exec/graphics/DOS; kickfs supplies ordinary file access.
; From Secret Weapons of the Luftwaffe's slave (docs/upstream.md). Custom1 selects
; the proportional joystick: the slave passes the program's ANALOGJOYSTICK
; argument (docs/amiga-arch.md) through RunCommand, as a Shell does, so the same
; executable runs from a Shell.

        INCLUDE whdload.i
        INCLUDE whdmacros.i

; Sizes from MemFree measurements (docs/whdload.md, Memory): code, guest RAM
; and the EMS store in Fast; in Chip the screens, the FM pool and the
; prerendered effects (owner decision D13: $C0000 plus what they need).
CHIPMEMSIZE = $150000
        IFD FASTSIZE
FASTMEMSIZE = FASTSIZE            ; sizing variants (MemFree)
        ELSE
FASTMEMSIZE = $700000
        ENDC
NUMDRIVES = 0
WPDRIVES = 0
BLACKSCREEN
INITAGA
BOOTDOS
CACHE                           ; _bootdos falls back to CACHECHIP without MMU
HDINIT
SEGTRACKER
NO68020                         ; portable kickemu patches; game still needs 020
; Do not use kick31.s STACKSIZE: its A600 patch at $2305c overwrites
; the MOVE.L opcode (the immediate starts at $2305e).
        IFD TEST
BOOTEARLY
DEBUG
        ENDC

slv_Version = 17
slv_Flags = WHDLF_NoError|WHDLF_Req68020|WHDLF_ReqAGA
slv_keyexit = $5f                 ; Help: the game's key table has no Help key
        INCLUDE whdload/kick31.s

slv_CurrentDir dc.b "data",0
; Not cached by WHDLoad (ws_DontCache): the executable, read once by _load in two
; reads (each read of an uncached file is an OS switch). WC2.EXE stays cached: the
; runtime's EXEC reads its relocations 4 bytes at a time, and the overlay manager
; reads overlays from it during play (docs/vroomm.md).
slv_DontCache dc.b "(Wc2)",0
slv_name dc.b "Wing Commander II: Vengeance of the Kilrathi",0
slv_copy dc.b "1991 Origin Systems",0
slv_info dc.b "Amiga port by Vesuri",10
        dc.b "Version 0.1 alpha (19.11.2026)",10
        dc.b "Help quits",0
slv_config dc.b "C1:B:Analog joystick in port 2;",0
        dc.b "$VER: Wc2.slave 0.1 (19.11.2026)",0
_program dc.b "Wc2",0
_args_tail dc.b 10,0
_args_analog dc.b "ANALOGJOYSTICK ",0
        IFD KEYS
; Test only (tools/test_whdload.py --mode script): data/keys, the diagnostic
; image's KEYS="..." argument, too long for a fixed line, goes before the tail.
KEYSBYTES = 2048
_keysname dc.b "keys",0
_keysbad dc.b "data/keys is missing or too long",0
_line   ds.b 160+KEYSBYTES
_keysbuf ds.b KEYSBYTES
        ELSE
_line   ds.b 160                  ; the argument line, built at start
        ENDC
        EVEN

_bootdos
        move.l (_resload,pc),a2
        ; CACHE marks BaseMem noncacheable, which needs WHDLoad's MMU (68040/060,
        ; 68030 with the MMU option); without it WHDLoad switches every cache off
        ; (CACR 0). Then keep CACHECHIP's instruction cache (docs/whdload.md).
        move.l 4.w,a6
        lea (_getcacr,pc),a5
        jsr (_LVOSupervisor,a6)
        and.w #$8001,d0           ; IC (68040/060) or EI (68020/030)
        bne .cached
        move.l #WCPUF_Base_WT|WCPUF_Exp_CB|WCPUF_Slave_CB|WCPUF_IC|WCPUF_BC|WCPUF_SS|WCPUF_SB,d0
        move.l #WCPUF_All,d1
        jsr (resload_SetCPU,a2)
.cached
        lea (_config_tags,pc),a0
        jsr (resload_Control,a2)
        IFD BOOTONLY
        pea TDREASON_OK
        jmp (resload_Abort,a2)
        ENDC
        IFD TEST
        lea (_bootmark,pc),a0
        bsr _mark
        ENDC
        ; The argument line, the Custom keywords then the tail, and its length
        ; without the terminating zero.
        lea (_line,pc),a1
        lea (_args_analog,pc),a0
        tst.l (_analog,pc)
        beq .noanalog
        bsr _append
.noanalog
        IFD KEYS
        move.l a1,-(sp)
        lea (_keysname,pc),a0
        jsr (resload_GetFileSize,a2)
        tst.l d0
        beq .nokeys
        cmp.l #KEYSBYTES-1,d0
        bcc .nokeys
        move.l d0,-(sp)
        lea (_keysname,pc),a0
        lea (_keysbuf,pc),a1
        jsr (resload_LoadFile,a2)
        move.l (sp)+,d0
        lea (_keysbuf,pc),a0
        clr.b (a0,d0.l)
        move.l (sp)+,a1
        bsr _append
        bra .keysdone
.nokeys pea (_keysbad,pc)
        pea TDREASON_FAILMSG
        jmp (resload_Abort,a2)
.keysdone
        ENDC
        lea (_args_tail,pc),a0
        bsr _append
        clr.b (a1)
        lea (_line,pc),a0
        move.l a1,d0
        sub.l a0,d0
        lea (_args,pc),a1
        move.l a0,(a1)+
        move.l d0,(a1)
        IFD TEST
        move.l (_args,pc),a1
        lea (_argsmark,pc),a0
        jsr (resload_SaveFile,a2)
        ENDC
        lea (_dosname,pc),a1
        move.l 4.w,a6
        jsr (_LVOOldOpenLibrary,a6)
        move.l d0,a6
        tst.l d0
        beq .oserror
        bsr _load
        move.l d0,d7
        beq .readerror
        IFD TEST
        lea (_loadmark,pc),a0
        bsr _mark
        ENDC
        IFD LOADONLY
        ; Test only: the relocated block and its address and sizes, which
        ; tools/test_whdload.py --mode load relocates independently.
        move.l (_blocksize,pc),d0
        beq .noblock
        lea (_blockname,pc),a0
        move.l (_block,pc),a1
        jsr (resload_SaveFile,a2)
        moveq #12,d0
        lea (_blockadrname,pc),a0
        lea (_block,pc),a1
        jsr (resload_SaveFile,a2)
.noblock
        ENDC
        jsr (resload_FlushCache,a2)
        ; Establish PROGDIR as a Shell would. Calling a LoadSeg entry alone
        ; does not set pr_HomeDir.
        lea (_current,pc),a0
        move.l a0,d1
        moveq #-2,d2              ; ACCESS_READ, lock the actual current drawer
        jsr (_LVOLock,a6)
        tst.l d0
        beq .readerror
        move.l d0,d1
        jsr (_LVOSetProgramDir,a6)
        lea (_oldhome,pc),a0
        move.l d0,(a0)
        IFD LOADONLY
        pea TDREASON_OK
        jmp (resload_Abort,a2)
        ENDC
        ; RunCommand allocates and swaps in the stack and also places the line
        ; in Input()'s buffer, where ReadArgs reads it (dos.doc RunCommand);
        ; -1 when it could not run the program.
        move.l d7,d1
        move.l #16384,d2
        move.l (_args,pc),d3
        move.l (_argslen,pc),d4
        jsr (_LVORunCommand,a6)
        move.l d0,d6
        move.l (_oldhome,pc),d1
        jsr (_LVOSetProgramDir,a6)
        move.l d0,d1
        jsr (_LVOUnLock,a6)
        bsr _unload
        move.l a6,a1
        move.l 4.w,a6
        jsr (_LVOCloseLibrary,a6)
        tst.l d6
        bne .gameerror
        IFD TEST
        lea (_exitmark,pc),a0
        bsr _mark
        ENDC
        IFD MEMFREE
        ; Diagnostic only: kickemu's lowest largest free Chip/Fast chunks.
        lea (_memfreename,pc),a0
        lea MEMFREE,a1
        moveq #8,d0
        move.l (_resload,pc),a2
        jsr (resload_SaveFile,a2)
        ENDC
        pea TDREASON_OK
        bra .abort
.readerror
        jsr (_LVOIoErr,a6)
        pea (_program,pc)
        move.l d0,-(sp)
        pea TDREASON_DOSREAD
        bra .abort
.oserror
        clr.l -(sp)
        clr.l -(sp)
        pea TDREASON_OSEMUFAIL
        bra .abort
.gameerror
        ; A nonzero result: a failed start or a runtime stop (WC2_STOP, result 2).
        pea (_stopped,pc)
        pea TDREASON_FAILMSG
.abort
        move.l (_resload,pc),a2
        jmp (resload_Abort,a2)
_getcacr
        movec cacr,d0
        rte

; d0 = the seglist of _program (BPTR), 0 if LoadSeg failed; a2 resload, a6 DOS.
; Under PreLoad Wc2 is uncached (slv_DontCache), so each read of it is an
; OS switch: dos.LoadSeg reads relocations in 1 KiB pieces. Here: the hunk
; header and the file, each in one read, into one cleared block that
; resload_Relocate (WHDLTAG_LOADSEG) turns into a seglist in place. A header
; this does not take (resident libraries, Chip or extended memory flags, more
; than MAXHUNKS hunks), a file larger than its block or no memory for the
; block: dos.LoadSeg. _unload frees what this loaded.
MAXHUNKS = 32
HDRBYTES = (5+MAXHUNKS)*4
_load
        movem.l d2-d6/a3/a6,-(sp)
        lea (-HDRBYTES,sp),sp
        move.l a6,a3                ; DOS
        lea (_program,pc),a0
        jsr (resload_GetFileSize,a2)
        move.l d0,d5                ; file bytes
        cmp.l #HDRBYTES,d0
        bls .seg
        move.l #HDRBYTES,d0
        moveq #0,d1
        lea (_program,pc),a0
        move.l sp,a1
        jsr (resload_LoadFileOffset,a2)
        move.l sp,a0
        cmp.l #$3f3,(a0)+           ; HUNK_HEADER
        bne .seg
        tst.l (a0)+                 ; resident library names
        bne .seg
        addq.l #4,a0                ; table size
        move.l (a0)+,d2             ; first hunk
        move.l (a0)+,d4             ; last hunk
        sub.l d2,d4                 ; hunks - 1
        bcs .seg
        cmp.l #MAXHUNKS-1,d4
        bhi .seg
        moveq #0,d6                 ; block bytes
.size   move.l (a0)+,d0
        btst #30,d0                 ; MEMF_CHIP, or with bit 31 extended flags
        bne .seg
        and.l #$3fffffff,d0
        cmp.l #$01000000,d0         ; 64 MiB: not a size this can take
        bcc .seg
        lsl.l #2,d0
        add.l #8+7+8,d0             ; segment header, alignment 8, margin
        and.w #-8,d0
        add.l d0,d6
        dbf d4,.size
        cmp.l d5,d6
        bcc .fits
        move.l d5,d6                ; the file is loaded before it is relocated
.fits   move.l d6,d0
        move.l #$10001,d1           ; MEMF_PUBLIC|MEMF_CLEAR
        move.l 4.w,a6
        jsr (_LVOAllocMem,a6)
        tst.l d0
        beq .seg
        lea (_block,pc),a0
        move.l d0,(a0)+
        move.l d6,(a0)
        lea (_program,pc),a0
        move.l d0,a1
        jsr (resload_LoadFile,a2)
        clr.l -(sp)                 ; TAG_DONE
        pea -1
        pea WHDLTAG_LOADSEG
        pea 8
        pea WHDLTAG_ALIGN
        move.l (_block,pc),a0
        move.l sp,a1
        jsr (resload_Relocate,a2)
        lea (5*4,sp),sp
        lea (_relocated,pc),a0
        move.l d0,(a0)
        cmp.l d6,d0
        bhi .overrun
        move.l (_block,pc),d0
        addq.l #4,d0                ; the first segment's link
        lsr.l #2,d0
        bra .done
.seg    move.l a3,a6
        lea (_program,pc),a0
        move.l a0,d1
        jsr (_LVOLoadSeg,a6)
.done   lea (HDRBYTES,sp),sp
        movem.l (sp)+,d2-d6/a3/a6
        rts
.overrun
        ; resload_Relocate wrote past the block: memory is not to be trusted.
        pea (_failed,pc)
        pea TDREASON_FAILMSG
        jmp (resload_Abort,a2)

; Unloads d7, the seglist _load returned; a6 DOS.
_unload
        move.l (_block,pc),d0
        beq .unloadseg
        move.l a6,-(sp)
        move.l d0,a1
        move.l (_blocksize,pc),d0
        move.l 4.w,a6
        jsr (_LVOFreeMem,a6)
        move.l (sp)+,a6
        rts
.unloadseg
        move.l d7,d1
        jmp (_LVOUnLoadSeg,a6)
; Copies the zero-terminated string at a0 to a1, which ends past its last byte.
_append move.b (a0)+,(a1)+
        bne _append
        subq.l #1,a1
        rts
_failed dc.b "Wing Commander II could not start. Check the installed original data files.",0
_stopped dc.b "Wing Commander II stopped. Please report it with what you were doing: github.com/Vesuri/wc2/issues",0
        IFD MEMFREE
_memfreename dc.b "memfree",0
        ENDC
_current dc.b 0
        EVEN
_config_tags dc.l WHDLTAG_CUSTOM1_GET
_analog dc.l 0
        dc.l 0
_args   dc.l 0
_argslen dc.l 0
_oldhome dc.l 0
_block  dc.l 0                    ; _load's block, 0 when dos.LoadSeg loaded
_blocksize dc.l 0
_relocated dc.l 0                 ; resload_Relocate's size
        IFD LOADONLY
_blockname dc.b "test-block",0
_blockadrname dc.b "test-blockadr",0
        EVEN
        ENDC
        IFD TEST
_bootearly
        move.l (_resload,pc),a2
        lea (_earlymark,pc),a0
        bra _mark
_mark
        movem.l d0-d1/a0-a1,-(sp)
        lea (_marker,pc),a1
        moveq #4,d0
        jsr (resload_SaveFile,a2)
        movem.l (sp)+,d0-d1/a0-a1
        rts
_marker dc.b "PASS"
_earlymark dc.b "test-early",0
_bootmark dc.b "test-bootdos",0
_argsmark dc.b "test-args",0
_loadmark dc.b "test-loaded",0
_exitmark dc.b "test-returned",0
        EVEN
        ENDC
