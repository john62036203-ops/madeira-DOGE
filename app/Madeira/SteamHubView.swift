// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import SwiftUI

/// The Steam page of the 221 library: sign in, Valve's client components, the
/// account's owned games with their downloads, and Play through Madeira Dock.
///
/// The account, download and Dock models are the upstream project's
/// (SteamSignInModel, SteamOwnedLibrary, MadeiraDockModel); this view replaces
/// the Steam sections of upstream's Library screens, which the 221 library does
/// not have. A game starts through `play`, which the library turns into a
/// LaunchRequest (MadeiraDockLauncher).
struct SteamHubView: View {
    let play: (DockGame) -> Void

    @ObservedObject private var signIn = SteamSignInModel.shared
    @ObservedObject private var dock = MadeiraDockModel.shared
    @ObservedObject private var library = SteamOwnedLibrary.shared
    @Environment(\.dismiss) private var dismiss
    @State private var showSignIn = false
    @State private var search = ""
    @State private var confirmRemove: DockGame?
    @AppStorage(MadeiraDockLauncher.noDesktopKey) private var noDesktop = false

    private var installed: [Int: DockGame] {
        Dictionary(dock.games.filter(\.installed).map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
    }

    private var shownGames: [SteamOwnedGame] {
        let q = search.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return library.owned }
        return library.owned.filter { $0.name.localizedCaseInsensitiveContains(q) }
    }

    private var canPlay: Bool { dock.clientInstalled && signIn.signedIn }

    var body: some View {
        NavigationStack {
            Form {
                accountSection
                clientSection
                gamesSection
                statusSection
            }
            .navigationTitle("Steam").navigationBarTitleDisplayMode(.inline)
            .searchable(text: $search, prompt: "Search your games")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
                ToolbarItem(placement: .primaryAction) {
                    Button { Task { await library.refreshLibrary(interactive: true) } } label: {
                        if library.refreshing { ProgressView() } else { Image(systemName: "arrow.clockwise") }
                    }
                    .disabled(library.refreshing || !signIn.signedIn)
                }
            }
            .onAppear {
                dock.refresh(); signIn.refresh()
                library.start()
                library.reconcileSession()
            }
            .sheet(isPresented: $showSignIn) { SteamSignInView() }
            .confirmationDialog("Remove this game's files?", isPresented: Binding(get: { confirmRemove != nil },
                                                                                  set: { if !$0 { confirmRemove = nil } }),
                                titleVisibility: .visible) {
                if let game = confirmRemove {
                    Button("Remove \(game.name)", role: .destructive) { library.uninstall(game); confirmRemove = nil }
                }
                Button("Cancel", role: .cancel) { confirmRemove = nil }
            }
        }
    }

    // MARK: Sections

    private var accountSection: some View {
        Section {
            if let name = signIn.accountName {
                LabeledContent("Signed in", value: name)
                Button("Sign out or switch account") { showSignIn = true }
            } else {
                Button("Sign in to Steam") { showSignIn = true }
            }
        } header: { Text("Steam account") } footer: {
            Text("Madeira signs in with Steam directly. Games download unmodified from Steam's servers, and Valve's own client decides whether the game may start.")
        }
    }

    private var clientSection: some View {
        Section {
            if dock.clientInstalled {
                Label("Valve's client components are installed", systemImage: "checkmark.circle")
            } else if dock.preparing {
                HStack(spacing: 12) { ProgressView(); Text(dock.progress).foregroundStyle(.secondary) }
            } else {
                Button("Download Valve's client components (about 73 MB)") { dock.prepareClient() }
            }
            if let error = dock.error {
                Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
            }
            Toggle("Start games without the virtual desktop (experimental)", isOn: $noDesktop)
        } header: { Text("Steam client") } footer: {
            Text("Needed once, to start games. Downloaded from Valve's update servers and checked against pinned SHA-256 sums. "
                 + "Turn the switch on if a game runs but the screen stays black.")
        }
    }

    @ViewBuilder private var gamesSection: some View {
        if !signIn.signedIn {
            Section("Your games") {
                Text("Sign in to see the games your account owns.").foregroundStyle(.secondary)
            }
        } else {
            Section {
                if library.owned.isEmpty {
                    Text(library.refreshing ? "Loading your library…" : "No Windows games were found. Pull the refresh button to try again.")
                        .foregroundStyle(.secondary)
                }
                ForEach(shownGames) { game in row(game) }
                if let error = library.error {
                    Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
                }
            } header: { Text("Your games") } footer: {
                Text("Downloads go into the Steam library folder of the Wine prefix and pause while a game runs. Keep Madeira open while a game downloads.")
            }
        }
    }

    @ViewBuilder private var statusSection: some View {
        if let status = dock.status {
            Section("Dock status") { Text(status) }
        }
    }

    // MARK: A game

    @ViewBuilder private func row(_ game: SteamOwnedGame) -> some View {
        let item = library.downloads[game.id]
        let local = installed[game.id]
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(game.name)
                    if let summary = library.playtime[game.id]?.summary {
                        Text(summary).font(.caption).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                trailing(game, item: item, local: local)
            }
            if let item { downloadLine(item) }
        }
    }

    @ViewBuilder private func trailing(_ game: SteamOwnedGame, item: SteamOwnedLibrary.Download?, local: DockGame?) -> some View {
        switch item?.state {
        case .active?, .queued?:
            Button("Pause") { library.pause(game.id) }.buttonStyle(.bordered)
        case .paused?, .failed?:
            HStack {
                Button("Resume") { library.install(game.id) }.buttonStyle(.bordered)
                Button(role: .destructive) { library.cancelInstall(game.id, installed: local != nil) } label: {
                    Image(systemName: "xmark")
                }.buttonStyle(.bordered)
            }
        case nil:
            if let local {
                HStack {
                    Button("Play") { dismiss(); play(local) }
                        .buttonStyle(.borderedProminent).disabled(!canPlay)
                    Menu {
                        if library.updateAvailable(appID: game.id, installedBuild: SteamInstallFiles.buildID(appID: game.id, steamApps: SteamOwnedLibrary.steamApps)) {
                            Button("Update") { library.install(game.id) }
                        }
                        Button("Verify files") { library.repair(game.id) }
                        if let count = dock.installPrograms[game.id] {
                            // The game's Steam install script programs (runtime setups); see DockInstallers.
                            Toggle("Run \(count) one-time install(s) at next start",
                                   isOn: Binding(get: { dock.installRunNext[game.id] ?? true },
                                                 set: { dock.setRunsInstallers(game.id, $0) }))
                        }
                        if SteamInstallPaths.isManaged(library: local.library) {
                            Button("Remove files", role: .destructive) { confirmRemove = local }
                        }
                    } label: { Image(systemName: "ellipsis.circle") }
                }
            } else {
                Button(library.hasPartialDownload(game.id) ? "Resume" : "Install") { library.install(game.id) }
                    .buttonStyle(.bordered)
            }
        }
    }

    @ViewBuilder private func downloadLine(_ item: SteamOwnedLibrary.Download) -> some View {
        switch item.state {
        case .queued:
            Text("Waiting in the download queue").font(.caption).foregroundStyle(.secondary)
        case .active:
            VStack(alignment: .leading, spacing: 4) {
                ProgressView(value: item.progress.fraction)
                Text(progressText(item.progress)).font(.caption).foregroundStyle(.secondary)
            }
        case .paused:
            Text("Paused").font(.caption).foregroundStyle(.secondary)
        case .failed(let message):
            Text(message).font(.caption).foregroundStyle(.red)
        }
    }

    private func progressText(_ p: SteamDownloadProgress) -> String {
        switch p.phase {
        case .preparing: return "Preparing…"
        case .finishing: return "Finishing…"
        case .downloading:
            let fmt = ByteCountFormatter()
            fmt.countStyle = .file
            var text = "\(fmt.string(fromByteCount: Int64(clamping: p.doneBytes))) of \(fmt.string(fromByteCount: Int64(clamping: p.totalBytes)))"
            if p.bytesPerSecond > 1 { text += " · \(fmt.string(fromByteCount: Int64(p.bytesPerSecond)))/s" }
            return text
        }
    }
}
