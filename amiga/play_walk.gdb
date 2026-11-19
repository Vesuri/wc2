# The flight smoke (amiga/play_walk.sh): m4's flight label from generated code,
# then WC2's joystick calibration entered from the flight keys (Ctrl+J) and
# flight going on after it under the stick.
#   flight: entries of WC2.EXE+0813C, m4's label (reference/milestones.csv:
#           813c#1 its first flight frame, #50 the milestone's frame)
#   calib:  entries of WC2.EXE+36FFA, the calibration (Ctrl+J, scan 24h, in the
#           flight key handler WC2.EXE+04C58; docs/amiga-arch.md "Input")
#   after:  flight frames once the calibration was entered: it returned
set pagination off
set confirm off
set $flight = 0
set $calib = 0
set $after = 0
break *rt_stop
commands
  silent
  printf "WC2_PLAY_STOP fields=%u flight=%u calib=%u after=%u\n", amiga_frames, $flight, $calib, $after
  x/s *(char **)($sp+4)
  printf "args=%x %x\n", *(unsigned int *)($sp+8), *(unsigned int *)($sp+12)
  detach
  quit 1
end
break *R_0813C
commands
  silent
  set $flight = $flight + 1
  if $calib > 0
    set $after = $after + 1
  end
  if $flight == 1 || $flight == 50
    printf "WC2_PLAY_FLIGHT n=%u fields=%u ticks=%u\n", $flight, amiga_frames, amiga_ticks
  end
  continue
end
break *R_36FFA
commands
  silent
  set $calib = $calib + 1
  printf "WC2_PLAY_CALIBRATE fields=%u flight=%u\n", amiga_frames, $flight
  continue
end
break *amiga_script_mark
commands
  silent
  printf "WC2_PLAY_MARK fields=%u reads=%u flight=%u calib=%u after=%u\n", amiga_frames, amiga_mouse_reads, $flight, $calib, $after
  if *(unsigned int *)($sp+4)
    if $flight >= 50 && $calib > 0 && $after >= 100
      printf "WC2_PLAY_OK\n"
      detach
      quit 0
    end
    detach
    quit 1
  end
  continue
end
break Wc2::handBack
commands
  silent
  printf "WC2_PLAY_HANDBACK fields=%u flight=%u\n", amiga_frames, $flight
  detach
  quit 1
end
continue
