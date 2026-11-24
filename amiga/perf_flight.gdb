# P7 frames fixture (docs/perf-method.md): a flight window on the image that runs,
# driven by a KEYS script (tools/perf_flight.py) that marks the window start with
# `shot`. From the mark: the PAL field and the scaled objects drawn (STM_0153E,
# SUPERTM.DRV's entry 2, one per object, docs/feasibility.md) at each of the next
# FRAMES visits to the flight frame label R_0813C (reference/milestones.csv m4),
# one gdb stop per frame and per object, outside any capture, then a 100-field
# instruction profile. @FRAMES@ and @OUT@ are filled by tools/perf_flight.py.
set pagination off
set confirm off
break *rt_stop
commands
  silent
  x/s *(char **)($sp+4)
  quit 1
end
break Wc2::handBack
commands
  silent
  printf "WC2_PERF_HANDBACK\n"
  quit 1
end
break amiga_script_mark
continue
delete $bpnum
printf "WINDOW_MARK field %u presents %u\n", amiga_frames, amiga_presents
set $obj = 0
break *STM_0153E
break *R_0813C
set $n = 0
while $n < @FRAMES@
  continue
  if $pc == (unsigned int) &R_0813C
    printf "FRAME %d field %u objects %d\n", $n, amiga_frames, $obj
    set $obj = 0
    set $n = $n + 1
  else
    set $obj = $obj + 1
  end
end
delete
printf "PROFILE_START field %u\n", amiga_frames
monitor profile 100 "" "@OUT@"
printf "PROFILE_END field %u\n", amiga_frames
printf "WC2_PERF_OK\n"
quit 0
