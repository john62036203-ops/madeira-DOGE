// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import Foundation

/// Starts an installed Steam game through Madeira Dock (docs/MADEIRA_DOCK.md)
/// from the library: checks the launch state, hands the stored sign-in to the
/// host once, sets the host's environment and returns the library's own
/// LaunchRequest, which RootView then starts like any other game.
///
/// This is the app-side half of ContentView.startDock of the upstream project,
/// without its library model: the 221 library starts a session by handing a
/// LaunchRequest to ContentView (HomeView.launch), so the Dock start does the
/// same. Nothing is handed over unless JIT is ready and no session runs.
@MainActor
enum MadeiraDockLauncher {
    static func prepare(_ game: DockGame) async throws -> LaunchRequest {
        guard jit_check_debugged() else { throw DockError.message("Enable JIT before starting a Steam game.") }
        guard wine_process_is_running() == 0, wineserver_is_running() == 0 else {
            LogStore.shared.log("[madeira-dock] a session already ran in this app run; restart Madeira first", level: .error)
            throw DockError.message("A session already ran in this app run. Restart Madeira first.")
        }
        func fail(_ error: Error) {
            MadeiraDock.cleanup()
            SteamOwnedLibrary.shared.dockEnded()
            MadeiraDockModel.shared.status = error.localizedDescription
            LogStore.shared.log("[madeira-dock] not started: \(error.localizedDescription)", level: .error)
        }
        do {
            try MadeiraDock.validate(game, drive: MadeiraDock.drive)
            guard SteamSignIn.isSignedIn else { throw DockError.message("Sign in to Steam in Madeira before starting Dock.") }
        } catch { fail(error); throw error }

        // Only one sign-in of the account may be online: the app's own Steam connection
        // (library, playtime, downloads) logs off and its socket closes before the sign-in
        // is handed to Valve's client, and it stays off until the Dock session has ended
        // (SteamOwnedLibrary.prepareDock / dockEnded).
        await SteamOwnedLibrary.shared.prepareDock()
        do {
            guard jit_check_debugged(), wine_process_is_running() == 0, wineserver_is_running() == 0 else {
                throw DockError.message("The launch state changed. Enable JIT and try again.")
            }
            guard let signIn = SteamSignIn.credentialsForDock() else {
                throw DockError.message("Sign in to Steam in Madeira before starting Dock.")
            }
            try MadeiraDock.writeHandoff(account: signIn.accountName, token: signIn.refreshToken, appID: game.id)
        } catch { fail(error); throw error }

        MadeiraDock.configure(game)
        // The game's one-time installs (its Steam install script) run first, in the same
        // session. No session runs yet, so the registry files can be read and written.
        DockInstallers.prepare(game, drive: MadeiraDock.drive, prefix: MadeiraDock.prefix)
        // Engines with madsync read this once when the server starts; others ignore it.
        if DockInstallers.serverSync { setenv("MADEIRA_MADSYNC_SESSION", "0", 1) } else { unsetenv("MADEIRA_MADSYNC_SESSION") }
        // A Dock session starts 64-bit but the programs it starts later are often 32-bit
        // (installers, 32-bit games): win32u needs its GDI handle table in a section they
        // can all map. Wine without the switch ignores the variable.
        setenv("MADEIRA_GDI_SHARED_SECTION", "1", 1)

        var width = 1280, height = 720
        if let txt = MadeiraConfig.get("desktop-size") {
            let p = txt.lowercased().split(separator: "x").compactMap { Int($0.trimmingCharacters(in: .whitespaces)) }
            if p.count == 2, p[0] >= 640, p[1] >= 360, p[0] <= 3840, p[1] <= 2160 { width = p[0]; height = p[1] }
        }
        LogStore.shared.log("[madeira-dock] starting the host for app \(game.id); Valve's client authenticates and authorizes the launch")
        MadeiraDockModel.shared.watchReport()
        var request: LaunchRequest
        if noDesktop {
            // Experimental: no Wine virtual desktop. The host and the game Valve's client
            // starts run like a directly launched program, so the game's 3D window gets the
            // full-screen layer the library's own launches use, instead of a sublayer of the
            // desktop compositor. One-time installs run first through cmd.exe as before.
            if let installers = DockInstallers.script {
                request = LaunchRequest(title: game.name, exe: "C:\\windows\\system32\\cmd.exe",
                                        args: "/c call \(installers) & \(MadeiraDock.executable)", desktop: nil)
            } else {
                request = LaunchRequest(title: game.name, exe: MadeiraDock.executable, args: nil, desktop: nil)
            }
            LogStore.shared.log("[madeira-dock] no virtual desktop for this launch (Steam page switch)")
        } else {
            request = LaunchRequest(title: game.name, exe: "explorer.exe",
                                    args: MadeiraDock.launchArguments(width: width, height: height, installers: DockInstallers.script),
                                    desktop: (w: width, h: height))
        }
        request.dock = true
        // The game's own options (Steam page › Game settings), as a library game gets them.
        SteamGameOptions.apply(to: &request, appID: game.id)
        return request
    }

    /// The Steam page's "without virtual desktop" switch (off by default: upstream's Dock
    /// always runs inside explorer's desktop).
    nonisolated static let noDesktopKey = "madeira.dock.noDesktop"
    nonisolated static var noDesktop: Bool { UserDefaults.standard.bool(forKey: noDesktopKey) }
}
