// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright 2026 125hz
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import SwiftUI

// Installed Steam games in the library (docs/LIBRARY.md, "Steam setup"). The
// list is Madeira Dock's own discovery (MadeiraDock.games): Steam's
// appmanifest_<appid>.acf records in the client's library and the other C:
// libraries its libraryfolders.vdf lists. Nothing here reads or writes other
// Steam files. Play starts the game through Madeira Dock's launch path
// (ContentView.startDock), so Valve's own client signs in, checks the licence
// and starts it. No program names are involved: a game is its App ID.
// A game whose Steam app info lists more than one Windows launch option (DLC
// often adds its own) gets a choice; Dock passes the chosen key to Valve's
// LaunchApp, and Valve's client still checks the licence for that entry.
// Log tag: [steam-games] (App IDs and counts only).

// MARK: - Rules (Foundation only; build/host-tests/check-onboarding.py compiles this part)

enum SteamGamesRules {
    /// Whether the library shows the Steam section: Dock is available and at
    /// least one game was found.
    static func showsSection(dock: Bool, count: Int) -> Bool { dock && count > 0 }

    /// Games whose name contains the library's search text (all of them when it is empty).
    static func matching(_ games: [DockGame], search: String) -> [DockGame] {
        let text = search.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return games }
        return games.filter { $0.name.localizedCaseInsensitiveContains(text) }
    }

    /// Why Play is not offered yet, or nil when Dock can be asked to start the game.
    /// Valve's client still decides at launch.
    static func blocker(installed: Bool, client: Bool, signedIn: Bool) -> String? {
        if !installed { return "Steam does not list this game as fully installed yet." }
        if !client { return "Madeira Dock needs Valve's client components. Download them in Settings › Steam › Madeira Dock." }
        if !signedIn { return "Sign in to Steam in Settings › Steam to play." }
        return nil
    }

    /// Valve's client's app info cache in the prefix (read only).
    static func appInfoCache(drive: URL) -> URL {
        drive.appendingPathComponent(SteamRuntimeFiles.relativeRoot + "/appcache/appinfo.vdf")
    }

    /// The launch choice is offered only when there is something to choose.
    static func showsLaunchOptions(_ options: [SteamLaunchOption]) -> Bool { options.count > 1 }

    /// The entry Play starts before anything is chosen: Steam's first entry (0), as
    /// every Dock start did before, unless the choice is offered without it.
    static func defaultLaunchOption(_ options: [SteamLaunchOption]) -> UInt32 {
        guard showsLaunchOptions(options), !options.contains(where: { $0.id == 0 }) else { return 0 }
        return options[0].id
    }

    /// An entry's name in the choice; entries that need a DLC say so.
    static func title(_ option: SteamLaunchOption) -> String {
        option.dlc.isEmpty ? option.title : option.title + " (DLC)"
    }

    /// Steam's public store artwork for an App ID (no account data).
    static func cover(_ appID: Int) -> URL? {
        guard appID > 0 else { return nil }
        return URL(string: "https://cdn.cloudflare.steamstatic.com/steam/apps/\(appID)/library_600x900.jpg")
    }
}

// MARK: - Model

@MainActor final class SteamGamesModel: ObservableObject {
    static let shared = SteamGamesModel()
    @Published private(set) var games: [DockGame] = []
    private var scanning = false
    private var lastCount = -1

    /// Reads the install records again, off the main thread.
    func refresh() {
        guard MadeiraDock.enabled, !scanning else { return }
        scanning = true
        let drive = MadeiraDock.drive
        Task.detached(priority: .utility) {
            let found = MadeiraDock.games(drive: drive)
            await MainActor.run {
                self.scanning = false
                if self.games != found { self.games = found }
                if found.count != self.lastCount {
                    self.lastCount = found.count
                    LogStore.shared.log("[steam-games] installed=\(found.count) ready=\(found.filter(\.installed).count)")
                }
            }
        }
    }
}

// MARK: - Library section

/// The library's Steam section: games Steam's client has installed in the
/// prefix, each started through Madeira Dock.
struct SteamGamesSection: View {
    let search: String
    /// Madeira Dock's start (ContentView.startDock).
    let startDock: (DockGame, Bool) -> Void
    @ObservedObject private var model = SteamGamesModel.shared
    @Environment(\.scenePhase) private var scenePhase
    @AppStorage("madeiraLibraryHideSteam") private var hidden = false
    @State private var selected: DockGame?

    var body: some View {
        let games = SteamGamesRules.matching(model.games, search: search)
        Group {
            if SteamGamesRules.showsSection(dock: MadeiraDock.enabled, count: model.games.count) {
                VStack(alignment: .leading, spacing: 14) {
                    LibrarySectionHeader(title: "Steam", count: model.games.count, collapsed: $hidden) {
                        Button { model.refresh() } label: { Label("Refresh", systemImage: "arrow.clockwise") }.font(.subheadline)
                    }
                    if hidden {
                        EmptyView()
                    } else if games.isEmpty {
                        Text("No Steam games match your search.").foregroundStyle(.secondary)
                    } else {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 110, maximum: 164), spacing: 12, alignment: .top)],
                                  alignment: .leading, spacing: 18) {
                            ForEach(games) { game in
                                Button { selected = game } label: { SteamGameCell(game: game) }.buttonStyle(.plain)
                            }
                        }
                    }
                }
            }
        }
        // The library reappears after every session, so this also rereads after a game.
        .onAppear { model.refresh() }
        .onChange(of: scenePhase) { _, phase in if phase == .active { model.refresh() } }
        .sheet(item: $selected) { game in SteamGameDetail(game: game, startDock: startDock) }
    }
}

struct SteamGameArtwork: View {
    let appID: Int
    var body: some View {
        GeometryReader { geometry in
            ZStack {
                Color(uiColor: .secondarySystemFill)
                Image(systemName: "gamecontroller.fill").font(.largeTitle).foregroundStyle(.secondary)
                AsyncImage(url: SteamGamesRules.cover(appID)) { phase in
                    if let image = phase.image {
                        image.resizable().scaledToFill()
                            .frame(width: geometry.size.width, height: geometry.size.height).clipped()
                    }
                }
            }
            .frame(width: geometry.size.width, height: geometry.size.height).clipped()
        }
        .accessibilityHidden(true)
    }
}

private struct SteamGameCell: View {
    let game: DockGame
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            SteamGameArtwork(appID: game.id).aspectRatio(2.0 / 3.0, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .opacity(game.installed ? 1 : 0.6)
            Text(game.name).font(.subheadline.weight(.semibold)).lineLimit(2)
            Text(game.installed ? "Madeira Dock" : "Not fully installed")
                .font(.caption2.weight(.medium)).lineLimit(1)
                .padding(.horizontal, 5).padding(.vertical, 4)
                .background(.secondary.opacity(0.12), in: RoundedRectangle(cornerRadius: 6))
                .foregroundStyle(.secondary)
        }
        .padding(4).foregroundStyle(.primary)
        .accessibilityElement(children: .combine)
    }
}

/// One installed Steam game: Play through Madeira Dock.
struct SteamGameDetail: View {
    let game: DockGame
    let startDock: (DockGame, Bool) -> Void
    @ObservedObject private var dock = MadeiraDockModel.shared
    @ObservedObject private var signIn = SteamSignInModel.shared
    @Environment(\.dismiss) private var dismiss
    @State private var launchOptions: [SteamLaunchOption] = []
    @State private var launchOption: UInt32 = 0

    var body: some View {
        let blocker = SteamGamesRules.blocker(installed: game.installed, client: dock.clientInstalled, signedIn: signIn.signedIn)
        NavigationStack {
            Form {
                Section {
                    HStack(spacing: 20) {
                        SteamGameArtwork(appID: game.id).frame(width: 120, height: 180)
                            .clipShape(RoundedRectangle(cornerRadius: 14))
                        VStack(alignment: .leading, spacing: 12) {
                            Text(game.name).font(.title2.bold())
                            Button {
                                let option = SteamGamesRules.showsLaunchOptions(launchOptions) ? launchOption : 0
                                LogStore.shared.log("[steam-games] play app=\(game.id) option=\(option)")
                                dismiss()
                                // Let the sheet finish dismissing before the session takes over.
                                DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                                    MadeiraDock.requestLaunchOption(option, appID: game.id)
                                    startDock(game, dock.compactPool)
                                }
                            } label: {
                                HStack(spacing: 10) { Image(systemName: "play.fill"); Text("Play").fontWeight(.semibold) }
                                    .frame(minWidth: 100, minHeight: 30)
                            }
                            .buttonStyle(.borderedProminent).disabled(blocker != nil)
                        }
                    }.padding(.vertical, 12)
                    if let blocker { Text(blocker).font(.footnote).foregroundStyle(.orange) }
                }
                if SteamGamesRules.showsLaunchOptions(launchOptions) {
                    Section {
                        Picker("Start", selection: $launchOption) {
                            ForEach(launchOptions) { option in Text(SteamGamesRules.title(option)).tag(option.id) }
                        }
                    } header: {
                        Text("Launch option")
                    } footer: {
                        Text("Steam's launch options for this game, including the ones its DLC adds. A DLC entry starts only when the signed-in account owns that DLC and its content is installed; Valve's client decides.")
                    }
                }
                Section {
                    Toggle("Smaller JIT pool (512 MB) for this launch", isOn: $dock.compactPool)
                } footer: {
                    Text("Madeira Dock starts the game through Valve's own Steam client, without the Steam desktop window. Valve's client signs in with your account and decides whether the game may run.")
                }
                if let status = dock.status {
                    Section("Last Dock result") { Text(status) }
                }
                Section {
                    LabeledContent("App ID", value: String(game.id))
                    LabeledContent("Folder", value: game.windowsInstallPath).font(.caption)
                }
            }
            .navigationTitle("Steam").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .onAppear { dock.refresh(); signIn.refresh() }
            .task(id: game.id) {
                // Valve's client keeps the app info cache; a game it has not loaded yet has no choice.
                let appID = game.id, cache = SteamGamesRules.appInfoCache(drive: MadeiraDock.drive)
                let found = await Task.detached(priority: .utility) { SteamAppInfo.launchOptions(appID: appID, cache: cache) }.value
                launchOptions = found
                launchOption = SteamGamesRules.defaultLaunchOption(found)
                LogStore.shared.log("[steam-games] app=\(appID) launch-options=\(found.count)")
            }
        }
    }
}
