# Smoke fixture: the takeover is live once the VERTB vector has counted 100 frames.
# The empty image (no translated program yet, amiga_platform.c) must then hand back:
# WC2_SMOKE_OK only at a hand-back after those 100 frames.
# gdb aborts the whole file at the first unknown symbol: keep in step with the source.
set $live = 0
break Wc2::verticalBlank if amiga_frames >= 100 && $live == 0
commands
  silent
  set $live = 1
  printf "WC2_SMOKE_LIVE amiga_frames=%u\n", amiga_frames
  continue
end
break Wc2::handBack
commands
  silent
  if $live
    printf "WC2_SMOKE_OK amiga_frames=%u\n", amiga_frames
    quit 0
  end
  printf "WC2_SMOKE_EARLY_EXIT\n"
  quit 1
end
continue
