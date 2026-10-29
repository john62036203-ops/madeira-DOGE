//
//  LibraryBCD.swift
//  Madeira
//
//  madeira-bcd: this fork's per-game options inside upstream's library.
//
//  Upstream's library (Library.swift) is the default interface; this fork's own
//  home screen (HomeView.swift) stays as a choice in Settings › Interface and in
//  the developer interface. A game's madeira-bcd options are keyed by its
//  Windows path in both, so a setting made in one interface applies in the
//  other: the switches in LibraryPrefs (AVX, Wine's C++ runtime, NVIDIA) and
//  the game's own config file (GameProfiles.swift: MetalFX, frame generation,
//  D3D12 switches, any madeira.cfg key).
//

import SwiftUI
import UIKit
import Metal

extension Notification.Name {
    /// Posted by the developer interface: show madeira-bcd's home screen (RootView).
    static let madeiraShowBCDHome = Notification.Name("madeiraShowBCDHome")
}

/// What a launch exports on top of the exe, its arguments and its screen.
enum BCDLaunch {
    /// The switches both interfaces share. Everything is set or unset, so a
    /// previous launch's choice never leaks into this one.
    static func applyExtras(avx: Bool, wineVCRT: Bool, nvidia: Bool, olderNvidia: Bool = false, profile: GameProfile?) {
        if avx { setenv("MADEIRA_FEX_AVX", "1", 1) } else { unsetenv("MADEIRA_FEX_AVX") }
        if wineVCRT { setenv("MADEIRA_WINE_VCRT", "1", 1) } else { unsetenv("MADEIRA_WINE_VCRT") }
        var dxmtExtra: [String] = []
        if nvidia {
            setenv("DXMT_ENABLE_NVEXT", "1", 1)
            // The same GeForce RTX 3060 (10DE:2544) win32u registers as the
            // display adapter (sysparams_ios.c, ios_virtual_gpu_ids); merged
            // into DXMT_CONFIG by ContentView.
            dxmtExtra.append("dxgi.customDeviceId=2544")
            // DXGI's output carries user32's monitor handle and user32's mode
            // list, so a game can find its monitor on the adapter. Default-on
            // in this fork until the build 222 switch to upstream, where both
            // became 32-bit-only switches; Ghost of Tsushima has said "No
            // installed graphics card ... monitor connected to it" on every
            // launch since (logs 2026-10-01 16:15 / 16:16 / 17:04; 2026-09-28
            // ran with both). A game file's env.NAME = 0 still wins.
            setenv("DXMT_WSI_MONITOR_IDENTITY", "1", 1)
            setenv("DXMT_WSI_MODE_TABLE", "1", 1)
        } else {
            unsetenv("DXMT_ENABLE_NVEXT")
            unsetenv("DXMT_WSI_MONITOR_IDENTITY")
            unsetenv("DXMT_WSI_MODE_TABLE")
        }
        // "Older NVIDIA card (Direct3D 9)": after the NVIDIA ids, so its D3D9 ids win.
        if olderNvidia { dxmtExtra += D3D9Identity.olderNvidia.options }
        // The game's own settings (GameProfiles.swift).
        if let p = profile, p.hasSettings, let u = p.url {
            setenv("MADEIRA_CFG_GAME", u.path, 1)
        } else {
            unsetenv("MADEIRA_CFG_GAME")
        }
        // MetalFX: the D3D12 runtime reads metalfx-upscale from that file; a
        // D3D11 game gets DXMT's own MetalFX swapchain at the same factor.
        if let f = profile?.metalFXFactor {
            setenv("DXMT_METALFX_SPATIAL_SWAPCHAIN", "1", 1)
            dxmtExtra.append("d3d11.metalSpatialUpscaleFactor=\(f)")
        } else {
            unsetenv("DXMT_METALFX_SPATIAL_SWAPCHAIN")
        }
        if dxmtExtra.isEmpty { unsetenv("MADEIRA_DXMT_EXTRA") }
        else { setenv("MADEIRA_DXMT_EXTRA", dxmtExtra.joined(separator: ";"), 1)   /* DXMT splits on ";" */ }
    }

    /// A start from upstream's library: the update pack, this game's
    /// madeira-bcd options and its own session log. The FPS limit is the
    /// entry's (upstream's FPS picker, which offers 40 FPS too).
    /// `sessionLog: false` for a Steam game started through Madeira Dock: the
    /// native side names that log after the program Valve's client starts
    /// (process_ios.c, madeira_steam_session_log).
    static func applyLibrary(_ entry: LibraryEntry, sessionLog: Bool = true) {
        // madeira-doge: a session that starts in the Wine desktop runs explorer (64-bit)
        // first, so win32u initialises before any 32-bit program arms the session and keeps
        // the GDI handle table in private host memory; a 32-bit program started on that
        // desktop then truncates the table's address and faults in gdi32's
        // get_gdi_client_ptr (Flash Player 30 projector, 2026-10-21 23:14). Same remedy as
        // the Dock path (ContentView.startDock). Set before the madeira.cfg export, so
        // env.MADEIRA_GDI_SHARED_SECTION = 0 there still wins.
        if entry.desktop == true || entry.runsInDesktop { setenv("MADEIRA_GDI_SHARED_SECTION", "1", 1) }
        ExperimentalSettings.exportToEnvironment()
        if entry.desktop == true {
            applyExtras(avx: false, wineVCRT: false, nvidia: false, profile: nil)
            LogStore.shared.startSessionLog(program: "explorer.exe")
            return
        }
        let path = entry.windowsPath
        let profile = GameProfile(windowsPath: path)
        let olderNvidia = LibraryPrefs.olderNvidia(path)
        applyExtras(avx: LibraryPrefs.avx(path), wineVCRT: LibraryPrefs.wineVCRT(path),
                    nvidia: LibraryPrefs.nvidia(path), olderNvidia: olderNvidia, profile: profile)
        if let appID = entry.steamAppID { D3D9Identity.syncGamePrefs(appID: appID, olderNvidia: olderNvidia) }
        LibraryPrefs.markPlayed(entry.title)
        let program = path.split(separator: "\\").last.map(String.init) ?? path
        LogStore.shared.log("[bcd] library launch \(program): avx=\(LibraryPrefs.avx(path) ? 1 : 0) "
                            + "wine-vcrt=\(LibraryPrefs.wineVCRT(path) ? 1 : 0) nvidia=\(LibraryPrefs.nvidia(path) ? 1 : 0) "
                            + "older-nvidia=\(olderNvidia ? 1 : 0) "
                            + "game-config=\(profile.hasSettings ? 1 : 0) metalfx=\(profile.metalFXFactor.map { String($0) } ?? "off")")
        if sessionLog { LogStore.shared.startSessionLog(program: program) }
    }

    /// "Pause threads fully" (Game details › Compatibility): MADEIRA_REAL_SUSPEND for
    /// this session, or nil to leave it unset. Without it a Wine SuspendThread only
    /// snapshots the target's registers while the thread keeps running (ml730,
    /// build/wineserver/mach_ios.c). A Unity IL2CPP game's garbage collector suspends
    /// every thread and scans its stack: with the threads still running it freed
    /// objects in use, and Megabonk crashed while loading (c0000005 at a scrambled
    /// address in two of the threads it had suspended). With real suspension it runs.
    /// The game's own On or Off wins; Automatic follows madeira.cfg's real-suspend
    /// when that is set, and otherwise turns it on for a Unity IL2CPP game only:
    /// real suspension can deadlock a game that suspends a thread holding a lock
    /// Madeira's own code needs, so it stays off for everything else.
    static func realSuspend(_ entry: LibraryEntry?) -> (value: String, source: String)? {
        if let entry, entry.desktop != true, let on = LibraryPrefs.realSuspend(entry.windowsPath) {
            return (on ? "1" : "0", "this game's switch")
        }
        if let v = MadeiraConfig.get("real-suspend")?.trimmingCharacters(in: .whitespacesAndNewlines), !v.isEmpty {
            return (v, "madeira.cfg real-suspend")
        }
        if let entry, entry.desktop != true, isUnityIL2CPP(entry) { return ("1", "Unity IL2CPP game (GameAssembly.dll)") }
        return nil
    }

    /// A Unity IL2CPP build keeps GameAssembly.dll next to its exe. A Steam entry's
    /// path is its install folder; another entry's is the exe.
    static func isUnityIL2CPP(_ entry: LibraryEntry) -> Bool {
        guard let url = LibraryEntry.hostURL(ofWindowsPath: entry.windowsPath) else { return false }
        var isDir: ObjCBool = false
        let fm = FileManager.default
        let folder = fm.fileExists(atPath: url.path, isDirectory: &isDir) && isDir.boolValue ? url : url.deletingLastPathComponent()
        return fm.fileExists(atPath: folder.appendingPathComponent("GameAssembly.dll").path)
    }

    /// The size that MetalFX 1.5x brings back to this screen's shape at 720
    /// lines ("WxH"), as madeira-bcd's home screen offers it (fill-mfx15).
    static var metalFX15Resolution: String {
        let s = LibraryPrefs.screenPixels("fill-mfx15")
        return "\(s.0)x\(s.1)"
    }
}

/// The madeira-bcd sections of upstream's game details page (LibraryDetail).
/// Every change is written at once, so Done, Play and a swipe away all keep it.
struct BCDGameSections: View {
    let windowsPath: String
    /// Bumped by LibraryDetail when it changes this game's config file itself.
    var refresh: Int = 0
    /// madeira-doge: a Steam game that starts through Madeira Dock (its launch
    /// arguments and the overlay choice go to Valve's client).
    var steamDock = false

    @State private var pool = ""
    @State private var dockArgs = ""
    @State private var overlay = false
    @State private var avx = false
    @State private var wineVCRT = false
    @State private var nvidia = false
    @State private var metalFX = ""
    @State private var frameGen = ""
    @State private var syncEngine = ""
    @State private var tess = ""
    @State private var submit = ""
    @State private var gpuSync = ""
    @State private var padMode = ""
    @State private var loaded = true
    @State private var copiedLink = false

    init(windowsPath: String, refresh: Int = 0, steamDock: Bool = false) {
        self.windowsPath = windowsPath
        self.refresh = refresh
        self.steamDock = steamDock
        let p = GameProfile(windowsPath: windowsPath)
        _pool = State(initialValue: p.get("pool") ?? "")
        _dockArgs = State(initialValue: p.get("env.MADEIRA_DOCK_GAME_ARGS") ?? "")
        _overlay = State(initialValue: p.get("env.MADEIRA_STEAM_OVERLAY") == "1")
        _avx = State(initialValue: LibraryPrefs.avx(windowsPath))
        _wineVCRT = State(initialValue: LibraryPrefs.wineVCRT(windowsPath))
        _nvidia = State(initialValue: LibraryPrefs.nvidia(windowsPath))
        _metalFX = State(initialValue: p.get("metalfx-upscale") ?? "")
        _frameGen = State(initialValue: p.get("env.MADEIRA_FRAMEGEN") ?? "")
        _syncEngine = State(initialValue: p.get("inproc-sync") ?? "")
        _tess = State(initialValue: p.get("dxil-tess-max-factor") ?? "")
        _submit = State(initialValue: p.get("async-submit") ?? "")
        _gpuSync = State(initialValue: p.get("fence-chain") ?? "")
        _padMode = State(initialValue: p.get(GamepadInput.padModeKey) ?? "")
    }

    private var profile: GameProfile { GameProfile(windowsPath: windowsPath) }

    private var thisGameFooter: String {
        let pool = "JIT pool for this game only; \"Same as Settings\" uses the size chosen in Settings › Memory & sync."
        guard steamDock else { return pool }
        return pool + " Steam launch arguments are what Steam calls Launch Options (for example -d3d12)."
            + " The Steam Overlay is off in Madeira Dock sessions unless allowed here."
    }

    /// madeira-doge: the JIT pool of this game alone (ContentView reads the game's `pool` first).
    static let poolChoices: [(String, String)] = [("", "Same as Settings"), ("512", "512 MB"), ("640", "640 MB"),
                                                   ("768", "768 MB"), ("896", "896 MB"), ("1024", "1024 MB"),
                                                   ("1152", "1152 MB")]

    private func load() {
        loaded = false
        avx = LibraryPrefs.avx(windowsPath)
        wineVCRT = LibraryPrefs.wineVCRT(windowsPath)
        nvidia = LibraryPrefs.nvidia(windowsPath)
        let p = profile
        pool = p.get("pool") ?? ""
        dockArgs = p.get("env.MADEIRA_DOCK_GAME_ARGS") ?? ""
        overlay = p.get("env.MADEIRA_STEAM_OVERLAY") == "1"
        metalFX = p.get("metalfx-upscale") ?? ""
        frameGen = p.get("env.MADEIRA_FRAMEGEN") ?? ""
        syncEngine = p.get("inproc-sync") ?? ""
        tess = p.get("dxil-tess-max-factor") ?? ""
        submit = p.get("async-submit") ?? ""
        gpuSync = p.get("fence-chain") ?? ""
        padMode = p.get(GamepadInput.padModeKey) ?? ""
        // The onChange handlers of this pass must not write the values back.
        DispatchQueue.main.async { loaded = true }
    }

    /// Writes one key of the game's file when the value really changed.
    private func store(_ key: String, _ value: String) {
        guard loaded else { return }
        let p = profile
        if (p.get(key) ?? "") != value { p.set(key, value) }
    }

    /// A picker over (value, label) pairs that also shows a value typed into the raw file.
    private func choicePicker(_ title: String, _ selection: Binding<String>, _ choices: [(String, String)]) -> some View {
        let known = choices.contains { $0.0 == selection.wrappedValue }
        let all: [(String, String)] = choices + (known ? [] : [(selection.wrappedValue, selection.wrappedValue)])
        return Picker(title, selection: selection) {
            ForEach(Array(all.enumerated()), id: \.offset) { item in
                Text(item.element.1).tag(item.element.0)
            }
        }
    }

    var body: some View {
        Group { sections }
            .onChange(of: refresh) { _, _ in load() }
    }

    @ViewBuilder private var sections: some View {
        Section {
            Toggle("AVX / AVX2", isOn: $avx)
                .onChange(of: avx) { _, on in if loaded { LibraryPrefs.setAVX(on, for: windowsPath) } }
            Toggle("Wine's C++ runtime", isOn: $wineVCRT)
                .onChange(of: wineVCRT) { _, on in if loaded { LibraryPrefs.setWineVCRT(on, for: windowsPath) } }
            Toggle("Report an NVIDIA GPU", isOn: $nvidia)
                .onChange(of: nvidia) { _, on in if loaded { LibraryPrefs.setNvidia(on, for: windowsPath) } }
        } header: {
            Text("madeira-bcd: launch options")
        } footer: {
            Text("Turn on AVX when a game quits at start with \"illegal instruction\" (c000001d): it was built for AVX "
                 + "CPUs; emulated AVX is slower. Wine's C++ runtime replaces Microsoft's concrt140/msvcp140_* for a "
                 + "game that crashes right after loading them. Report an NVIDIA GPU is for games that stop with "
                 + "\"no graphics card\" or \"failed to get GPU driver info\".")
        }
        Section {
            choicePicker("MetalFX upscaling", $metalFX, GameProfile.metalFXChoices)
                .onChange(of: metalFX) { _, v in store("metalfx-upscale", v) }
            choicePicker("Frame generation", $frameGen, GameProfile.frameGenChoices)
                .onChange(of: frameGen) { _, v in store("env.MADEIRA_FRAMEGEN", v) }
            // madeira-doge: this game's sync engine (inproc-sync in its own file; the
            // native side reads it there, Library.swift drops the fastsync export).
            choicePicker("Sync engine (this game)", $syncEngine, [("", "App setting (default)"), ("1", "Madsync")])
                .onChange(of: syncEngine) { _, v in store("inproc-sync", v) }
            choicePicker("Tessellation detail (D3D12)", $tess, GameProfile.tessChoices)
                .onChange(of: tess) { _, v in store("dxil-tess-max-factor", v) }
            choicePicker("D3D12 command encoding", $submit, GameProfile.submitChoices)
                .onChange(of: submit) { _, v in store("async-submit", v) }
            choicePicker("GPU sync (D3D12)", $gpuSync, GameProfile.gpuSyncChoices)
                .onChange(of: gpuSync) { _, v in store("fence-chain", v) }
            NavigationLink {
                GameConfigEditor(profile: profile, onSave: { load() })
            } label: {
                Label("Advanced: this game's config", systemImage: "doc.text")
            }
        } header: {
            Text("madeira-bcd: graphics & performance")
        } footer: {
            Text("MetalFX upscaling renders at the resolution above and scales the picture up 1.5× or 2× with "
                 + "Apple's scaler; the \"MetalFX 1.5×\" resolution is this screen's shape at 480 lines, which "
                 + "1.5× brings to 720. Frame generation (experimental) shows a MetalFX-interpolated frame between "
                 + "every two game frames; FPS limits do not apply while it is on. Sync engine: Madsync keeps thread "
                 + "waits inside the game instead of asking the Wine server (faster for games that wait a lot, "
                 + "such as Sekiro; a game's own online service may not connect); it applies from the next full "
                 + "restart of the app. The advanced file takes any "
                 + "madeira.cfg key or env.NAME line for this game only.")
        }
        Section {
            choicePicker("JIT pool (this game)", $pool, BCDGameSections.poolChoices)
                .onChange(of: pool) { _, v in store("pool", v) }
            if steamDock {
                TextField("Steam launch arguments", text: $dockArgs, axis: .vertical)
                    .autocorrectionDisabled().textInputAutocapitalization(.never)
                    .onChange(of: dockArgs) { _, v in
                        // One line; the Dock host hands it to Valve's client as the launch options.
                        store("env.MADEIRA_DOCK_GAME_ARGS",
                              v.replacingOccurrences(of: "\n", with: " ").trimmingCharacters(in: .whitespaces))
                    }
                Toggle("Allow the Steam Overlay (slower)", isOn: $overlay)
                    .onChange(of: overlay) { _, on in store("env.MADEIRA_STEAM_OVERLAY", on ? "1" : "") }
            }
        } header: {
            Text("madeira-doge: this game")
        } footer: {
            Text(thisGameFooter)
        }
        Section {
            choicePicker("Controller API", $padMode, GameProfile.padModeChoices)
                .onChange(of: padMode) { _, v in store(GamepadInput.padModeKey, v) }
        } header: {
            Text("madeira-bcd: controller")
        } footer: {
            Text("XInput shows every controller as an Xbox pad, which almost every game understands. "
                 + "DirectInput / HID shows player 1 as what it is: a DualSense to Sony's PC ports (God of War "
                 + "and others show PlayStation buttons), a HID gamepad to DirectInput games; it is then not an "
                 + "XInput pad. Read when the game starts; the in-game menu changes it too.")
        }
        Section {
            Button {
                UIPasteboard.general.string = ShortcutRouter.link(for: windowsPath)
                copiedLink = true
            } label: {
                Label(copiedLink ? "Link copied" : "Copy Home Screen shortcut link",
                      systemImage: copiedLink ? "checkmark" : "link")
            }
        } header: {
            Text("madeira-bcd: Home Screen")
        } footer: {
            Text("In the Shortcuts app: new shortcut, Open URLs, paste the link, then Share > Add to Home Screen.")
        }
    }
}

/// Settings › Interface: which screen Madeira starts with.
struct BCDInterfacePicker: View {
    @State private var choice = FrontendChoice.preferred
    @State private var restartNotice = false

    var body: some View {
        Picker("Start with", selection: Binding(get: { choice }, set: { value in
            choice = value
            FrontendChoice.choose(value)
            restartNotice = true
        })) {
            Text("Library").tag("new")
            Text("madeira-bcd home").tag("bcd")
            Text("Developer interface").tag("old")
        }
        .alert("Restart Madeira", isPresented: $restartNotice) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("Close Madeira from the app switcher and open it again to switch interfaces.")
        }
    }
}

/// Adds every game madeira-bcd's home screen finds in drive_c (its main exe)
/// to upstream's library, once.
enum BCDLibraryImport {
    static func run(done: @escaping (Int) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let games = LibraryGame.group(GameLibrary.scan())
            var found: [LibraryEntry] = []
            for game in games {
                let exe = game.primary
                guard var entry = try? LibraryModel.inspect(exe.url) else { continue }
                entry.title = game.title
                found.append(entry)
            }
            DispatchQueue.main.async {
                let model = LibraryModel.shared
                let known = Set(model.entries.map { $0.relativePath.lowercased() })
                var added = 0
                for entry in found where !known.contains(entry.relativePath.lowercased()) {
                    model.save(entry)
                    added += 1
                }
                LogStore.shared.log("[bcd] library import: \(added) added, \(found.count - added) already there")
                done(added)
            }
        }
    }
}


/// "Older NVIDIA card (Direct3D 9)" (Game details › Compatibility): Direct3D 9
/// names a GeForce 7900 GS with NVIDIA's driver file, as the d3d9.dll wrapper
/// New Vegas players install does. Fallout 3 and New Vegas pick their render
/// path from the card's name and the driver: with Madeira's own ("Apple ...",
/// "DXMT (Metal)") they take the basic one (Shader Package 2), and New Vegas
/// crashes loading a save at 00B57AA9 right after building faces; the
/// wrapper's identity gives NVIDIA's (Shader Package 13). The ids alone did not
/// help (2026-10-26 logs): the driver name is the part that counts
/// (d3d9.customDriver, willfaust/dxmt d3d9_interface.cpp).
enum D3D9Identity {
    static let olderNvidiaName = "NVIDIA GeForce 7900 GS"

    struct Card { let options: [String] }
    static let olderNvidia = Card(options: [
        "d3d9.customVendorId=10de", "d3d9.customDeviceId=0292",
        "d3d9.customDeviceDesc=\"\(olderNvidiaName)\"", "d3d9.customDriver=nv4_disp.dll",
    ])

    /// Games that keep the card's name in their prefs (sD3DDevice) and open their
    /// launcher when it changes: a second 32-bit program, which ends the session.
    /// App ID -> the file under Documents/My Games.
    static let prefsFiles: [Int: String] = [
        22380: "FalloutNV/FalloutPrefs.ini",                                   // Fallout: New Vegas
        22300: "Fallout3/FalloutPrefs.ini", 22370: "Fallout3/FalloutPrefs.ini", // Fallout 3, GOTY
    ]

    /// Keeps the game's sD3DDevice on the card it will see, before a launch (no session runs).
    static func syncGamePrefs(appID: Int, olderNvidia: Bool) {
        guard let relative = prefsFiles[appID] else { return }
        let users = LibraryModel.drive.appendingPathComponent("users", isDirectory: true)
        let metalName = MTLCreateSystemDefaultDevice()?.name
        for user in (try? FileManager.default.contentsOfDirectory(atPath: users.path)) ?? [] {
            let file = users.appendingPathComponent(user).appendingPathComponent("Documents/My Games/" + relative)
            guard let data = try? Data(contentsOf: file) else { continue }
            let utf8 = String(data: data, encoding: .utf8)
            guard let text = utf8 ?? String(data: data, encoding: .isoLatin1),
                  let updated = prefsText(text, olderNvidia: olderNvidia, metalName: metalName),
                  let out = updated.data(using: utf8 != nil ? .utf8 : .isoLatin1) else { continue }
            do {
                try out.write(to: file, options: .atomic)
                LogStore.shared.log("[d3d9-identity] app=\(appID) \(relative): sD3DDevice set to the card the game sees")
            } catch {
                LogStore.shared.log("[d3d9-identity] app=\(appID) \(relative): not written: \(error.localizedDescription)", level: .error)
            }
        }
    }

    /// The prefs with sD3DDevice naming the card the game will see, or nil when nothing
    /// changes. Switching off puts back the Metal name only over the name this setting
    /// wrote, never over a name the game or the user chose.
    static func prefsText(_ text: String, olderNvidia: Bool, metalName: String?) -> String? {
        var lines = text.components(separatedBy: "\n")
        var changed = false
        for (i, raw) in lines.enumerated() {
            let cr = raw.hasSuffix("\r")
            let line = cr ? String(raw.dropLast()) : raw
            guard line.lowercased().hasPrefix("sd3ddevice=") else { continue }
            let key = line.prefix { $0 != "=" }
            let current = line.dropFirst(key.count + 1).trimmingCharacters(in: CharacterSet(charactersIn: "\" \t"))
            let wanted: String?
            if olderNvidia { wanted = current == olderNvidiaName ? nil : olderNvidiaName }
            else { wanted = current == olderNvidiaName ? metalName : nil }
            guard let wanted else { continue }
            lines[i] = "\(key)=\"\(wanted)\"" + (cr ? "\r" : "")
            changed = true
        }
        return changed ? lines.joined(separator: "\n") : nil
    }
}
