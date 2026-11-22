#ifndef _AUDIO_H
#define _AUDIO_H

#include "Util.h"

// AdLib FM on Paula (docs/sound-plan.md): the FM re-hoster (fm_paula.c) turns
// the guest's OPL registers into four voice commands in the main program at
// each vertical blank; the vertical blank stages them on Paula. DMA stays on,
// silence is volume 0; a key-on restarts its channel's loop.
class Audio {
public:
    // The Chip loop pool and the re-hoster (before the takeover); false
    // without the Chip RAM.
    static bool begin();
    static void end();
    // The prerendered effects (fx_play.c): from sfx.cache at plat_sfx_cached,
    // true when it holds them; of the runtime's capture at plat_sfx_captured.
    static bool cachedEffects();
    static void loadEffects();

    // DMA on for the four channels on a silent loop; off again, volume 0.
    static void takeOver();
    static void handBack();

    // The field task after a vertical blank (plat_service): the next commands.
    static void service();
    // Vertical blank: the commands on Paula.
    static void verticalBlank();
    // Volume 0 while the OS runs (I/O windows).
    static void mute(bool on);
};

#endif
