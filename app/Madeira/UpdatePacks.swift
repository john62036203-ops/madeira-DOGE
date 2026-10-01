//
//  UpdatePacks.swift
//  Madeira
//
//  madeira-bcd: update packs -- new PE DLLs without a new IPA.
//
//  Most fixes land in the Windows-side DLLs (the D3D12 runtime above all), and
//  those are data to iOS: Wine maps them into the JIT pool, nothing signs them.
//  So a pack -- a zip of DLLs plus madeira-pack.json -- can replace them from
//  inside the app. Settings > Updates checks the "packs" release of this repo
//  (built by .github/workflows/build-pack.yml in a few minutes), installs one
//  with a tap, or takes a zip from Files (the GitHub artifact as downloaded).
//
//  Safety rails, in order:
//  * native ABI: a pack is built against one native half (winemetal, the
//    conversion service, ntdll...). tools/native-abi.sh hashes it the same way
//    in both workflows; Info.plist carries this app's (MadeiraNativeABI), and a
//    pack with another is refused -- that fix needs a new IPA.
//  * age: a pack older than the app build (MadeiraBuilt) is not used, so a
//    fresh IPA is never overridden by a stale pack of the same ABI.
//  * integrity: every file's SHA-256 is checked on install AND at each launch;
//    only arm64ec/aarch64/i386-windows paths are accepted.
//  WineProcessBridge.m links the farm entries to the pack's files
//  (madeira_pe_source) when MADEIRA_PACK_DIR is set, and only then.
//

import Foundation
import SwiftUI
import Compression
import CryptoKit
import UniformTypeIdentifiers

// MARK: - This app build

enum AppBuild {
    static func info(_ key: String) -> String? {
        guard let s = Bundle.main.object(forInfoDictionaryKey: key) as? String, !s.isEmpty else { return nil }
        return s
    }
    static var number: Int { Int(info("CFBundleVersion") ?? "") ?? 0 }
    static var version: String { info("CFBundleShortVersionString") ?? "?" }
    /// tools/native-abi.sh of the commit this IPA was built from.
    static var nativeABI: String? { info("MadeiraNativeABI") }
    /// The D3D12 shader cache identity (tools/build-madeira-d3d12-dll.sh).
    static var shaderCacheID: String? { info("MadeiraShaderCacheID") }
    static var commit: String? { info("MadeiraCommit") }
    static var built: String? { info("MadeiraBuilt") }
    static var repo: String { info("MadeiraRepo") ?? "bahacan16/madeira-bcd" }
}

// MARK: - Pack model

struct PackFile: Codable, Hashable {
    let path: String
    let sha256: String
    let size: Int?
}

struct PackManifest: Codable, Identifiable {
    let format: Int
    let kind: String
    let build: Int
    let commit: String?
    let branch: String?
    let created: String?
    let nativeABI: String
    let notes: String?
    let files: [PackFile]
    /// index.json only
    let asset: String?
    let url: String?
    let size: Int?

    var id: Int { build }
    var shortCommit: String { String((commit ?? "").prefix(7)) }
    var dllNames: String {
        Set(files.map { ($0.path as NSString).lastPathComponent }).sorted().joined(separator: ", ")
    }

    enum CodingKeys: String, CodingKey {
        case format, kind, build, commit, branch, created, notes, files, asset, url, size
        case nativeABI = "native_abi"
    }
}

struct PackAppEntry: Codable {
    let build: Int
    let nativeABI: String
    let commit: String?
    let runURL: String?
    let created: String?

    enum CodingKeys: String, CodingKey {
        case build, commit, created
        case nativeABI = "native_abi"
        case runURL = "run_url"
    }
}

struct PackIndex: Codable {
    let packs: [PackManifest]?
    let apps: [PackAppEntry]?
}

enum PackError: LocalizedError {
    case message(String)
    var errorDescription: String? {
        switch self { case .message(let m): return m }
    }
}

// MARK: - Store

final class UpdatePacks: ObservableObject {
    static let shared = UpdatePacks()

    static let tag = "packs"
    private static let enabledKey = "madeira.packs.enabled"
    private static let allowedRoots: Set<String> = ["arm64ec-windows", "aarch64-windows", "i386-windows"]

    @Published private(set) var installed: PackManifest?
    @Published private(set) var index: PackIndex?
    @Published private(set) var busy = false
    @Published private(set) var lastChecked: Date?
    @Published var message: String?
    @Published var enabled: Bool {
        didSet { UserDefaults.standard.set(enabled, forKey: UpdatePacks.enabledKey) }
    }

    private init() {
        enabled = UserDefaults.standard.object(forKey: UpdatePacks.enabledKey) as? Bool ?? true
        installed = UpdatePacks.readInstalled()
    }

    // MARK: Paths

    static var baseDir: URL? {
        guard let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
            return nil
        }
        let dir = base.appendingPathComponent("MadeiraPacks", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }
    static var activeDir: URL? { baseDir?.appendingPathComponent("active", isDirectory: true) }

    static func readInstalled() -> PackManifest? {
        guard let dir = activeDir,
              let data = try? Data(contentsOf: dir.appendingPathComponent("madeira-pack.json")) else { return nil }
        return try? JSONDecoder().decode(PackManifest.self, from: data)
    }

    // MARK: Rules

    /// Why `pack` cannot run on this app build, or nil when it can.
    static func incompatibility(_ pack: PackManifest) -> String? {
        guard let abi = AppBuild.nativeABI else {
            return "This app build predates update packs; install a newer IPA once."
        }
        if pack.nativeABI != abi {
            return "Built for another native half (ABI \(pack.nativeABI), this app \(abi)); it needs a newer IPA."
        }
        if let built = AppBuild.built, let created = pack.created, created < built {
            return "Older than this app build; the app already carries newer DLLs."
        }
        return nil
    }

    var installedUsable: Bool {
        guard enabled, let p = installed else { return false }
        return UpdatePacks.incompatibility(p) == nil
    }

    /// Compatible packs from the index, newest first.
    var compatiblePacks: [PackManifest] {
        (index?.packs ?? []).filter { UpdatePacks.incompatibility($0) == nil }.sorted { $0.build > $1.build }
    }

    /// The newest compatible pack when it is not the one installed.
    var available: PackManifest? {
        guard let best = compatiblePacks.first else { return nil }
        if let cur = installed, UpdatePacks.incompatibility(cur) == nil, cur.build >= best.build { return nil }
        return best
    }

    /// Packs published after the newest compatible one that need a newer app.
    var packsNeedingNewerApp: Int {
        let best = compatiblePacks.first?.build ?? 0
        return (index?.packs ?? []).filter { $0.build > best && $0.nativeABI != AppBuild.nativeABI }.count
    }

    /// The newest IPA build recorded in the index, when newer than this one.
    var newerApp: PackAppEntry? {
        guard let a = index?.apps?.max(by: { $0.build < $1.build }), a.build > AppBuild.number else { return nil }
        return a
    }

    // MARK: Launch

    /// Called before Wine starts (ExperimentalSettings.exportToEnvironment).
    /// Exports the shader cache identity always, and the pack only when it is
    /// enabled, compatible and every file still hashes to its manifest.
    static func exportEnvironment() {
        if let sc = AppBuild.shaderCacheID { setenv("MADEIRA_SC_ID", sc, 1) } else { unsetenv("MADEIRA_SC_ID") }
        unsetenv("MADEIRA_PACK_DIR")
        unsetenv("MADEIRA_PACK_ID")
        let enabled = UserDefaults.standard.object(forKey: enabledKey) as? Bool ?? true
        guard enabled, let pack = readInstalled(), let dir = activeDir else { return }
        if let why = incompatibility(pack) {
            LogStore.shared.log("[pack] update pack \(pack.build) not used: \(why)")
            return
        }
        for f in pack.files {
            guard let data = try? Data(contentsOf: dir.appendingPathComponent(f.path)),
                  sha256(data) == f.sha256.lowercased() else {
                LogStore.shared.log("[pack] update pack \(pack.build) not used: \(f.path) is missing or damaged")
                return
            }
        }
        setenv("MADEIRA_PACK_DIR", dir.path, 1)
        setenv("MADEIRA_PACK_ID", "pack \(pack.build) (\(pack.shortCommit))", 1)
        LogStore.shared.log("[pack] update pack \(pack.build) (\(pack.shortCommit)) active: \(pack.dllNames)")
    }

    // MARK: Actions

    var indexURL: URL? {
        URL(string: "https://github.com/\(AppBuild.repo)/releases/download/\(UpdatePacks.tag)/index.json")
    }

    func refresh(silent: Bool = false) {
        guard !busy, let url = indexURL else { return }
        busy = true
        if !silent { message = nil }
        var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 30)
        req.setValue("Madeira/\(AppBuild.version)", forHTTPHeaderField: "User-Agent")
        URLSession.shared.dataTask(with: req) { data, response, error in
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            var decoded: PackIndex?
            var problem: String?
            if let error { problem = error.localizedDescription }
            else if status == 404 { problem = "No update packs have been published yet." }
            else if status != 200 { problem = "The pack index answered HTTP \(status)." }
            else if let data {
                decoded = try? JSONDecoder().decode(PackIndex.self, from: data)
                if decoded == nil { problem = "The pack index could not be read." }
            }
            DispatchQueue.main.async {
                self.busy = false
                self.lastChecked = Date()
                if let decoded { self.index = decoded }
                if !silent {
                    if let problem { self.message = problem }
                    else if let a = self.available { self.message = "Pack \(a.build) is available." }
                    else { self.message = "Up to date." }
                }
            }
        }.resume()
    }

    func install(_ pack: PackManifest) {
        guard !busy, let s = pack.url, let url = URL(string: s) else { return }
        busy = true
        message = "Downloading pack \(pack.build)…"
        URLSession.shared.dataTask(with: url) { data, response, error in
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            let result: Result<PackManifest, Error>
            if let error { result = .failure(error) }
            else if status != 200 || data == nil { result = .failure(PackError.message("Download failed (HTTP \(status)).")) }
            else { result = Result { try UpdatePacks.installZip(data!) } }
            DispatchQueue.main.async { self.finish(result) }
        }.resume()
    }

    func importFile(_ url: URL) {
        guard !busy else { return }
        busy = true
        message = "Reading \(url.lastPathComponent)…"
        DispatchQueue.global(qos: .userInitiated).async {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            let result = Result<PackManifest, Error> {
                try UpdatePacks.installZip(try Data(contentsOf: url))
            }
            DispatchQueue.main.async { self.finish(result) }
        }
    }

    func remove() {
        if let dir = UpdatePacks.activeDir { try? FileManager.default.removeItem(at: dir) }
        installed = nil
        message = "Update pack removed; the app's own DLLs are used."
    }

    private func finish(_ result: Result<PackManifest, Error>) {
        busy = false
        switch result {
        case .success(let m):
            installed = m
            enabled = true
            message = "Pack \(m.build) installed (\(m.dllNames)). It is used from the next game start."
        case .failure(let e):
            message = e.localizedDescription
        }
    }

    // MARK: Install

    static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// Unpacks, checks and swaps in a pack. Runs off the main thread.
    static func installZip(_ data: Data, depth: Int = 0) throws -> PackManifest {
        let zip = try ZipArchive(data)
        guard let manEntry = zip.entry(named: "madeira-pack.json") else {
            // A zip of the zip (how some browsers save the artifact): look one level in.
            if depth == 0, let inner = zip.entries.first(where: { $0.name.lowercased().hasSuffix(".zip") }), zip.entries.count == 1 {
                return try installZip(try zip.extract(inner), depth: 1)
            }
            throw PackError.message("Not an update pack: madeira-pack.json is missing.")
        }
        let man: PackManifest
        do { man = try JSONDecoder().decode(PackManifest.self, from: try zip.extract(manEntry)) }
        catch { throw PackError.message("madeira-pack.json could not be read: \(error.localizedDescription)") }
        guard man.kind == "madeira-pack", man.format == 1 else {
            throw PackError.message("Unknown pack format (\(man.kind) \(man.format)).")
        }
        if let why = incompatibility(man) { throw PackError.message("Pack \(man.build): \(why)") }
        guard !man.files.isEmpty else { throw PackError.message("Pack \(man.build) lists no files.") }

        guard let base = baseDir, let active = activeDir else { throw PackError.message("No Application Support directory.") }
        let fm = FileManager.default
        let staging = base.appendingPathComponent("staging-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: staging, withIntermediateDirectories: true)
        do {
            for f in man.files {
                let comps = f.path.split(separator: "/").map(String.init)
                guard comps.count == 2, allowedRoots.contains(comps[0]),
                      !comps[1].isEmpty, comps[1] != "..", !comps[1].hasPrefix(".") else {
                    throw PackError.message("Pack \(man.build) has a file outside the DLL folders: \(f.path)")
                }
                guard let e = zip.entry(named: f.path) else {
                    throw PackError.message("Pack \(man.build) is missing \(f.path).")
                }
                let bytes = try zip.extract(e)
                guard sha256(bytes) == f.sha256.lowercased() else {
                    throw PackError.message("\(f.path) does not match its checksum; the download is damaged.")
                }
                let dir = staging.appendingPathComponent(comps[0], isDirectory: true)
                try fm.createDirectory(at: dir, withIntermediateDirectories: true)
                try bytes.write(to: dir.appendingPathComponent(comps[1]), options: .atomic)
            }
            try zip.extract(manEntry).write(to: staging.appendingPathComponent("madeira-pack.json"), options: .atomic)
            // Swap: the old pack moves aside first, so a failure never leaves half of each.
            let old = base.appendingPathComponent("old-\(UUID().uuidString)", isDirectory: true)
            if fm.fileExists(atPath: active.path) { try fm.moveItem(at: active, to: old) }
            try fm.moveItem(at: staging, to: active)
            try? fm.removeItem(at: old)
        } catch {
            try? fm.removeItem(at: staging)
            throw error
        }
        return man
    }
}

// MARK: - ZIP reading (stored and deflate, zip64 aware)

struct ZipArchive {
    struct Entry {
        let name: String
        let method: UInt16
        let compressedSize: Int
        let size: Int
        let localOffset: Int
    }

    private let bytes: [UInt8]
    let entries: [Entry]

    init(_ data: Data) throws {
        let b = [UInt8](data)
        bytes = b
        func u16(_ o: Int) throws -> Int {
            guard o >= 0, o + 2 <= b.count else { throw PackError.message("The zip is truncated.") }
            return Int(b[o]) | Int(b[o + 1]) << 8
        }
        func u32(_ o: Int) throws -> Int {
            guard o >= 0, o + 4 <= b.count else { throw PackError.message("The zip is truncated.") }
            return Int(b[o]) | Int(b[o + 1]) << 8 | Int(b[o + 2]) << 16 | Int(b[o + 3]) << 24
        }
        func u64(_ o: Int) throws -> Int {
            let lo = try u32(o), hi = try u32(o + 4)
            guard hi < 0x10000 else { throw PackError.message("The zip is too large.") }
            return lo | hi << 32
        }
        guard b.count >= 22 else { throw PackError.message("Not a zip file.") }
        var eocd = -1
        var p = b.count - 22
        let lowest = max(0, b.count - 22 - 65_535)
        while p >= lowest {
            if b[p] == 0x50, b[p + 1] == 0x4b, b[p + 2] == 0x05, b[p + 3] == 0x06 { eocd = p; break }
            p -= 1
        }
        guard eocd >= 0 else { throw PackError.message("Not a zip file.") }
        var count = try u16(eocd + 10)
        var cdOffset = try u32(eocd + 16)
        if count == 0xFFFF || cdOffset == 0xFFFF_FFFF {
            let loc = eocd - 20
            guard try u32(loc) == 0x0706_4b50 else { throw PackError.message("Broken zip64 record.") }
            let z = try u64(loc + 8)
            guard try u32(z) == 0x0606_4b50 else { throw PackError.message("Broken zip64 record.") }
            count = try u64(z + 32)
            cdOffset = try u64(z + 48)
        }
        var list: [Entry] = []
        var q = cdOffset
        for _ in 0..<count {
            guard try u32(q) == 0x0201_4b50 else { throw PackError.message("Broken zip directory.") }
            let method = UInt16(try u16(q + 10))
            var csize = try u32(q + 20)
            var usize = try u32(q + 24)
            let nlen = try u16(q + 28), elen = try u16(q + 30), clen = try u16(q + 32)
            var loff = try u32(q + 42)
            guard q + 46 + nlen <= b.count else { throw PackError.message("The zip is truncated.") }
            let name = String(decoding: b[(q + 46)..<(q + 46 + nlen)], as: UTF8.self)
            // zip64 extra field: the 0xFFFFFFFF fields, in this order.
            var x = q + 46 + nlen
            let xend = x + elen
            while x + 4 <= xend {
                let id = try u16(x), len = try u16(x + 2)
                if id == 0x0001 {
                    var f = x + 4
                    if usize == 0xFFFF_FFFF { usize = try u64(f); f += 8 }
                    if csize == 0xFFFF_FFFF { csize = try u64(f); f += 8 }
                    if loff == 0xFFFF_FFFF { loff = try u64(f) }
                }
                x += 4 + len
            }
            list.append(Entry(name: name, method: method, compressedSize: csize, size: usize, localOffset: loff))
            q += 46 + nlen + elen + clen
        }
        entries = list
    }

    /// Exact name, or the same name under one leading folder.
    func entry(named name: String) -> Entry? {
        entries.first { $0.name == name } ?? entries.first { e in
            let parts = e.name.split(separator: "/", maxSplits: 1).map(String.init)
            return parts.count == 2 && parts[1] == name
        }
    }

    func extract(_ e: Entry) throws -> Data {
        let o = e.localOffset
        guard o + 30 <= bytes.count,
              bytes[o] == 0x50, bytes[o + 1] == 0x4b, bytes[o + 2] == 0x03, bytes[o + 3] == 0x04 else {
            throw PackError.message("Broken zip entry \(e.name).")
        }
        let nlen = Int(bytes[o + 26]) | Int(bytes[o + 27]) << 8
        let elen = Int(bytes[o + 28]) | Int(bytes[o + 29]) << 8
        let start = o + 30 + nlen + elen
        guard start + e.compressedSize <= bytes.count else { throw PackError.message("The zip is truncated.") }
        let src = bytes[start..<(start + e.compressedSize)]
        switch e.method {
        case 0:
            return Data(src)
        case 8:
            if e.size == 0 { return Data() }
            var out = Data(count: e.size)
            let written: Int = out.withUnsafeMutableBytes { dst in
                src.withUnsafeBufferPointer { s in
                    guard let d = dst.baseAddress?.assumingMemoryBound(to: UInt8.self), let sp = s.baseAddress else { return 0 }
                    return compression_decode_buffer(d, e.size, sp, s.count, nil, COMPRESSION_ZLIB)
                }
            }
            guard written == e.size else { throw PackError.message("\(e.name) could not be decompressed.") }
            return out
        default:
            throw PackError.message("\(e.name) uses zip method \(e.method), which is not supported.")
        }
    }
}

// MARK: - UI

/// Settings > Updates.
struct UpdatesSection: View {
    @ObservedObject private var packs = UpdatePacks.shared
    @State private var importing = false

    var body: some View {
        Section {
            LabeledContent("App build", value: "\(AppBuild.version) · ABI \(AppBuild.nativeABI ?? "none")")
                .font(.footnote)
            if let p = packs.installed {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Pack \(p.build) · \(p.shortCommit)").font(.subheadline.weight(.semibold))
                    Text(p.dllNames).font(.caption.monospaced()).foregroundStyle(.secondary)
                    if let n = p.notes, !n.isEmpty { Text(n).font(.caption).foregroundStyle(.secondary).lineLimit(3) }
                    if let why = UpdatePacks.incompatibility(p) {
                        Label("Not used: \(why)", systemImage: "exclamationmark.triangle")
                            .font(.caption).foregroundStyle(.orange)
                    }
                }
                Toggle("Use the update pack", isOn: $packs.enabled)
                Button(role: .destructive) { packs.remove() } label: {
                    Label("Remove pack", systemImage: "trash")
                }
            }
            Button { packs.refresh() } label: {
                HStack {
                    Label("Check for updates", systemImage: "arrow.triangle.2.circlepath")
                    if packs.busy { Spacer(); ProgressView() }
                }
            }
            .disabled(packs.busy)
            if let a = packs.available {
                Button { packs.install(a) } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Label("Install pack \(a.build)", systemImage: "arrow.down.circle.fill")
                        if let n = a.notes, !n.isEmpty { Text(n).font(.caption).foregroundStyle(.secondary).lineLimit(3) }
                    }
                }
                .disabled(packs.busy)
            }
            let older = packs.compatiblePacks.filter { $0.build != packs.available?.build && $0.build != packs.installed?.build }
            if !older.isEmpty {
                Menu {
                    ForEach(Array(older.prefix(8))) { p in
                        Button(Self.menuLabel(p)) { packs.install(p) }
                    }
                } label: {
                    Label("Other compatible packs", systemImage: "clock.arrow.circlepath")
                }
                .disabled(packs.busy)
            }
            if let app = packs.newerApp {
                if let s = app.runURL, let url = URL(string: s) {
                    Link(destination: url) {
                        Label("App build 0.1.\(app.build) exists (needs a new IPA)", systemImage: "arrow.up.forward.app")
                    }
                } else {
                    Label("App build 0.1.\(app.build) exists (needs a new IPA)", systemImage: "arrow.up.forward.app")
                }
            }
            if packs.packsNeedingNewerApp > 0 {
                Text("\(packs.packsNeedingNewerApp) newer pack(s) need a newer app build.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Button { importing = true } label: {
                Label("Install a pack from Files…", systemImage: "doc.zipper")
            }
            .disabled(packs.busy)
            if let m = packs.message {
                Text(m).font(.caption).foregroundStyle(.secondary)
            }
        } header: {
            Text("Updates")
        } footer: {
            Text("Update packs replace the Windows-side DLLs (the D3D12 runtime) without reinstalling Madeira. "
                 + "A pack only installs over the app build it was made for; changes to the app itself still "
                 + "need a new IPA. The artifact zip from a pack build can be installed from Files as well.")
        }
        .fileImporter(isPresented: $importing, allowedContentTypes: [.zip, .data]) { result in
            if case .success(let url) = result { packs.importFile(url) }
        }
    }

    private static func menuLabel(_ p: PackManifest) -> String {
        var s = "Pack \(p.build) · \(p.shortCommit)"
        if let n = p.notes, !n.isEmpty { s += " · " + n }
        return s
    }
}

/// The home screen's one-line notice when a pack is waiting.
struct UpdateBanner: View {
    @ObservedObject private var packs = UpdatePacks.shared

    var body: some View {
        if let a = packs.available {
            Button { packs.install(a) } label: {
                HStack(spacing: 12) {
                    Image(systemName: packs.busy ? "hourglass" : "arrow.down.circle.fill").font(.title2)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Update pack \(a.build) available").font(.headline)
                        Text(a.notes ?? a.dllNames).font(.caption).lineLimit(2).foregroundStyle(.white.opacity(0.8))
                    }
                    Spacer()
                    Text("Install").font(.subheadline.weight(.semibold))
                }
                .foregroundStyle(.white)
                .padding(14)
                .background(LinearGradient(colors: [.teal, .blue.opacity(0.8)], startPoint: .leading, endPoint: .trailing),
                            in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(packs.busy)
        } else if let m = packs.message, packs.installed != nil, m.hasPrefix("Pack ") && m.contains("installed") {
            Label(m, systemImage: "checkmark.circle.fill")
                .font(.caption)
                .foregroundStyle(.green)
        }
    }
}
