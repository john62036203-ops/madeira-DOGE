#!/usr/bin/env python3
"""StikJIT.xcframework's Swift interface in the syntax older compilers read.

Upstream's prebuilt framework (app/Frameworks/StikJIT.xcframework) was built
with Swift 6.4, whose module interfaces qualify names with module selectors
(`Swift::String`, `StikJIT::DDIPaths`). The CI runner's newest Xcode has an
older Swift, which stops at the first one ("expected '{' in struct"), and the
MadeiraJITHelper target does not compile.

The same declarations in the older spelling: another module's name keeps a dot
(`Swift.String`); this module's own selector is dropped, because the module and
its main type are both called StikJIT and `StikJIT.X` already means the type's
member (`StikJIT::StikJIT.StikJIT::Configuration` -> `StikJIT.Configuration`).
The binary is untouched. Build-time only: the tracked files are not changed in
the repository.

Usage: patch-stikjit-interface.py app/Frameworks/StikJIT.xcframework
"""
import glob, os, re, sys

root = sys.argv[1]
files = glob.glob(os.path.join(root, "**", "*.swiftinterface"), recursive=True)
if not files:
    sys.exit("patch-stikjit-interface: no .swiftinterface under " + root)
for path in files:
    s = open(path).read()
    if "::" not in s:
        print(os.path.basename(path) + ": no module selectors"); continue
    n = s.count("::")
    s = s.replace("StikJIT::", "")
    s = re.sub(r"\b([A-Za-z_][A-Za-z_0-9]*)::", r"\1.", s)
    open(path, "w").write(s)
    print("%s: %d module selectors rewritten" % (os.path.basename(path), n))
