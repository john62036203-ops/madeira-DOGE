// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import SwiftUI

/// Search the Steam store and get games onto the account (madeira-doge).
///
/// The search is Steam's public store search (store.steampowered.com/api/
/// storesearch, no sign-in). What a result offers depends on the account:
///  - owned: Install (the same download as "Your games");
///  - free to play: Get, which asks Steam for the game's free license
///    (SteamOwnedLibrary.requestFreeLicense) and then installs it;
///  - paid: Buy on Steam, which opens the store page; after buying, refresh
///    the library and the game appears under "Your games".
/// Nothing here downloads a game the account does not own.
struct SteamStoreView: View {
    @ObservedObject private var library = SteamOwnedLibrary.shared
    @ObservedObject private var dock = MadeiraDockModel.shared
    @Environment(\.openURL) private var openURL

    @State private var query = ""
    @State private var results: [StoreItem] = []
    @State private var searching = false
    @State private var message: String?
    @State private var busy = Set<Int>()
    @State private var notes: [Int: String] = [:]
    @State private var searchTask: Task<Void, Never>?
    @FocusState private var fieldFocused: Bool

    struct StoreItem: Identifiable, Hashable {
        let id: Int
        let name: String
        let priceText: String?      // nil = no price on the store (free or not for sale)
        let discount: Int?
        let windows: Bool
    }

    var body: some View {
        List {
            // A plain text field, not .searchable: the Steam page this is pushed from
            // already owns a search bar ("Search your games"), and a second
            // .searchable in the same navigation stack did not take typing.
            Section {
                HStack {
                    Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                    TextField("Search Steam games", text: $query)
                        .focused($fieldFocused)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .submitLabel(.search)
                        .onSubmit { runSearch() }
                    if !query.isEmpty {
                        Button { query = ""; results = [] } label: {
                            Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary)
                        }.buttonStyle(.plain)
                    }
                }
            }
            if let message {
                Text(message).foregroundStyle(.secondary)
            }
            ForEach(results) { item in row(item) }
        }
        .navigationTitle("Steam store").navigationBarTitleDisplayMode(.inline)
        .onChange(of: query) { _, new in
            // Search as you type, after a short pause.
            searchTask?.cancel()
            let q = new.trimmingCharacters(in: .whitespaces)
            guard q.count >= 2 else { return }
            searchTask = Task {
                try? await Task.sleep(nanoseconds: 500_000_000)
                if !Task.isCancelled { await search(q) }
            }
        }
        .overlay { if searching && results.isEmpty { ProgressView() } }
        .onAppear {
            library.start()
            fieldFocused = true
            if results.isEmpty && message == nil {
                message = "Type a game's name. Free games can be added to your account; paid games open on the Steam store."
            }
        }
    }

    // MARK: Rows

    @ViewBuilder private func row(_ item: StoreItem) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 10) {
                AsyncImage(url: URL(string: "https://cdn.cloudflare.steamstatic.com/steam/apps/\(item.id)/header.jpg")) { image in
                    image.resizable().aspectRatio(contentMode: .fill)
                } placeholder: {
                    Color.gray.opacity(0.25)
                }
                .frame(width: 92, height: 43)
                .clipShape(RoundedRectangle(cornerRadius: 4))
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.name).lineLimit(2)
                    Text(subtitle(item)).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                action(item)
            }
            if let note = notes[item.id] {
                Text(note).font(.caption).foregroundStyle(.secondary)
            }
            if let dl = library.downloads[item.id], case .active = dl.state {
                ProgressView(value: dl.progress.fraction)
            }
        }
    }

    private func subtitle(_ item: StoreItem) -> String {
        var parts: [String] = []
        if library.game(item.id) != nil { parts.append("In your library") }
        if let price = item.priceText {
            parts.append(item.discount.map { "\(price) (−\($0)%)" } ?? price)
        } else {
            parts.append("Free / no price listed")
        }
        if !item.windows { parts.append("no Windows version") }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder private func action(_ item: StoreItem) -> some View {
        if busy.contains(item.id) {
            ProgressView()
        } else if library.game(item.id) != nil {
            if isInstalled(item.id) {
                Label("Installed", systemImage: "checkmark.circle").labelStyle(.iconOnly).foregroundStyle(.green)
            } else if let dl = library.downloads[item.id] {
                switch dl.state {
                case .active, .queued: Text("Downloading").font(.caption).foregroundStyle(.secondary)
                case .paused, .failed: Button("Resume") { library.install(item.id) }.buttonStyle(.bordered)
                }
            } else {
                Button("Install") { library.install(item.id); notes[item.id] = "Downloading — see Your games." }
                    .buttonStyle(.borderedProminent)
            }
        } else if !item.windows {
            EmptyView()
        } else if item.priceText == nil {
            Button("Get") { Task { await getFree(item) } }.buttonStyle(.borderedProminent)
        } else {
            Button("Buy on Steam") {
                if let url = URL(string: "https://store.steampowered.com/app/\(item.id)/") { openURL(url) }
                notes[item.id] = "After buying, come back and tap refresh on the Steam page."
            }
            .buttonStyle(.bordered)
        }
    }

    private func isInstalled(_ appID: Int) -> Bool {
        dock.games.contains { $0.id == appID && $0.installed }
    }

    // MARK: Actions

    private func getFree(_ item: StoreItem) async {
        busy.insert(item.id)
        defer { busy.remove(item.id) }
        // The search lists unreleased and delisted games without a price too:
        // ask the store whether this one really is free before asking Steam.
        if let free = await StoreAPI.isFree(appID: item.id), !free {
            notes[item.id] = "This game is not free. Open it on the Steam store to buy it."
            return
        }
        switch await library.requestFreeLicense(item.id) {
        case .granted, .alreadyOwned:
            if library.game(item.id) != nil {
                library.install(item.id)
                notes[item.id] = "Added to your account. Downloading — see Your games."
            } else {
                notes[item.id] = "Added to your account. It will appear under Your games after a refresh."
            }
        case .refused(let reason):
            notes[item.id] = reason
        }
    }

    private func runSearch() {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return }
        searchTask?.cancel()
        searchTask = Task { await search(q) }
    }

    @MainActor private func search(_ q: String) async {
        searching = true
        defer { searching = false }
        do {
            let items = try await StoreAPI.search(q)
            guard !Task.isCancelled, q == query.trimmingCharacters(in: .whitespaces) else { return }
            results = items
            message = items.isEmpty ? "No games found for “\(q)”." : nil
        } catch {
            if !Task.isCancelled { message = "Search failed: \(error.localizedDescription)" }
        }
    }
}

/// Steam's public store endpoints (no account, no key).
enum StoreAPI {
    private static var region: (cc: String, lang: String) {
        let cc = Locale.current.region?.identifier ?? "US"
        let lang = Locale.preferredLanguages.first ?? "en"
        let steamLang: String
        if lang.hasPrefix("zh-Hant") || lang.hasPrefix("zh-TW") || lang.hasPrefix("zh-HK") { steamLang = "tchinese" }
        else if lang.hasPrefix("zh") { steamLang = "schinese" }
        else if lang.hasPrefix("ja") { steamLang = "japanese" }
        else if lang.hasPrefix("ko") { steamLang = "koreana" }
        else { steamLang = "english" }
        return (cc, steamLang)
    }

    private struct SearchResponse: Decodable {
        struct Item: Decodable {
            struct Price: Decodable { let currency: String?; let initial: Int?; let final: Int? }
            struct Platforms: Decodable { let windows: Bool? }
            let type: String?
            let name: String
            let id: Int
            let price: Price?
            let platforms: Platforms?
        }
        let items: [Item]
    }

    static func search(_ term: String) async throws -> [SteamStoreView.StoreItem] {
        var c = URLComponents(string: "https://store.steampowered.com/api/storesearch/")!
        c.queryItems = [URLQueryItem(name: "term", value: term),
                        URLQueryItem(name: "l", value: region.lang),
                        URLQueryItem(name: "cc", value: region.cc)]
        let (data, _) = try await URLSession.shared.data(from: c.url!)
        let response = try JSONDecoder().decode(SearchResponse.self, from: data)
        return response.items.filter { ($0.type ?? "app") == "app" }.map { item -> SteamStoreView.StoreItem in
            var priceText: String?
            var discount: Int?
            if let p = item.price, let final = p.final {
                priceText = format(cents: final, currency: p.currency)
                if let initial = p.initial, initial > final, initial > 0 {
                    discount = Int((Double(initial - final) / Double(initial) * 100).rounded())
                }
            }
            return .init(id: item.id, name: item.name, priceText: priceText, discount: discount,
                         windows: item.platforms?.windows ?? true)
        }
    }

    /// appdetails' `is_free`; nil when the store does not say.
    static func isFree(appID: Int) async -> Bool? {
        var c = URLComponents(string: "https://store.steampowered.com/api/appdetails")!
        c.queryItems = [URLQueryItem(name: "appids", value: String(appID)),
                        URLQueryItem(name: "filters", value: "basic"),
                        URLQueryItem(name: "cc", value: region.cc)]
        guard let url = c.url, let fetched = try? await URLSession.shared.data(from: url),
              let root = try? JSONSerialization.jsonObject(with: fetched.0) as? [String: Any],
              let entry = root[String(appID)] as? [String: Any],
              (entry["success"] as? Bool) == true,
              let details = entry["data"] as? [String: Any] else { return nil }
        return details["is_free"] as? Bool
    }

    private static func format(cents: Int, currency: String?) -> String {
        let f = NumberFormatter()
        f.numberStyle = .currency
        if let currency { f.currencyCode = currency }
        let amount = Double(cents) / 100
        if amount == amount.rounded() { f.maximumFractionDigits = 0 }
        return f.string(from: NSNumber(value: amount)) ?? String(format: "%.2f", amount)
    }
}
