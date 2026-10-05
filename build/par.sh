#!/bin/bash
# build/par.sh -- run a build script's per-file compiles side by side.
#
# The unix-side build scripts (ntdll-unix, win32u-unix, wineserver, dxmt-ios)
# compiled one file at a time on a runner with several cores. Sourcing this
# file gives them two calls:
#
#   par_spawn fn args...   run "fn args..." in a background subshell, at most
#                          PAR_JOBS at once
#   par_wait               wait for every spawned job, print each job's output
#                          in the order the jobs were spawned, and add each
#                          job's SUCCEEDED / FAILED / FAILED_FILES to the
#                          caller's. PAR_FAILED_JOBS counts the jobs whose
#                          function returned non-zero.
#
# A spawned function cannot change the caller's variables, which is why the
# three counters travel back through a file. Anything that looks at a job's
# result -- its .o, or the counters -- must come after a par_wait.
#
# MADEIRA_JOBS=1 runs every job in the foreground, exactly as before.
# Written for macOS's /bin/bash 3.2: no `wait -n`, no associative arrays.

PAR_JOBS="${MADEIRA_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 2)}"
case "$PAR_JOBS" in ''|*[!0-9]*) PAR_JOBS=2 ;; esac
PAR_DIR="$(mktemp -d "${TMPDIR:-/tmp}/madeira-par.XXXXXX")"
PAR_N=0
PAR_DONE=0
PAR_FAILED_JOBS=0

par_cleanup() {
    local pids
    pids="$(jobs -p 2>/dev/null || true)"
    if [ -n "$pids" ]; then kill $pids 2>/dev/null || true; fi
    rm -rf "$PAR_DIR"
}
trap par_cleanup EXIT

par_spawn() {
    if [ "$PAR_JOBS" -le 1 ]; then
        "$@"
        return
    fi
    # $(( )) because macOS wc pads its count with spaces.
    while [ $(( $(jobs -rp | wc -l) )) -ge "$PAR_JOBS" ]; do
        sleep 0.05
    done
    PAR_N=$((PAR_N + 1))
    local id=$PAR_N
    (
        SUCCEEDED=0
        FAILED=0
        FAILED_FILES=""
        rc=0
        "$@" || rc=$?
        printf '%s\n%s\n%s\n%s\n' "$rc" "$SUCCEEDED" "$FAILED" "$FAILED_FILES" > "$PAR_DIR/$id.tally"
    ) > "$PAR_DIR/$id.out" 2>&1 &
}

par_wait() {
    if [ "$PAR_DONE" -ge "$PAR_N" ]; then return 0; fi
    wait
    local id rc s f ff
    while [ "$PAR_DONE" -lt "$PAR_N" ]; do
        PAR_DONE=$((PAR_DONE + 1))
        id=$PAR_DONE
        cat "$PAR_DIR/$id.out" 2>/dev/null || true
        rc=1; s=0; f=1; ff=" job$id(no-result)"
        if [ -s "$PAR_DIR/$id.tally" ]; then
            {
                IFS= read -r rc
                IFS= read -r s
                IFS= read -r f
                IFS= read -r ff
            } < "$PAR_DIR/$id.tally" || true
        else
            echo "  par: job $id ended without reporting a result"
        fi
        SUCCEEDED=$(( ${SUCCEEDED:-0} + s ))
        FAILED=$(( ${FAILED:-0} + f ))
        FAILED_FILES="${FAILED_FILES:-}$ff"
        if [ "$rc" != 0 ]; then PAR_FAILED_JOBS=$((PAR_FAILED_JOBS + 1)); fi
    done
}
