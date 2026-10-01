// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import SwiftUI

/// Per-game options for a Steam game started through Madeira Dock: the same
/// switches the 221 library offers a game it launches itself (AVX, NVIDIA,
/// safe sync, MetalFX, frame generation, FPS limit, D3D12 options and the raw
/// game config file). They are stored under the key "steam:<App ID>" and
/// applied to the Dock session's LaunchRequest (MadeiraDockLauncher), whose
/// environment Valve's client passes on to the game it starts.
enum SteamGameOptions {
    static func key(_ appID: Int) -> String { "steam:\(appID)" }
    static func profile(_ appID: Int) -> GameProfile { GameProfile(windowsPath: key(appID)) }

    static func apply(to request: inout LaunchRequest, appID: Int) {
        let k = key(appID)
        request.avx = LibraryPrefs.avx(k)
        request.nvidia = LibraryPrefs.nvidia(k)
        request.safeSync = LibraryPrefs.safeSync(k)
        request.wineVCRT = LibraryPrefs.wineVCRT(k)
        request.profile = profile(appID)
    }
}

struct SteamGameSettingsView: View {
    let appID: Int
    let name: String

    @Environment(\.dismiss) private var dismiss
    @State private var avx: Bool
    @State private var nvidia: Bool
    @State private var safeSync: Bool
    @State private var wineVCRT: Bool
    @State private var metalFX: String
    @State private var frameGen: String
    @State private var fpsLimit: String
    @State private var tess: String
    @State private var submit: String
    @State private var gpuSync: String
    @State private var overlay: Bool
    @State private var args: String

    private var profile: GameProfile { SteamGameOptions.profile(appID) }

    init(appID: Int, name: String) {
        self.appID = appID
        self.name = name
        let k = SteamGameOptions.key(appID)
        let p = SteamGameOptions.profile(appID)
        _avx = State(initialValue: LibraryPrefs.avx(k))
        _nvidia = State(initialValue: LibraryPrefs.nvidia(k))
        _safeSync = State(initialValue: LibraryPrefs.safeSync(k))
        _wineVCRT = State(initialValue: LibraryPrefs.wineVCRT(k))
        _metalFX = State(initialValue: p.get("metalfx-upscale") ?? "")
        _frameGen = State(initialValue: p.get("env.MADEIRA_FRAMEGEN") ?? "")
        _fpsLimit = State(initialValue: p.get("fps-limit") ?? "")
        _tess = State(initialValue: p.get("dxil-tess-max-factor") ?? "")
        _submit = State(initialValue: p.get("async-submit") ?? "")
        _gpuSync = State(initialValue: p.get("fence-chain") ?? "")
        _overlay = State(initialValue: p.get("env.MADEIRA_STEAM_OVERLAY") == "1")
        _args = State(initialValue: p.get("env.MADEIRA_DOCK_GAME_ARGS") ?? "")
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Toggle("Expose AVX/AVX2", isOn: $avx)
                    Toggle("Present the GPU as NVIDIA", isOn: $nvidia)
                    Toggle("Safe sync (fastsync off)", isOn: $safeSync)
                    Toggle("Keep Wine's VC++ runtime", isOn: $wineVCRT)
                    Toggle("Allow the Steam Overlay (slower)", isOn: $overlay)
                } header: { Text("Compatibility") } footer: {
                    Text("The same switches as a library game's settings. They apply to the whole Dock session, so Valve's client runs with them too. "
                         + "The Steam Overlay is off by default: on iOS it makes games stutter and cannot be opened anyway.")
                }
                Section {
                    TextField("none", text: $args, axis: .vertical)
                        .font(.body.monospaced())
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .lineLimit(1...3)
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(["-dx11", "-dx12", "-d3d11", "-d3d12", "-windowed", "-fullscreen", "-nosplash"], id: \.self) { flag in
                                Button(flag) { toggleFlag(flag) }
                                    .buttonStyle(.bordered)
                                    .tint(hasFlag(flag) ? Color.accentColor : Color.gray)
                                    .font(.caption.monospaced())
                            }
                        }
                    }
                } header: { Text("Launch arguments") } footer: {
                    Text("Passed to the game when Steam starts it, like Steam's own Launch Options. "
                         + "Unreal Engine games: -dx11 or -dx12. Some games use -d3d11 / -d3d12 instead.")
                }
                Section {
                    picker("MetalFX upscaling", $metalFX, GameProfile.metalFXChoices)
                    picker("Frame generation", $frameGen, GameProfile.frameGenChoices)
                    picker("FPS limit at start", $fpsLimit, GameProfile.fpsChoices)
                    picker("Tessellation detail (D3D12)", $tess, GameProfile.tessChoices)
                    picker("D3D12 command encoding", $submit, GameProfile.submitChoices)
                    picker("GPU sync (D3D12)", $gpuSync, GameProfile.gpuSyncChoices)
                    NavigationLink {
                        GameConfigEditor(profile: profile, onSave: { reload() })
                    } label: {
                        Label("Advanced: this game's config", systemImage: "doc.text")
                    }
                } header: { Text("Graphics & performance") }
            }
            .navigationTitle(name).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { save(); dismiss() } }
            }
        }
    }

    private func picker(_ title: String, _ selection: Binding<String>, _ choices: [(String, String)]) -> some View {
        let known = choices.contains { $0.0 == selection.wrappedValue }
        let all: [(String, String)] = choices + (known ? [] : [(selection.wrappedValue, selection.wrappedValue)])
        return Picker(title, selection: selection) {
            ForEach(Array(all.enumerated()), id: \.offset) { item in
                Text(item.element.1).tag(item.element.0)
            }
        }
    }

    private func reload() {
        let p = profile
        metalFX = p.get("metalfx-upscale") ?? ""
        frameGen = p.get("env.MADEIRA_FRAMEGEN") ?? ""
        fpsLimit = p.get("fps-limit") ?? ""
        tess = p.get("dxil-tess-max-factor") ?? ""
        submit = p.get("async-submit") ?? ""
        gpuSync = p.get("fence-chain") ?? ""
        overlay = p.get("env.MADEIRA_STEAM_OVERLAY") == "1"
        args = p.get("env.MADEIRA_DOCK_GAME_ARGS") ?? ""
    }

    private func hasFlag(_ flag: String) -> Bool {
        args.split(separator: " ").contains { $0.caseInsensitiveCompare(flag) == .orderedSame }
    }

    /// Adds or removes one flag; the DirectX flags and windowed/fullscreen exclude each other.
    private func toggleFlag(_ flag: String) {
        var parts = args.split(separator: " ").map(String.init)
        if hasFlag(flag) {
            parts.removeAll { $0.caseInsensitiveCompare(flag) == .orderedSame }
        } else {
            let lower = flag.lowercased()
            if lower.hasPrefix("-dx") || lower.hasPrefix("-d3d") {
                parts.removeAll { $0.lowercased().hasPrefix("-dx") || $0.lowercased().hasPrefix("-d3d") }
            }
            if lower == "-windowed" { parts.removeAll { $0.lowercased() == "-fullscreen" } }
            if lower == "-fullscreen" { parts.removeAll { $0.lowercased() == "-windowed" } }
            parts.append(flag)
        }
        args = parts.joined(separator: " ")
    }

    private func save() {
        let k = SteamGameOptions.key(appID)
        LibraryPrefs.setAVX(avx, for: k)
        LibraryPrefs.setNvidia(nvidia, for: k)
        LibraryPrefs.setSafeSync(safeSync, for: k)
        LibraryPrefs.setWineVCRT(wineVCRT, for: k)
        let p = profile
        p.set("metalfx-upscale", metalFX)
        p.set("env.MADEIRA_FRAMEGEN", frameGen)
        p.set("fps-limit", fpsLimit)
        p.set("dxil-tess-max-factor", tess)
        p.set("async-submit", submit)
        p.set("fence-chain", gpuSync)
        p.set("env.MADEIRA_STEAM_OVERLAY", overlay ? "1" : nil)
        // One line, no "=" games would never need; the Dock host passes it to Steam.
        let cleaned = args.replacingOccurrences(of: "\n", with: " ").trimmingCharacters(in: .whitespaces)
        p.set("env.MADEIRA_DOCK_GAME_ARGS", cleaned.isEmpty ? nil : cleaned)
    }
}
