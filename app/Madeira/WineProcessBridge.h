#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Start Wine process initialization on a background thread.
// Must be called AFTER wineserver is running.
// prefix_path: path to the Wine prefix directory
// Returns 0 on success, -1 on error.
int wine_process_start(const char *prefix_path);

// Check if Wine process is running
int wine_process_is_running(void);

// Session exit report (the library front end). ntdll calls
// wine_launched_process_did_exit() when the program the app launched (the
// session's initial process) exits; other processes are not reported.
// Returns 1 and fills *status when that program ended with an NTSTATUS error
// (0xC...) since the last reset.
void wine_launched_process_did_exit(int status);
int wine_crash_exit_status(uint32_t *status);
// The last child process that ended with an NTSTATUS error (0xC...): returns
// a sequence number (0: none since the last reset) and fills *status and the
// image's Windows path. ntdll calls wine_child_process_did_exit() for it.
void wine_child_process_did_exit(int status, const char *name);
uint32_t wine_child_crash_exit(uint32_t *status, char *name, size_t name_len);
// Forget the recorded statuses; called when a session begins.
void wine_exit_status_reset(void);
// A game in a Madeira Dock session asked Steam to start another game
// (steam://run/<App ID>). ntdll calls wine_steam_run_requested(); returns 1
// and fills *appid when one was asked since the last reset.
void wine_steam_run_requested(unsigned int appid);
int wine_steam_run_request(uint32_t *appid);

// Steam S0 net-test VPN gate: write C:\madeira-continue.flag into the
// prefix's drive_c so the paused winhttp-test.exe resumes to the Steam
// stage. Called by the "Continue Net Test" UI button after the user has
// detached the JIT debugger and switched VPNs. Returns 0 on success.
int madeira_write_continue_flag(void);

// Extract the bundled prefix template if the prefix is new (idempotent).
// Madeira Dock's component setup calls it before writing Steam's registry keys.
void madeira_seed_prefix_if_needed(const char *prefix_path);

#ifdef __cplusplus
}
#endif
