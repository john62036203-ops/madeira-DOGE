/* SPDX-License-Identifier: GPL-3.0-or-later
 * madeira-doge: dockdetach.exe -- what Valve's client starts for a non-Steam
 * shortcut launched through Madeira Dock (MADEIRA_DOCK_SHORTCUT=1).
 *
 * The client starts the shortcut's program as its own child, so the program
 * inherits the Dock host's console (dockhost.exe has a real conhost). A
 * PyInstaller program (EXVS2IB_PC_Offline_Launcher.exe) then dies in Python's
 * init_sys_streams ("Cannot open console output buffer for reading", log
 * 2026-10-29 00:18), the client sees the game end and the host reports 46.
 * Started directly, the same program has no console and runs.
 *
 * This GUI-subsystem program starts MADEIRA_DOCK_DETACH_EXE (with
 * MADEIRA_DOCK_DETACH_ARGS) DETACHED from any console, with no standard
 * handles, in the program's own folder, waits for it and returns its exit code,
 * so the client still sees the game run for as long as it runs. With
 * MADEIRA_DOCK_NO_CONSOLE=1 in the program's environment Wine refuses conhost
 * to it and its children (build 543: the PyInstaller child asked for a new
 * console and died the same way). */
#include <windows.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, LPWSTR line, int show)
{
    static wchar_t exe[1024], args[2048], cmd[4096], dir[1024];
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    DWORD n, code = 0;
    wchar_t *slash;
    (void)inst; (void)prev; (void)line; (void)show;
    n = GetEnvironmentVariableW(L"MADEIRA_DOCK_DETACH_EXE", exe, 1024);
    if (!n || n >= 1024) return 2;
    n = GetEnvironmentVariableW(L"MADEIRA_DOCK_DETACH_ARGS", args, 2048);
    if (n >= 2048) args[0] = 0;
    _snwprintf(cmd, 4095, L"\"%ls\"%ls%ls", exe, args[0] ? L" " : L"", args);
    cmd[4095] = 0;
    wcscpy(dir, exe);
    slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;
    /* the program's own children must not take this route again */
    SetEnvironmentVariableW(L"MADEIRA_DOCK_DETACH_EXE", NULL);
    SetEnvironmentVariableW(L"MADEIRA_DOCK_DETACH_ARGS", NULL);
    /* the program and its children get no conhost console either (process_ios.c
     * dock_conhost_refuse): a PyInstaller program's child asks for a new one */
    SetEnvironmentVariableW(L"MADEIRA_DOCK_NO_CONSOLE", L"1");
    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    si.dwFlags = STARTF_USESTDHANDLES;   /* hStdInput/Output/Error stay NULL */
    ZeroMemory(&pi, sizeof pi);
    if (!CreateProcessW(exe, cmd, NULL, NULL, FALSE, DETACHED_PROCESS | CREATE_UNICODE_ENVIRONMENT, NULL,
                        slash ? dir : NULL, &si, &pi))
        return 3;
    CloseHandle(pi.hThread);
    WaitForSingleObject(pi.hProcess, INFINITE);
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    return (int)code;
}
