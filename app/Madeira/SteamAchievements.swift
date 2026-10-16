// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright 2026 madeira-doge contributors
// Madeira Converter Exception: see LICENSE-EXCEPTION.md
//
// A Steam game's achievements and the account's trading cards for it, on the
// game's Game details page. Written from Valve's public protocol definitions:
//   - ClientGetUserStats (EMsg 818/819): the account's unlock times per
//     achievement bit, and the game's stats schema (binary KeyValues) that names
//     each bit;
//   - Player.GetGameAchievements#1: localized names, descriptions, icons and the
//     global unlock percentage;
//   - Econ.GetInventoryItemsWithDescriptions#1: the account's Steam inventory
//     (app 753, context 6), filtered to this game's trading cards.
// Read-only: nothing here changes stats, achievements or the inventory.

import Foundation
import SwiftUI

// MARK: - Model

struct SteamAchievement: Identifiable, Equatable, Sendable {
    var id: String              // the API name
    var name: String
    var detail: String
    var iconURL: URL?
    var grayIconURL: URL?
    var hidden: Bool
    var unlockTime: UInt32      // 0 = locked
    var globalPercent: Double?

    var unlocked: Bool { unlockTime != 0 }
}

struct SteamTradingCard: Identifiable, Equatable, Sendable {
    var id: String              // classid
    var name: String
    var imageURL: URL?
    var count: Int
    var foil: Bool
}

struct SteamGameExtras: Equatable, Sendable {
    var achievements: [SteamAchievement] = []
    /// nil: read; otherwise why the achievements could not be read.
    var achievementsProblem: String?
    var cards: [SteamTradingCard] = []
    var cardsProblem: String?
}

// MARK: - Steam languages

enum SteamLanguage {
    /// Steam's language name for the device's first preferred language.
    static var current: String {
        let pref = (Locale.preferredLanguages.first ?? "en").lowercased()
        if pref.hasPrefix("zh-hant") || pref.hasPrefix("zh-tw") || pref.hasPrefix("zh-hk") || pref.hasPrefix("zh-mo") { return "tchinese" }
        if pref.hasPrefix("zh") { return "schinese" }
        let map = ["ja": "japanese", "ko": "koreana", "tr": "turkish", "de": "german", "fr": "french", "es": "spanish",
                   "it": "italian", "pt": "portuguese", "ru": "russian", "pl": "polish", "th": "thai"]
        return map[String(pref.prefix(2))] ?? "english"
    }
}

// MARK: - Binary KeyValues (the stats schema)

/// Valve's binary KeyValues: a type byte, a NUL-terminated key, then the value;
/// type 0 opens a subtree closed by type 8 (or 11). Keys are matched without case.
struct SteamBinaryKV: Equatable, Sendable {
    var value: String?
    var children: [String: SteamBinaryKV] = [:]
    var order: [String] = []

    subscript(_ key: String) -> SteamBinaryKV? { children[key.lowercased()] }

    /// The text of a node that is either a string or a per-language subtree.
    func localized(_ language: String) -> String? {
        if let value, !value.isEmpty { return value }
        if let v = self[language]?.value, !v.isEmpty { return v }
        if let v = self["english"]?.value, !v.isEmpty { return v }
        return order.lazy.compactMap { self.children[$0]?.value }.first { !$0.isEmpty }
    }

    static func parse(_ data: Data) -> SteamBinaryKV? {
        let b = [UInt8](data)
        var p = 0

        func cstr() -> String? {
            guard p <= b.count, let end = b[p...].firstIndex(of: 0) else { return nil }
            let s = String(decoding: b[p..<end], as: UTF8.self)
            p = end + 1
            return s
        }
        func little(_ n: Int) -> UInt64? {
            guard p + n <= b.count else { return nil }
            var v: UInt64 = 0
            for i in 0..<n { v |= UInt64(b[p + i]) << (8 * UInt64(i)) }
            p += n
            return v
        }
        func wide() -> String? {
            var units: [UInt16] = []
            while true {
                guard let u = little(2) else { return nil }
                if u == 0 { break }
                units.append(UInt16(u))
            }
            return String(decoding: units, as: UTF16.self)
        }
        func node(_ depth: Int) -> SteamBinaryKV? {
            guard depth < 64 else { return nil }
            var n = SteamBinaryKV()
            while p < b.count {
                let type = b[p]
                p += 1
                if type == 8 || type == 11 { return n }
                guard let key = cstr() else { return nil }
                var child = SteamBinaryKV()
                switch type {
                case 0: guard let sub = node(depth + 1) else { return nil }; child = sub
                case 1: guard let s = cstr() else { return nil }; child.value = s
                case 2: guard let v = little(4) else { return nil }; child.value = String(Int32(truncatingIfNeeded: v))
                case 3: guard let v = little(4) else { return nil }; child.value = String(Float(bitPattern: UInt32(truncatingIfNeeded: v)))
                case 4, 6: guard let v = little(4) else { return nil }; child.value = String(UInt32(truncatingIfNeeded: v))
                case 5: guard let s = wide() else { return nil }; child.value = s
                case 7: guard let v = little(8) else { return nil }; child.value = String(v)
                case 10: guard let v = little(8) else { return nil }; child.value = String(Int64(bitPattern: v))
                default: return nil
                }
                let k = key.lowercased()
                if n.children[k] == nil { n.order.append(k) }
                n.children[k] = child
            }
            return n   // a top level that simply ends
        }
        return node(0)
    }
}

// MARK: - Parsers

enum SteamAchievementsParser {
    struct UserStats: Equatable {
        var eresult: Int = 2
        var schema = Data()
        /// stat id -> unlock time per bit (0 = locked)
        var blocks: [UInt32: [UInt32]] = [:]
    }

    /// CMsgClientGetUserStatsResponse: eresult = 2, schema = 4,
    /// achievement_blocks = 6 { achievement_id = 1, repeated fixed32 unlock_time = 2 }.
    static func userStats(_ data: Data) throws -> UserStats {
        var out = UserStats()
        var d = ProtobufDecoder(data)
        while let next = try d.readTag() {
            let (field, wire) = (next.fieldNumber, next.wireType)
            switch (field, wire) {
            case (2, .varint): out.eresult = Int(Int32(truncatingIfNeeded: try d.readVarint()))
            case (4, .lengthDelimited): out.schema = try d.readBytes()
            case (6, .lengthDelimited):
                var b = ProtobufDecoder(try d.readBytes())
                var id: UInt32 = 0
                var times: [UInt32] = []
                while let next = try b.readTag() {
                    let (f, w) = (next.fieldNumber, next.wireType)
                    switch (f, w) {
                    case (1, .varint): id = UInt32(truncatingIfNeeded: try b.readVarint())
                    case (2, .fixed32): times.append(try b.readFixed32())
                    case (2, .lengthDelimited):
                        var packed = ProtobufDecoder(try b.readBytes())
                        while !packed.isAtEnd { times.append(try packed.readFixed32()) }
                    default: try b.skip(wireType: w)
                    }
                }
                out.blocks[id] = times
            default: try d.skip(wireType: wire)
            }
        }
        return out
    }

    struct SchemaAchievement: Equatable {
        var statID: UInt32
        var bit: Int
        var apiName: String
        var name: String?
        var detail: String?
        var hidden: Bool
        var icon: String?
        var iconGray: String?
    }

    /// The achievement bits of a stats schema: stats { <id> { type 4 (ACHIEVEMENTS),
    /// bits { <bit> { name, display { name, desc, hidden, icon, icon_gray } } } } }.
    static func schemaAchievements(_ schema: Data, appID: Int, language: String) -> [SchemaAchievement] {
        guard let root = SteamBinaryKV.parse(schema) else { return [] }
        let game = root[String(appID)] ?? root.order.first.flatMap { root.children[$0] }
        guard let stats = game?["stats"] else { return [] }
        var out: [SchemaAchievement] = []
        for key in stats.order {
            guard let stat = stats.children[key], let statID = UInt32(key) else { continue }
            let type = (stat["type"]?.value ?? stat["type_int"]?.value ?? "").uppercased()
            guard type == "4" || type == "ACHIEVEMENTS", let bits = stat["bits"] else { continue }
            for bitKey in bits.order {
                guard let entry = bits.children[bitKey],
                      let bit = Int(entry["bit"]?.value ?? bitKey), (0..<32).contains(bit),
                      let api = entry["name"]?.value, !api.isEmpty else { continue }
                let display = entry["display"]
                out.append(SchemaAchievement(statID: statID, bit: bit, apiName: api,
                                             name: display?["name"]?.localized(language),
                                             detail: display?["desc"]?.localized(language),
                                             hidden: display?["hidden"]?.value == "1",
                                             icon: display?["icon"]?.value, iconGray: display?["icon_gray"]?.value))
            }
        }
        return out
    }

    struct GameAchievement: Equatable {
        var apiName = ""
        var name = ""
        var detail = ""
        var icon = ""
        var iconGray = ""
        var hidden = false
        var percent: Double?
    }

    /// CPlayer_GetGameAchievements_Response: achievements = 1 { internal_name = 1,
    /// localized_name = 2, localized_desc = 3, icon = 4, icon_gray = 5, hidden = 6,
    /// player_percent_unlocked = 7 (a string) }.
    static func gameAchievements(_ data: Data) throws -> [String: GameAchievement] {
        var out: [String: GameAchievement] = [:]
        var d = ProtobufDecoder(data)
        while let next = try d.readTag() {
            let (field, wire) = (next.fieldNumber, next.wireType)
            guard field == 1, wire == .lengthDelimited else { try d.skip(wireType: wire); continue }
            var a = GameAchievement()
            var m = ProtobufDecoder(try d.readBytes())
            while let next = try m.readTag() {
                let (f, w) = (next.fieldNumber, next.wireType)
                switch (f, w) {
                case (1, .lengthDelimited): a.apiName = try m.readString()
                case (2, .lengthDelimited): a.name = try m.readString()
                case (3, .lengthDelimited): a.detail = try m.readString()
                case (4, .lengthDelimited): a.icon = try m.readString()
                case (5, .lengthDelimited): a.iconGray = try m.readString()
                case (6, .varint): a.hidden = try m.readVarint() != 0
                case (7, .lengthDelimited): a.percent = Double(try m.readString())
                default: try m.skip(wireType: w)
                }
            }
            if !a.apiName.isEmpty { out[a.apiName] = a }
        }
        return out
    }

    static func iconURL(_ value: String?, appID: Int) -> URL? {
        guard let value, !value.isEmpty else { return nil }
        if value.hasPrefix("http") { return URL(string: value) }
        return URL(string: "https://cdn.cloudflare.steamstatic.com/steamcommunity/public/images/apps/\(appID)/\(value)")
    }

    /// The schema's bits with the account's unlock times, named and pictured from
    /// Player.GetGameAchievements where it answered. Unlocked first, newest first.
    static func merge(appID: Int, stats: UserStats, game: [String: GameAchievement], language: String) -> [SteamAchievement] {
        let schema = schemaAchievements(stats.schema, appID: appID, language: language)
        var list: [SteamAchievement] = schema.map { s in
            let times = stats.blocks[s.statID] ?? []
            let time = s.bit < times.count ? times[s.bit] : 0
            let g = game[s.apiName]
            return SteamAchievement(id: s.apiName,
                                    name: (g?.name).flatMap { $0.isEmpty ? nil : $0 } ?? s.name ?? s.apiName,
                                    detail: (g?.detail).flatMap { $0.isEmpty ? nil : $0 } ?? s.detail ?? "",
                                    iconURL: iconURL((g?.icon).flatMap { $0.isEmpty ? nil : $0 } ?? s.icon, appID: appID),
                                    grayIconURL: iconURL((g?.iconGray).flatMap { $0.isEmpty ? nil : $0 } ?? s.iconGray, appID: appID),
                                    hidden: g?.hidden ?? s.hidden, unlockTime: time, globalPercent: g?.percent)
        }
        if list.isEmpty && !game.isEmpty {
            // No schema in the reply: list the game's achievements, unlock state unknown (locked).
            list = game.values.map {
                SteamAchievement(id: $0.apiName, name: $0.name.isEmpty ? $0.apiName : $0.name, detail: $0.detail,
                                 iconURL: iconURL($0.icon, appID: appID), grayIconURL: iconURL($0.iconGray, appID: appID),
                                 hidden: $0.hidden, unlockTime: 0, globalPercent: $0.percent)
            }
        }
        return list.sorted {
            if $0.unlocked != $1.unlocked { return $0.unlocked }
            if $0.unlocked { return $0.unlockTime > $1.unlockTime }
            return ($0.globalPercent ?? 0) > ($1.globalPercent ?? 0)
        }
    }

    struct Inventory: Equatable {
        struct Asset: Equatable { var classid: UInt64; var instanceid: UInt64; var amount: Int64 }
        struct Description: Equatable {
            var classid: UInt64 = 0
            var instanceid: UInt64 = 0
            var name = ""
            var iconURL = ""
            var feeApp: Int = 0
            var tags: [String: String] = [:]   // category -> internal_name
        }
        var assets: [Asset] = []
        var descriptions: [Description] = []
        var more = false
        var lastAssetID: UInt64 = 0
    }

    /// CEcon_GetInventoryItemsWithDescriptions_Response: assets = 1 { classid = 4,
    /// instanceid = 5, amount = 7 }, descriptions = 2 { classid = 2, instanceid = 3,
    /// icon_url = 6, name = 14, tags = 26 { category = 2, internal_name = 3 },
    /// market_fee_app = 28 }, more_items = 4, last_assetid = 5.
    static func inventory(_ data: Data) throws -> Inventory {
        var out = Inventory()
        var d = ProtobufDecoder(data)
        while let next = try d.readTag() {
            let (field, wire) = (next.fieldNumber, next.wireType)
            switch (field, wire) {
            case (1, .lengthDelimited):
                var a = Inventory.Asset(classid: 0, instanceid: 0, amount: 1)
                var m = ProtobufDecoder(try d.readBytes())
                while let next = try m.readTag() {
                    let (f, w) = (next.fieldNumber, next.wireType)
                    switch (f, w) {
                    case (4, .varint): a.classid = try m.readVarint()
                    case (5, .varint): a.instanceid = try m.readVarint()
                    case (7, .varint): a.amount = Int64(bitPattern: try m.readVarint())
                    default: try m.skip(wireType: w)
                    }
                }
                out.assets.append(a)
            case (2, .lengthDelimited):
                var desc = Inventory.Description()
                var m = ProtobufDecoder(try d.readBytes())
                while let next = try m.readTag() {
                    let (f, w) = (next.fieldNumber, next.wireType)
                    switch (f, w) {
                    case (2, .varint): desc.classid = try m.readVarint()
                    case (3, .varint): desc.instanceid = try m.readVarint()
                    case (6, .lengthDelimited): desc.iconURL = try m.readString()
                    case (14, .lengthDelimited): desc.name = try m.readString()
                    case (28, .varint): desc.feeApp = Int(Int32(truncatingIfNeeded: try m.readVarint()))
                    case (26, .lengthDelimited):
                        var t = ProtobufDecoder(try m.readBytes())
                        var category = "", internalName = ""
                        while let next = try t.readTag() {
                            let (tf, tw) = (next.fieldNumber, next.wireType)
                            switch (tf, tw) {
                            case (2, .lengthDelimited): category = try t.readString()
                            case (3, .lengthDelimited): internalName = try t.readString()
                            default: try t.skip(wireType: tw)
                            }
                        }
                        if !category.isEmpty { desc.tags[category] = internalName }
                    default: try m.skip(wireType: w)
                    }
                }
                out.descriptions.append(desc)
            case (4, .varint): out.more = try d.readVarint() != 0
            case (5, .varint): out.lastAssetID = try d.readVarint()
            default: try d.skip(wireType: wire)
            }
        }
        return out
    }

    /// This game's trading cards (item_class_2) in the inventory, counted per card.
    static func cards(_ inventory: Inventory, appID: Int) -> [SteamTradingCard] {
        var byClass: [UInt64: Inventory.Description] = [:]
        for desc in inventory.descriptions where desc.feeApp == appID && desc.tags["item_class"] == "item_class_2" {
            byClass[desc.classid] = desc
        }
        var counts: [UInt64: Int] = [:]
        for asset in inventory.assets where byClass[asset.classid] != nil {
            counts[asset.classid, default: 0] += Int(max(asset.amount, 1))
        }
        return byClass.values.map { desc in
            SteamTradingCard(id: String(desc.classid), name: desc.name,
                             imageURL: desc.iconURL.isEmpty ? nil
                                : URL(string: "https://community.cloudflare.steamstatic.com/economy/image/\(desc.iconURL)/192fx192f"),
                             count: counts[desc.classid] ?? 0,
                             foil: desc.tags["cardborder"] == "cardborder_1")
        }
        .filter { $0.count > 0 }
        .sorted { $0.foil != $1.foil ? !$0.foil : $0.name < $1.name }
    }
}

// MARK: - Page model

@MainActor
final class SteamGameExtrasModel: ObservableObject {
    static let shared = SteamGameExtrasModel()

    enum Phase: Equatable {
        case loading
        case ready(SteamGameExtras)
    }

    @Published private(set) var state: [Int: Phase] = [:]

    func load(_ appID: Int, force: Bool = false) async {
        if !force, case .ready = state[appID] { return }
        if case .loading = state[appID] { return }
        state[appID] = .loading
        state[appID] = .ready(await SteamOwnedLibrary.shared.fetchGameExtras(appID))
    }
}

// MARK: - Game details sections

/// The achievements and trading cards of a Steam game, under its Steam Cloud
/// section on the Game details page.
struct SteamAchievementsSection: View {
    let appID: Int
    @ObservedObject private var steam = SteamOwnedLibrary.shared
    @ObservedObject private var model = SteamGameExtrasModel.shared
    @State private var showAll = false

    private var readyExtras: SteamGameExtras? {
        if case .ready(let extras)? = model.state[appID] { return extras }
        return nil
    }

    private static let date: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .medium
        f.timeStyle = .short
        return f
    }()

    var body: some View {
        Section {
            if !steam.signedIn {
                Text("Sign in to Steam to see achievements and trading cards.").foregroundStyle(.secondary)
            } else {
                switch model.state[appID] {
                case .none, .loading?:
                    HStack(spacing: 10) { ProgressView(); Text("Loading from Steam…").foregroundStyle(.secondary) }
                        .task { await model.load(appID) }
                case .ready(let extras)?:
                    achievements(extras)
                }
            }
        } header: {
            Text("Achievements")
        }
        if steam.signedIn, let extras = readyExtras {
            Section {
                cards(extras)
            } header: {
                Text("Trading cards")
            } footer: {
                Text("From Steam for the signed-in account. Pull down or tap Refresh after playing to update.")
            }
        }
    }

    @ViewBuilder private func achievements(_ extras: SteamGameExtras) -> some View {
        if let problem = extras.achievementsProblem {
            Text(problem).font(.callout).foregroundStyle(.secondary)
        } else if extras.achievements.isEmpty {
            Text("This game has no Steam achievements.").foregroundStyle(.secondary)
        } else {
            let list = extras.achievements
            let done = list.filter(\.unlocked).count
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("\(done) of \(list.count) unlocked").font(.subheadline.weight(.medium))
                    Spacer()
                    Text("\(Int((Double(done) / Double(max(list.count, 1)) * 100).rounded()))%").foregroundStyle(.secondary)
                }
                ProgressView(value: Double(done), total: Double(max(list.count, 1)))
            }
            ForEach(showAll ? list : Array(list.prefix(8))) { row($0) }
            if list.count > 8 {
                Button(showAll ? "Show fewer" : "Show all \(list.count)") { showAll.toggle() }
            }
        }
        Button("Refresh") { Task { await model.load(appID, force: true) } }
    }

    private func row(_ a: SteamAchievement) -> some View {
        let secret = a.hidden && !a.unlocked
        return HStack(spacing: 12) {
            AsyncImage(url: a.unlocked ? a.iconURL : (a.grayIconURL ?? a.iconURL)) { image in
                image.resizable().scaledToFit()
            } placeholder: {
                RoundedRectangle(cornerRadius: 6).fill(Color.secondary.opacity(0.2))
            }
            .frame(width: 44, height: 44)
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .opacity(a.unlocked ? 1 : 0.55)
            VStack(alignment: .leading, spacing: 2) {
                Text(secret ? "Hidden achievement" : a.name).font(.subheadline.weight(.medium))
                    .foregroundColor(a.unlocked ? .primary : .secondary)
                if !secret && !a.detail.isEmpty {
                    Text(a.detail).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                }
                if a.unlocked {
                    Text("Unlocked " + Self.date.string(from: Date(timeIntervalSince1970: TimeInterval(a.unlockTime))))
                        .font(.caption2).foregroundStyle(.green)
                } else if let p = a.globalPercent {
                    Text(String(format: "%.1f%% of players", p)).font(.caption2).foregroundStyle(.secondary)
                }
            }
        }
    }

    @ViewBuilder private func cards(_ extras: SteamGameExtras) -> some View {
        if let problem = extras.cardsProblem {
            Text(problem).font(.callout).foregroundStyle(.secondary)
        } else if extras.cards.isEmpty {
            Text("No trading cards for this game in your Steam inventory.").foregroundStyle(.secondary)
        } else {
            let total = extras.cards.reduce(0) { $0 + $1.count }
            Text("\(total) card\(total == 1 ? "" : "s"), \(extras.cards.count) different").font(.subheadline.weight(.medium))
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(alignment: .top, spacing: 12) {
                    ForEach(extras.cards) { card in
                        VStack(spacing: 4) {
                            AsyncImage(url: card.imageURL) { image in
                                image.resizable().scaledToFit()
                            } placeholder: {
                                RoundedRectangle(cornerRadius: 6).fill(Color.secondary.opacity(0.2))
                            }
                            .frame(width: 84, height: 98)
                            .overlay(alignment: .topTrailing) {
                                if card.count > 1 {
                                    Text("×\(card.count)").font(.caption2.weight(.bold)).padding(.horizontal, 4)
                                        .background(.ultraThinMaterial, in: Capsule()).padding(3)
                                }
                            }
                            Text(card.name).font(.caption2).lineLimit(2).multilineTextAlignment(.center)
                                .frame(width: 84)
                            if card.foil { Text("Foil").font(.caption2.weight(.semibold)).foregroundStyle(.yellow) }
                        }
                    }
                }
                .padding(.vertical, 4)
            }
        }
    }
}
