"""host_run.compare_services with annotations/undefined-flags.csv masks: at a
masked INT site its bits may differ at the INT and at its return, any other
bit there fails, and the same bit at another site fails."""
import host_run as H

SITE = ("WC2.EXE", 0x01925)
MASKS = {SITE: {"cx": 0x0010}}


def row(cx, site, kind="svc"):
    r = {n: 0 for n in H.REGS + ("es", "ss", "ds")}
    r.update(vector=0x21, ax=0x1a80, cx=cx, flags=0x7213, cf=1, zf=0, df=0, site=site)
    r["if"] = 1
    return kind, r


def pair(cx_host, cx_ref, site):
    return [row(cx_host, site), row(cx_host, site, "svc_ret")], \
           [row(cx_ref, site), row(cx_ref, site, "svc_ret")]


def check():
    applied = []
    assert not H.compare_services(*pair(0x7203, 0x7213, SITE), MASKS, applied), 'masked AF failed'
    assert len(applied) == 2, applied                       # the INT and its return
    assert H.compare_services(*pair(0x7202, 0x7213, SITE), MASKS), 'an unmasked bit passed'
    assert H.compare_services(*pair(0x7203, 0x7213, ("WC2.EXE", 0x01912)), MASKS), 'another site passed'
    rows = H.undefined_flags()
    assert rows.get(SITE) == {"cx": 0x0010}, rows          # the annotation as read
    return 4


if __name__ == '__main__':
    print(f'undefined-flag masks: {check()} cases pass')
