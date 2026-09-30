//
//  SavesAndShortcuts.swift
//  Madeira
//
//  madeira-bcd: two things Winlator and GameHub users expect.
//
//  * Save backups. A game's progress lives in the Wine prefix (C:\users\...),
//    which a prefix reset, a bad experiment or a reinstall under another
//    bundle id takes with it. Settings > Saves writes every user's Documents,
//    Saved Games and AppData (minus caches) into one zip to keep in Files or
//    iCloud, and puts one back.
//  * Home Screen shortcuts. madeira://play?exe=<Windows path> starts that game
//    (after JIT, like a tap in the library). The game sheet copies the link;
//    the Shortcuts app turns it into a Home Screen icon.
//

import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

// MARK: - Shortcut links

final class ShortcutRouter: ObservableObject {
    static let shared = ShortcutRouter()

    /// A Windows exe path waiting for the library to launch it.
    @Published var pendingExe: String?

    static func link(for windowsPath: String) -> String {
        var c = URLComponents()
        c.scheme = "madeira"
        c.host = "play"
        c.queryItems = [URLQueryItem(name: "exe", value: windowsPath)]
        return c.string ?? "madeira://play"
    }

    func handle(_ url: URL) {
        guard url.scheme?.lowercased() == "madeira", url.host?.lowercased() == "play",
              let exe = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                .queryItems?.first(where: { $0.name == "exe" })?.value, !exe.isEmpty else { return }
        LogStore.shared.log("[shortcut] asked to start \(exe)")
        pendingExe = exe
    }
}

// MARK: - Zip writing (stored, CRC-32)

enum CRC32 {
    private static let table: [UInt32] = (0..<256).map { i -> UInt32 in
        var c = UInt32(i)
        for _ in 0..<8 { c = (c & 1) != 0 ? 0xEDB8_8320 ^ (c >> 1) : c >> 1 }
        return c
    }

    static func checksum(_ data: Data) -> UInt32 {
        var c: UInt32 = 0xFFFF_FFFF
        data.withUnsafeBytes { raw in
            for b in raw.bindMemory(to: UInt8.self) { c = table[Int((c ^ UInt32(b)) & 0xFF)] ^ (c >> 8) }
        }
        return c ^ 0xFFFF_FFFF
    }
}

/// Uncompressed zip (saves are small, and many are compressed already). No
/// zip64: the backup refuses to grow past 3.5 GB.
final class ZipWriter {
    private let handle: FileHandle
    private var central = Data()
    private var count = 0
    private(set) var offset: UInt64 = 0

    init(url: URL) throws {
        FileManager.default.createFile(atPath: url.path, contents: nil)
        handle = try FileHandle(forWritingTo: url)
    }

    private static func le16(_ v: Int) -> Data { var x = UInt16(truncatingIfNeeded: v).littleEndian; return Data(bytes: &x, count: 2) }
    private static func le32(_ v: UInt32) -> Data { var x = v.littleEndian; return Data(bytes: &x, count: 4) }

    func add(name: String, data: Data) throws {
        let n = Data(name.utf8)
        let crc = CRC32.checksum(data)
        let size = UInt32(data.count)
        var local = Data()
        local += ZipWriter.le32(0x0403_4b50); local += ZipWriter.le16(20); local += ZipWriter.le16(0x0800)
        local += ZipWriter.le16(0); local += ZipWriter.le16(0); local += ZipWriter.le16(0x21)
        local += ZipWriter.le32(crc); local += ZipWriter.le32(size); local += ZipWriter.le32(size)
        local += ZipWriter.le16(n.count); local += ZipWriter.le16(0); local += n
        var cd = Data()
        cd += ZipWriter.le32(0x0201_4b50); cd += ZipWriter.le16(20); cd += ZipWriter.le16(20); cd += ZipWriter.le16(0x0800)
        cd += ZipWriter.le16(0); cd += ZipWriter.le16(0); cd += ZipWriter.le16(0x21)
        cd += ZipWriter.le32(crc); cd += ZipWriter.le32(size); cd += ZipWriter.le32(size)
        cd += ZipWriter.le16(n.count); cd += ZipWriter.le16(0); cd += ZipWriter.le16(0)
        cd += ZipWriter.le16(0); cd += ZipWriter.le16(0); cd += ZipWriter.le32(0)
        cd += ZipWriter.le32(UInt32(offset)); cd += n
        try handle.write(contentsOf: local)
        try handle.write(contentsOf: data)
        offset += UInt64(local.count + data.count)
        central += cd
        count += 1
    }

    func finish() throws {
        var end = Data()
        end += ZipWriter.le32(0x0605_4b50); end += ZipWriter.le16(0); end += ZipWriter.le16(0)
        end += ZipWriter.le16(count); end += ZipWriter.le16(count)
        end += ZipWriter.le32(UInt32(central.count)); end += ZipWriter.le32(UInt32(offset)); end += ZipWriter.le16(0)
        try handle.write(contentsOf: central)
        try handle.write(contentsOf: end)
        try handle.close()
    }
}

// MARK: - Save backups

enum SaveBackup {
    /// Folders under each C:\users\<name> that hold saves and settings.
    static let roots = ["Documents", "Saved Games", "AppData/Roaming", "AppData/LocalLow", "AppData/Local"]
    /// Path components that are caches or Windows' own files, never saves.
    static let skipped: Set<String> = ["madeira", "temp", "shadercache", "d3dscache", "nvidia", "microsoft",
                                       "cache", "caches", "crashdumps", "logs", "webcache"]
    static let maxFile = 256 << 20
    static let maxTotal: UInt64 = 3_500 << 20

    struct BackupResult { let url: URL; let files: Int; let bytes: UInt64; let skippedLarge: Int }

    /// Writes the zip into the temporary directory; entries are named from
    /// drive_c ("users/<name>/Documents/..."), which is where restore puts them.
    static func backup() throws -> BackupResult {
        guard let drive = GameLibrary.driveC else { throw PackError.message("No Windows drive.") }
        let fm = FileManager.default
        let users = drive.appendingPathComponent("users")
        let stamp = DateFormatter(); stamp.dateFormat = "yyyy-MM-dd_HH-mm"
        let out = fm.temporaryDirectory.appendingPathComponent("Madeira-saves-\(stamp.string(from: Date())).zip")
        try? fm.removeItem(at: out)
        let zip = try ZipWriter(url: out)
        var files = 0, large = 0
        for user in (try? fm.contentsOfDirectory(atPath: users.path)) ?? [] {
            for root in roots {
                let dir = users.appendingPathComponent(user).appendingPathComponent(root, isDirectory: true)
                guard let e = fm.enumerator(at: dir, includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey],
                                            options: [], errorHandler: { _, _ in true }) else { continue }
                for case let f as URL in e {
                    let v = try? f.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey, .isDirectoryKey])
                    if v?.isDirectory == true {
                        if skipped.contains(f.lastPathComponent.lowercased()) { e.skipDescendants() }
                        continue
                    }
                    guard v?.isRegularFile == true, v?.isSymbolicLink != true else { continue }
                    let size = v?.fileSize ?? 0
                    if size > maxFile { large += 1; continue }
                    if zip.offset + UInt64(size) > maxTotal { large += 1; continue }
                    guard let data = try? Data(contentsOf: f) else { continue }
                    let rel = String(f.path.dropFirst(drive.path.count)).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
                    try zip.add(name: rel, data: data)
                    files += 1
                }
            }
        }
        try zip.finish()
        return BackupResult(url: out, files: files, bytes: zip.offset, skippedLarge: large)
    }

    /// Puts a backup's files back (overwriting). Only entries under users/.
    static func restore(from url: URL) throws -> Int {
        guard let drive = GameLibrary.driveC else { throw PackError.message("No Windows drive.") }
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        let zip = try ZipArchive(try Data(contentsOf: url))
        let fm = FileManager.default
        var n = 0
        for e in zip.entries where !e.name.hasSuffix("/") {
            let parts = e.name.split(separator: "/").map(String.init)
            guard parts.count >= 3, parts[0].lowercased() == "users",
                  !parts.contains(".."), !parts.contains(where: { $0.isEmpty }) else { continue }
            let dst = parts.reduce(drive) { $0.appendingPathComponent($1) }
            try fm.createDirectory(at: dst.deletingLastPathComponent(), withIntermediateDirectories: true)
            try zip.extract(e).write(to: dst, options: .atomic)
            n += 1
        }
        if n == 0 { throw PackError.message("That zip holds no saves (nothing under users/).") }
        return n
    }
}

struct ActivitySheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

/// Settings > Saves.
struct SavesSection: View {
    @State private var busy = false
    @State private var message: String?
    @State private var shareURL: URL?
    @State private var importing = false
    @State private var pendingRestore: URL?

    var body: some View {
        Section {
            Button {
                busy = true
                message = nil
                DispatchQueue.global(qos: .userInitiated).async {
                    let r = Swift.Result { try SaveBackup.backup() }
                    DispatchQueue.main.async {
                        busy = false
                        switch r {
                        case .success(let b):
                            message = "\(b.files) files, \(ByteCountFormatter.string(fromByteCount: Int64(b.bytes), countStyle: .file))"
                                + (b.skippedLarge > 0 ? "; \(b.skippedLarge) very large files left out" : "")
                            shareURL = b.url
                        case .failure(let e):
                            message = e.localizedDescription
                        }
                    }
                }
            } label: {
                HStack {
                    Label("Back up saves", systemImage: "externaldrive.badge.icloud")
                    if busy { Spacer(); ProgressView() }
                }
            }
            .disabled(busy)
            Button { importing = true } label: {
                Label("Restore saves from a backup…", systemImage: "arrow.uturn.backward.circle")
            }
            .disabled(busy)
            if let m = message { Text(m).font(.caption).foregroundStyle(.secondary) }
        } header: {
            Text("Saves")
        } footer: {
            Text("A backup is one zip of every Windows user's Documents, Saved Games and AppData (caches left out), "
                 + "to keep in Files or iCloud Drive. Restoring puts those files back and overwrites saves with "
                 + "the same names.")
        }
        .sheet(item: Binding(get: { shareURL.map { SharedFile(url: $0) } }, set: { if $0 == nil { shareURL = nil } })) { f in
            ActivitySheet(items: [f.url])
        }
        .fileImporter(isPresented: $importing, allowedContentTypes: [.zip, .data]) { r in
            if case .success(let url) = r { pendingRestore = url }
        }
        .confirmationDialog("Restore saves from \(pendingRestore?.lastPathComponent ?? "the backup")?",
                            isPresented: Binding(get: { pendingRestore != nil }, set: { if !$0 { pendingRestore = nil } }),
                            titleVisibility: .visible) {
            Button("Restore", role: .destructive) {
                guard let url = pendingRestore else { return }
                pendingRestore = nil
                busy = true
                DispatchQueue.global(qos: .userInitiated).async {
                    let r = Swift.Result { try SaveBackup.restore(from: url) }
                    DispatchQueue.main.async {
                        busy = false
                        switch r {
                        case .success(let n): message = "\(n) files restored."
                        case .failure(let e): message = e.localizedDescription
                        }
                    }
                }
            }
        } message: {
            Text("Files with the same names in C:\\users are overwritten.")
        }
    }
}

struct SharedFile: Identifiable {
    let url: URL
    var id: String { url.path }
}
