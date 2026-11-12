# Smoke fixture: the takeover is live once the VERTB vector has counted 100 frames.
# A hand-back before that (an exit or a loud stop) fails.
# gdb aborts the whole file at the first unknown symbol: keep in step with the source.
break Wc2::verticalBlank if amiga_frames >= 100
commands
  silent
  printf "WC2_SMOKE_OK amiga_frames=%u\n", amiga_frames
  quit 0
end
break Wc2::handBack
commands
  silent
  printf "WC2_SMOKE_EARLY_EXIT\n"
  quit 1
end
continue
