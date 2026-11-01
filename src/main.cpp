#include "Wc2.h"

int main(int argc, char** argv)
{
    Wc2 swotl;
    if (!swotl.isRunnable()) {
        return 20; // AmigaDOS FAIL
    }
    swotl.run();
    return 0;
}
