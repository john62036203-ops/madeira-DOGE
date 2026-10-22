#!/usr/bin/env python3
"""ISpatialAudioObject::SetEndOfStream and ::IsActive for Wine's mmdevapi.

Upstream Wine leaves both as FIXME stubs returning E_NOTIMPL, and IsActive does
not even write *active. A game that ends a sound with SetEndOfStream and then
polls IsActive until the object goes inactive waits forever. DYNASTY WARRIORS:
ORIGINS demo (Koei Tecmo KTSL2 audio, build 351, log 2026-10-22 10:27) called
each about 105,000 times on a grey frame and never moved on.

After this patch SetEndOfStream marks the object ended (S_OK) and IsActive
reports !ended (S_OK, E_POINTER for NULL). Nothing else changes.

Usage: patch-wine-spatialaudio-eos.py wine/dlls/mmdevapi/spatialaudio.c
Idempotent; fails by name when an anchor moves.
"""
import sys

MARK = "madeira-doge: spatial audio end of stream"


def main():
    path = sys.argv[1]
    src = open(path).read()
    if MARK in src:
        print("patch-wine-spatialaudio-eos: already applied")
        return
    edits = [
        ("    float *buf;\n\n    struct list entry;\n};\n",
         "    float *buf;\n    BOOL eos;   /* " + MARK + " */\n\n    struct list entry;\n};\n"),
        ("""static HRESULT WINAPI SAO_SetEndOfStream(ISpatialAudioObject *iface, UINT32 frames)
{
    SpatialAudioObjectImpl *This = impl_from_ISpatialAudioObject(iface);
    FIXME("(%p)->(%u)\\n", This, frames);
    return E_NOTIMPL;
}
""", """static HRESULT WINAPI SAO_SetEndOfStream(ISpatialAudioObject *iface, UINT32 frames)
{
    SpatialAudioObjectImpl *This = impl_from_ISpatialAudioObject(iface);
    TRACE("(%p)->(%u)\\n", This, frames);
    This->eos = TRUE;   /* """ + MARK + """ */
    return S_OK;
}
"""),
        ("""static HRESULT WINAPI SAO_IsActive(ISpatialAudioObject *iface, BOOL *active)
{
    SpatialAudioObjectImpl *This = impl_from_ISpatialAudioObject(iface);
    FIXME("(%p)->(%p)\\n", This, active);
    return E_NOTIMPL;
}
""", """static HRESULT WINAPI SAO_IsActive(ISpatialAudioObject *iface, BOOL *active)
{
    SpatialAudioObjectImpl *This = impl_from_ISpatialAudioObject(iface);
    TRACE("(%p)->(%p)\\n", This, active);
    if (!active) return E_POINTER;
    *active = !This->eos;   /* """ + MARK + """ */
    return S_OK;
}
"""),
    ]
    for old, new in edits:
        if src.count(old) != 1:
            sys.exit("patch-wine-spatialaudio-eos: anchor not found exactly once: %r" % old[:60])
        src = src.replace(old, new)
    open(path, "w").write(src)
    print("patch-wine-spatialaudio-eos: applied")


if __name__ == "__main__":
    main()
