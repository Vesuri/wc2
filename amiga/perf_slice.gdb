# P5.4 first target profile (docs/port-plan.md): the game from its start to the
# 300th entry of WC2's IRQ0 handler R_0FD10, inside the intro animation the reference
# presents every 1.7 ticks from tick 220 to 525 (MEASURED, host run to m1b), then a
# 100-field instruction profile into ../tmp/prof/slice.bin for tools/profile_report.py.
# No breakpoint in the window. The Barto profiler records nothing on an MMU core:
#   AMIGA_SETUP=a1200-030 EXTRA_ARGS=--uae_mmu_model=0 ./debug.sh "" perf_slice.gdb
set pagination off
set confirm off
break R_0FD10
ignore 1 299
continue
printf "WINDOW_START field %u irq0 %u\n", amiga_frames, rt_irq0_runs
delete breakpoints
monitor profile 100 "" "../tmp/prof/slice.bin"
printf "WINDOW_END field %u irq0 %u\n", amiga_frames, rt_irq0_runs
detach
quit
