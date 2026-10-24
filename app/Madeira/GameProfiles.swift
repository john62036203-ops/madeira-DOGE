//
//  GameProfiles.swift
//  Madeira
//
//  madeira-bcd: a game's own settings file -- Winlator's per-shortcut
//  overrides, in this app's terms.
//
//  Same syntax as Documents/madeira.cfg (key = value, env.NAME = value, # for
//  comments). The launch exports its path as MADEIRA_CFG_GAME; the native
//  reader (build/madeira_cfg.h) lets a key set here win over madeira.cfg, and
//  WineProcessBridge exports its env.* lines after madeira.cfg's. So any
//  runtime switch -- a D3D12 experiment, a FEX option, a DXMT setting -- can be
//  set for one game without touching the others, and without a new build.
//
//  The game settings sheet edits the common ones with pickers; the raw file is
//  one tap further for everything else.
//

import Foundation
import SwiftUI

struct GameProfile {
    let windowsPath: String

    /// madeira-doge: Documents/GameConfigs, which the Files app shows, so the
    /// per-game files can be copied out and back into a reinstalled Madeira
    /// (a SideStore reinstall empties the whole container). The files used to
    /// live in Application Support/GameConfigs; they are moved over once.
    static var directory: URL? { storeDirectory }

    private static let storeDirectory: URL? = {
        let fm = FileManager.default
        guard let docs = fm.urls(for: .documentDirectory, in: .userDomainMask).first else { return nil }
        let dir = docs.appendingPathComponent("GameConfigs", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        if let support = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask).first {
            let old = support.appendingPathComponent("GameConfigs", isDirectory: true)
            for name in (try? fm.contentsOfDirectory(atPath: old.path)) ?? [] where name.hasSuffix(".cfg") {
                let from = old.appendingPathComponent(name)
                let hash = name.dropLast(4).suffix(16)
                let taken = ((try? fm.contentsOfDirectory(atPath: dir.path)) ?? []).contains { $0.hasSuffix("\(hash).cfg") }
                if taken { continue }
                // A readable name from the file's own first line ("# Madeira settings for C:\...\Game.exe").
                var target = name
                if let text = try? String(contentsOf: from, encoding: .utf8),
                   let first = text.split(separator: "\n").first, first.hasPrefix("# Madeira settings for ") {
                    target = fileName(windowsPath: String(first.dropFirst("# Madeira settings for ".count)), hash: String(hash))
                }
                try? fm.moveItem(at: from, to: dir.appendingPathComponent(target))
            }
        }
        return dir
    }()

    /// "<program>-<hash>.cfg": the program's name so the Files app shows which game
    /// it is; the hash of its Windows path, which is what Madeira matches on.
    private static func fileName(windowsPath: String, hash: String) -> String {
        let program = windowsPath.split(whereSeparator: { $0 == "\\" || $0 == "/" }).last.map(String.init) ?? ""
        var stem = program.lowercased().hasSuffix(".exe") ? String(program.dropLast(4)) : program
        stem = String(stem.map { "/:\\?*\"<>|".contains($0) ? "_" : $0 }).trimmingCharacters(in: .whitespaces)
        return stem.isEmpty ? "\(hash).cfg" : "\(stem)-\(hash).cfg"
    }

    /// The game's file: an existing one whose name ends in its hash (any name
    /// before it, so a copied or renamed file still matches), else a new one
    /// named after the program.
    var url: URL? {
        guard let dir = GameProfile.directory else { return nil }
        let hash = String(format: "%016llx", CoverStore.stableHash(windowsPath.lowercased()))
        if let found = ((try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? [])
            .first(where: { $0 == "\(hash).cfg" || $0.hasSuffix("-\(hash).cfg") }) {
            return dir.appendingPathComponent(found)
        }
        return dir.appendingPathComponent(GameProfile.fileName(windowsPath: windowsPath, hash: hash))
    }

    /// The whole file ("" when there is none). Setting "" deletes it.
    var text: String {
        get {
            guard let u = url, let t = try? String(contentsOf: u, encoding: .utf8) else { return "" }
            return t
        }
        nonmutating set {
            guard let u = url else { return }
            if newValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                try? FileManager.default.removeItem(at: u)
            } else {
                try? (newValue.hasSuffix("\n") ? newValue : newValue + "\n").write(to: u, atomically: true, encoding: .utf8)
            }
        }
    }

    /// key -> value, the last line winning, as the native reader does.
    var values: [String: String] { GameProfile.parse(text) }

    static func values(ofFile url: URL) -> [String: String] {
        parse((try? String(contentsOf: url, encoding: .utf8)) ?? "")
    }

    static func parse(_ text: String) -> [String: String] {
        var out: [String: String] = [:]
        for raw in text.split(whereSeparator: { $0 == "\n" || $0 == "\r\n" }) {
            let line = raw.trimmingCharacters(in: .whitespaces)
            guard !line.isEmpty, !line.hasPrefix("#"), let eq = line.firstIndex(of: "=") else { continue }
            let k = line[..<eq].trimmingCharacters(in: .whitespaces)
            if !k.isEmpty { out[k] = line[line.index(after: eq)...].trimmingCharacters(in: .whitespaces) }
        }
        return out
    }

    /// True when the file sets anything at all.
    var hasSettings: Bool { !values.isEmpty }

    func get(_ key: String) -> String? {
        guard let v = values[key], !v.isEmpty else { return nil }
        return v
    }

    /// Sets or (nil / "") removes `key`, keeping every other line as written.
    func set(_ key: String, _ value: String?) {
        var lines = text.components(separatedBy: "\n")
        while lines.last == "" { lines.removeLast() }
        if lines.isEmpty { lines = ["# Madeira settings for \(windowsPath)", "# madeira.cfg syntax; keys here win over madeira.cfg."] }
        lines.removeAll { raw in
            let line = raw.trimmingCharacters(in: .whitespaces)
            guard !line.hasPrefix("#"), let eq = line.firstIndex(of: "=") else { return false }
            return line[..<eq].trimmingCharacters(in: .whitespaces) == key
        }
        if let value, !value.isEmpty { lines.append("\(key) = \(value)") }
        let kept = lines.filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("#") && !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        text = kept.isEmpty ? "" : lines.joined(separator: "\n")
    }

    // MARK: The curated switches

    /// MetalFX spatial upscaling factor: the D3D12 runtime reads
    /// metalfx-upscale itself; a D3D11 game gets DXMT's own MetalFX swapchain
    /// with the same factor (LaunchRequest.apply).
    static let metalFXChoices: [(String, String)] = [("", "Off"), ("1.5", "1.5×"), ("2", "2×")]

    /// Frame limit the session starts with (the Session panel still changes it).
    static let fpsChoices: [(String, String)] = [("", "Default (60)"), ("20", "20 FPS"), ("30", "30 FPS"), ("40", "40 FPS"),
                                                  ("60", "60 FPS"), ("max", "Display max"), ("raw", "Unlimited")]

    /// The D3D12 runtime's cap on low-detail tessellation (dxil-tess-max-factor).
    static let tessChoices: [(String, String)] = [("", "Default (3)"), ("2", "Low (2)"), ("4", "Medium (4)"),
                                                   ("8", "High (8)"), ("0", "Full (no cap)")]

    /// ml1120/ml1121 async-submit: the D3D12 runtime encodes the game's command
    /// lists on its own worker thread instead of inside the game's
    /// ExecuteCommandLists (10-16 ms of every Ghost of Tsushima frame in the
    /// 2026-09-28 14:04 log).
    static let submitChoices: [(String, String)] = [("", "Game's thread (default)"), ("1", "Worker thread")]

    /// fence-chain: F1 = every GPU pass waits for the one before (accurate,
    /// default); F6 = only where the game's barriers say so (the GPU overlaps
    /// work; the overlay's F pill switches the same thing live).
    static let gpuSyncChoices: [(String, String)] = [("", "Every pass (F1, default)"), ("6", "Barriers only (F6)"), ("7", "Barriers only, fragment-stage waits (F7)"), ("8", "Barriers only, read-to-write transitions skipped (F8)")]
    /// env.MADEIRA_FRAMEGEN: MetalFX frame interpolation in the present path
    /// (tools/patch-dxmt-framegen.py), D3D11 and D3D12 alike.
    static let frameGenChoices: [(String, String)] = [("", "Off"), ("1", "MetalFX 2× (experimental)")]
    /// ml2100 env.MADEIRA_PAD_MODE (GamepadInput.configuredPadMode): player 1 as an
    /// XInput pad (default) or as a HID controller -- a DualSense when it is one.
    static let padModeChoices: [(String, String)] = [("", "XInput (default)"), ("hid", "DirectInput / HID")]

    var frameLimit: FrameLimit? {
        switch get("fps-limit") {
        case "20": return .locked20
        case "30": return .locked30
        case "40": return .locked40
        case "60": return .locked60
        case "max": return .display
        case "raw": return .unlimited
        default: return nil
        }
    }

    var metalFXFactor: Double? {
        guard let s = get("metalfx-upscale"), let f = Double(s), f >= 1.1 else { return nil }
        return min(f, 3)
    }
}

/// The raw file, for any switch the sheet has no picker for.
struct GameConfigEditor: View {
    let profile: GameProfile
    let onSave: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var text = ""

    var body: some View {
        Form {
            Section {
                TextEditor(text: $text)
                    .font(.caption.monospaced())
                    .frame(minHeight: 260)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
            } footer: {
                Text("One key = value per line, as in madeira.cfg; env.NAME = value exports an environment "
                     + "variable (FEX_*, DXMT_*, MADEIRA_*). A key set here wins over madeira.cfg for this "
                     + "game only. Examples: dxil-tess-max-factor = 0, metalfx-upscale = 2, "
                     + "env.FEX_MULTIBLOCK = 1.")
            }
        }
        .navigationTitle("Game config")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("Save") {
                    profile.text = text
                    onSave()
                    dismiss()
                }
            }
        }
        .onAppear { text = profile.text }
    }
}
