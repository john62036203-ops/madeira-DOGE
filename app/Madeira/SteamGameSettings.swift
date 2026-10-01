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
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Toggle("Expose AVX/AVX2", isOn: $avx)
                    Toggle("Present the GPU as NVIDIA", isOn: $nvidia)
                    Toggle("Safe sync (fastsync off)", isOn: $safeSync)
                    Toggle("Keep Wine's VC++ runtime", isOn: $wineVCRT)
                } header: { Text("Compatibility") } footer: {
                    Text("The same switches as a library game's settings. They apply to the whole Dock session, so Valve's client runs with them too.")
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
    }
}
