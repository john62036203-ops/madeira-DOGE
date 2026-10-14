// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright 2026 125hz
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import Foundation

// Valve's text KeyValues format is used for library folders and app manifests.
// Keep this reader independent of the UI and never write Steam's own files.
indirect enum SteamValue: Sendable {
    case text(String)
    case object([String: SteamValue])
    var fields: [String: SteamValue] { if case .object(let value) = self { return value }; return [:] }
    var string: String? { if case .text(let value) = self { return value }; return nil }
    subscript(_ key: String) -> SteamValue? { fields[key.lowercased()] }
}

enum SteamFileError: LocalizedError {
    case invalid(String)
    var errorDescription: String? { if case .invalid(let reason) = self { return reason }; return nil }
}

struct SteamKeyValues {
    private var bytes: [UInt8]
    private var position = 0
    private var tokens = 0
    init(_ data: Data) throws {
        guard data.count <= 4 * 1024 * 1024 else { throw SteamFileError.invalid("Steam metadata is too large.") }
        bytes = Array(data)
        if bytes.starts(with: [0xef, 0xbb, 0xbf]) { position = 3 }
    }
    private enum Token: Equatable { case word(String), open, close }
    private mutating func token() throws -> Token? {
        while position < bytes.count {
            if bytes[position] <= 32 { position += 1; continue }
            if bytes[position] == 47, position + 1 < bytes.count, bytes[position + 1] == 47 {
                while position < bytes.count && bytes[position] != 10 { position += 1 }
                continue
            }
            break
        }
        guard position < bytes.count else { return nil }
        tokens += 1
        guard tokens <= 100_000 else { throw SteamFileError.invalid("Steam metadata has too many entries.") }
        let first = bytes[position]; position += 1
        if first == 123 { return .open }; if first == 125 { return .close }
        var value: [UInt8] = []
        if first == 34 {
            while position < bytes.count {
                let byte = bytes[position]; position += 1
                if byte == 34 { return .word(String(decoding: value, as: UTF8.self)) }
                if byte == 92, position < bytes.count, bytes[position] == 34 || bytes[position] == 92 {
                    value.append(bytes[position]); position += 1
                } else { value.append(byte) }
                guard value.count <= 16_384 else { throw SteamFileError.invalid("Steam metadata contains an oversized value.") }
            }
            throw SteamFileError.invalid("Steam metadata is incomplete. Refresh after the download finishes.")
        }
        value.append(first)
        while position < bytes.count, bytes[position] > 32, bytes[position] != 123, bytes[position] != 125 {
            value.append(bytes[position]); position += 1
            guard value.count <= 16_384 else { throw SteamFileError.invalid("Steam metadata contains an oversized value.") }
        }
        return .word(String(decoding: value, as: UTF8.self))
    }
    mutating func read() throws -> SteamValue { .object(try object(depth: 0)) }
    private mutating func object(depth: Int) throws -> [String: SteamValue] {
        guard depth < 32 else { throw SteamFileError.invalid("Steam metadata is nested too deeply.") }
        var result: [String: SteamValue] = [:]
        while let key = try token() {
            if key == .close {
                guard depth > 0 else { throw SteamFileError.invalid("Steam metadata has an unexpected closing brace.") }
                return result
            }
            guard case .word(let name) = key, let value = try token(), value != .close else {
                throw SteamFileError.invalid("Steam metadata is incomplete. Try refreshing it.")
            }
            switch value {
            case .open: result[name.lowercased()] = .object(try object(depth: depth + 1))
            case .word(let text): result[name.lowercased()] = .text(text)
            case .close: break
            }
        }
        guard depth == 0 else { throw SteamFileError.invalid("Steam metadata is incomplete. Try refreshing it.") }
        return result
    }
}

// MARK: - Binary app info

/// One Windows entry of a game's Steam launch options (its app info's
/// config/launch list), for example the entry a DLC adds.
struct SteamLaunchOption: Identifiable, Equatable, Sendable {
    let id: UInt32      // the config/launch key Valve's LaunchApp takes
    let title: String
    let dlc: [Int]      // config/ownsdlc: the DLC App IDs this entry needs
}

/// Steam's binary app info cache (`appcache/appinfo.vdf`, versions 27 to 29),
/// which Valve's client keeps. Read for one app's launch options; never written.
enum SteamAppInfo {
    static let maxFileBytes = 1 << 30
    /// research/madeira-dock with patches/madeira-dock-launch-option.patch (SH_LAUNCH_OPTION_MAX).
    static let maxOption: UInt32 = 1023

    /// The `appinfo` section of one app, or nil when the cache has no readable entry for it.
    static func app(_ appID: Int, in data: Data) -> SteamValue? {
        guard appID > 0, UInt64(appID) < UInt64(UInt32.max), data.count >= 8, data.count <= maxFileBytes else { return nil }
        return data.withUnsafeBytes { raw -> SteamValue? in
            var reader = Reader(raw: raw, position: 0)
            guard let magic = reader.u32(), reader.u32() != nil else { return nil }
            let version: Int
            switch magic {
            case 0x0756_4427: version = 27
            case 0x0756_4428: version = 28
            case 0x0756_4429: version = 29
            default: return nil
            }
            // Version 29 names keys by index into a string table at the end of the file.
            var strings: [String]?
            if version >= 29 {
                guard let offset = reader.u64(), offset >= 16, offset < UInt64(raw.count) else { return nil }
                var table = Reader(raw: raw, position: Int(offset))
                guard let count = table.u32(), count <= 1 << 20 else { return nil }
                var list: [String] = []
                list.reserveCapacity(Int(count))
                for _ in 0..<count {
                    guard let text = table.cString() else { return nil }
                    list.append(text)
                }
                strings = list
            }
            while let id = reader.u32(), id != 0 {
                guard let size = reader.u32(), Int(size) <= raw.count - reader.position else { return nil }
                let end = reader.position + Int(size)
                if Int(id) == appID {
                    // info state, last update, PICS token, text SHA-1, change number and,
                    // from version 28, the binary SHA-1, then the app's keys.
                    let start = reader.position + 4 + 4 + 8 + 20 + 4 + (version >= 28 ? 20 : 0)
                    guard start < end else { return nil }
                    var body = Reader(raw: UnsafeRawBufferPointer(rebasing: raw[start..<end]), position: 0)
                    return body.table(strings: strings, depth: 0)?["appinfo"]
                }
                reader.position = end
            }
            return nil
        }
    }

    /// The Windows launch options an app's info lists, by key. Entries for another
    /// system or a beta branch are left out.
    static func launchOptions(_ app: SteamValue) -> [SteamLaunchOption] {
        var options: [SteamLaunchOption] = []
        for (key, entry) in app["config"]?["launch"]?.fields ?? [:] {
            guard !key.isEmpty, key.utf8.count <= 4, key.utf8.allSatisfy({ (48...57).contains($0) }),
                  let id = UInt32(key), id <= maxOption else { continue }
            let config = entry["config"]
            let systems = (config?["oslist"]?.string ?? "").lowercased()
                .split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
            guard systems.isEmpty || systems.contains("windows") else { continue }
            guard (config?["betakey"]?.string ?? "").isEmpty else { continue }
            let dlc = (config?["ownsdlc"]?.string ?? "").split(separator: ",")
                .compactMap { Int($0.trimmingCharacters(in: .whitespaces)) }.filter { $0 > 0 }
            let described = (entry["description_loc"]?["english"]?.string ?? entry["description"]?.string ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            options.append(SteamLaunchOption(id: id, title: described.isEmpty ? "Launch option \(id)" : String(described.prefix(120)),
                                             dlc: Array(dlc.prefix(64))))
        }
        return options.sorted { $0.id < $1.id }
    }

    /// The launch options of one app in an app info cache file; empty when the file
    /// is missing, unreadable or does not list the app.
    static func launchOptions(appID: Int, cache: URL) -> [SteamLaunchOption] {
        guard let data = try? Data(contentsOf: cache, options: .alwaysMapped), let app = app(appID, in: data) else { return [] }
        return launchOptions(app)
    }

    private struct Reader {
        let raw: UnsafeRawBufferPointer
        var position: Int

        mutating func byte() -> UInt8? {
            guard position < raw.count else { return nil }
            defer { position += 1 }
            return raw[position]
        }
        mutating func u32() -> UInt32? {
            guard position >= 0, raw.count - position >= 4 else { return nil }
            var value: UInt32 = 0
            for index in 0..<4 { value |= UInt32(raw[position + index]) << UInt32(8 * index) }
            position += 4
            return value
        }
        mutating func u64() -> UInt64? {
            guard let low = u32(), let high = u32() else { return nil }
            return UInt64(low) | UInt64(high) << 32
        }
        mutating func cString() -> String? {
            var end = position
            while end < raw.count, raw[end] != 0, end - position <= 65_536 { end += 1 }
            guard end < raw.count, raw[end] == 0 else { return nil }
            let text = String(decoding: UnsafeRawBufferPointer(rebasing: raw[position..<end]), as: UTF8.self)
            position = end + 1
            return text
        }
        /// One binary KeyValues table, up to its end marker.
        mutating func table(strings: [String]?, depth: Int) -> SteamValue? {
            guard depth < 32 else { return nil }
            var fields: [String: SteamValue] = [:]
            while let type = byte() {
                if type == 8 || type == 11 { return .object(fields) }
                let key: String
                if let strings {
                    guard let index = u32(), Int(index) < strings.count else { return nil }
                    key = strings[Int(index)]
                } else {
                    guard let name = cString() else { return nil }
                    key = name
                }
                let value: SteamValue
                switch type {
                case 0:
                    guard let child = table(strings: strings, depth: depth + 1) else { return nil }
                    value = child
                case 1:
                    guard let text = cString() else { return nil }
                    value = .text(text)
                case 2, 4, 6:
                    guard let number = u32() else { return nil }
                    value = .text(String(Int32(bitPattern: number)))
                case 3:
                    guard let bits = u32() else { return nil }
                    value = .text(String(Float(bitPattern: bits)))
                case 7:
                    guard let number = u64() else { return nil }
                    value = .text(String(number))
                case 10:
                    guard let number = u64() else { return nil }
                    value = .text(String(Int64(bitPattern: number)))
                default:
                    return nil
                }
                fields[key.lowercased()] = value
            }
            return nil
        }
    }
}
