// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import SwiftUI

/// madeira-doge: the Deals tab -- Steam's current specials as cards.
///
/// The list is Steam's public store search with `specials=1` (no sign-in), the
/// same request the store's own "Specials" page pages through while scrolling:
/// it answers JSON whose `results_html` holds one row per game. A row gives the
/// app id, the name, the discount and both prices, already formatted for the
/// region asked for. The next page is fetched when the last cards come on
/// screen. If the first page cannot be read that way, the store's
/// `featuredcategories` JSON supplies its (shorter) specials list instead.
/// A card opens the game's store page; nothing here buys or downloads.
struct SteamDeal: Identifiable, Hashable {
    let id: Int
    let name: String
    let discount: Int            // percent, 1...100
    let finalPrice: String
    let originalPrice: String?

    var storeURL: URL { URL(string: "https://store.steampowered.com/app/\(id)/")! }
    var portraitArt: URL { URL(string: "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/\(id)/library_600x900.jpg")! }
    var headerArt: URL { URL(string: "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/\(id)/header.jpg")! }
}

@MainActor
final class SteamDealsModel: ObservableObject {
    static let shared = SteamDealsModel()

    @Published private(set) var deals: [SteamDeal] = []
    @Published private(set) var loading = false
    @Published private(set) var finished = false
    @Published private(set) var message: String?

    private var nextStart = 0
    private var seen = Set<Int>()
    private var fallbackUsed = false
    private static let pageSize = 50

    static var countryCode: String { Locale.current.region?.identifier ?? "US" }
    static var language: String {
        let preferred = Locale.preferredLanguages.first?.lowercased() ?? "en"
        if preferred.hasPrefix("zh-hant") || preferred.hasPrefix("zh-tw") || preferred.hasPrefix("zh-hk") { return "tchinese" }
        if preferred.hasPrefix("zh") { return "schinese" }
        if preferred.hasPrefix("ja") { return "japanese" }
        if preferred.hasPrefix("ko") { return "koreana" }
        return "english"
    }

    func loadFirstIfNeeded() {
        if deals.isEmpty && !loading { reload() }
    }

    func reload() {
        deals = []; seen = []; nextStart = 0; finished = false; fallbackUsed = false; message = nil
        loadMore()
    }

    func loadMore() {
        guard !loading, !finished else { return }
        loading = true
        let start = nextStart
        Task {
            let page = await Self.fetchPage(start: start, count: Self.pageSize)
            var added = page.deals.filter { seen.insert($0.id).inserted }
            if page.failed && start == 0 && !fallbackUsed {
                // The search page could not be read: the store's own short specials list.
                fallbackUsed = true
                added = (await Self.fetchFeatured()).filter { seen.insert($0.id).inserted }
                finished = true
                if added.isEmpty { message = "Couldn't load Steam's specials. Pull down to try again." }
            } else if page.failed {
                message = deals.isEmpty ? "Couldn't load Steam's specials. Pull down to try again." : nil
                finished = deals.isEmpty
            } else {
                nextStart = start + Self.pageSize
                if page.rows == 0 || (page.total > 0 && nextStart >= page.total) { finished = true }
            }
            deals.append(contentsOf: added)
            loading = false
            LogStore.shared.log("[steam-deals] start=\(start) added=\(added.count) total=\(deals.count) rows=\(page.rows) failed=\(page.failed ? 1 : 0) fallback=\(fallbackUsed ? 1 : 0) cc=\(Self.countryCode)")
            // A page of rows that were all bundles or repeats: keep going.
            if added.isEmpty && !finished && !page.failed { loadMore() }
        }
    }

    struct Page { var deals: [SteamDeal] = []; var rows = 0; var total = 0; var failed = false }

    nonisolated static func request(_ url: URL) -> URLRequest {
        var r = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 20)
        r.setValue("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1", forHTTPHeaderField: "User-Agent")
        return r
    }

    nonisolated static func fetchPage(start: Int, count: Int) async -> Page {
        var c = URLComponents(string: "https://store.steampowered.com/search/results/")!
        let cc = await MainActor.run { countryCode }
        let lang = await MainActor.run { language }
        c.queryItems = [
            URLQueryItem(name: "query", value: ""),
            URLQueryItem(name: "start", value: String(start)),
            URLQueryItem(name: "count", value: String(count)),
            URLQueryItem(name: "specials", value: "1"),
            URLQueryItem(name: "category1", value: "998"),     // games
            URLQueryItem(name: "infinite", value: "1"),
            URLQueryItem(name: "cc", value: cc),
            URLQueryItem(name: "l", value: lang),
        ]
        guard let url = c.url,
              let (data, _) = try? await URLSession.shared.data(for: request(url)),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let html = json["results_html"] as? String else {
            return Page(failed: true)
        }
        var page = Page()
        page.total = (json["total_count"] as? Int) ?? 0
        // One <a ...> ... </a> per result.
        let rows = html.components(separatedBy: "<a href=").dropFirst()
        page.rows = rows.count
        for row in rows {
            guard let idText = first(#"data-ds-appid="(\d+)""#, in: row), let id = Int(idText),
                  let name = first(#"<span class="title">(.*?)</span>"#, in: row),
                  let pctText = first(#"data-discount="(\d+)""#, in: row) ?? first(#"discount_pct">\s*-?(\d+)%"#, in: row),
                  let pct = Int(pctText), pct > 0,
                  let final = first(#"discount_final_price[^>]*>(.*?)</div>"#, in: row) else { continue }
            let original = first(#"discount_original_price[^>]*>(.*?)</div>"#, in: row)
            page.deals.append(SteamDeal(id: id, name: plain(name), discount: pct,
                                        finalPrice: plain(final), originalPrice: original.map(plain)))
        }
        // Rows present but none readable: the markup changed; let the caller fall back.
        if page.rows > 0 && page.deals.isEmpty && start == 0 { page.failed = true }
        return page
    }

    nonisolated static func fetchFeatured() async -> [SteamDeal] {
        var c = URLComponents(string: "https://store.steampowered.com/api/featuredcategories/")!
        let cc = await MainActor.run { countryCode }
        let lang = await MainActor.run { language }
        c.queryItems = [URLQueryItem(name: "cc", value: cc), URLQueryItem(name: "l", value: lang)]
        guard let url = c.url,
              let (data, _) = try? await URLSession.shared.data(for: request(url)),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let specials = json["specials"] as? [String: Any],
              let items = specials["items"] as? [[String: Any]] else { return [] }
        var out: [SteamDeal] = []
        for item in items {
            guard let id = item["id"] as? Int, let name = item["name"] as? String,
                  let pct = item["discount_percent"] as? Int, pct > 0,
                  let final = item["final_price"] as? Int else { continue }
            let code = (item["currency"] as? String) ?? "USD"
            let original = item["original_price"] as? Int
            out.append(SteamDeal(id: id, name: name, discount: pct,
                                 finalPrice: money(final, code), originalPrice: original.map { money($0, code) }))
        }
        return out
    }

    nonisolated static func money(_ hundredths: Int, _ code: String) -> String {
        let f = NumberFormatter()
        f.numberStyle = .currency
        f.currencyCode = code
        return f.string(from: NSNumber(value: Double(hundredths) / 100)) ?? "\(Double(hundredths) / 100) \(code)"
    }

    nonisolated static func first(_ pattern: String, in text: String) -> String? {
        guard let re = try? NSRegularExpression(pattern: pattern, options: [.dotMatchesLineSeparators]) else { return nil }
        let range = NSRange(text.startIndex..., in: text)
        guard let m = re.firstMatch(in: text, range: range), m.numberOfRanges > 1,
              let r = Range(m.range(at: 1), in: text) else { return nil }
        return String(text[r])
    }

    /// Text of an HTML fragment: tags dropped, the few entities Steam uses decoded.
    nonisolated static func plain(_ html: String) -> String {
        var s = html.replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
        for (entity, value) in [("&amp;", "&"), ("&quot;", "\""), ("&#39;", "'"), ("&lt;", "<"), ("&gt;", ">"),
                                ("&nbsp;", " "), ("&trade;", "\u{2122}"), ("&reg;", "\u{00AE}")] {
            s = s.replacingOccurrences(of: entity, with: value)
        }
        return s.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

struct SteamDealsView: View {
    /// The tab's search text: filters the loaded cards by name.
    var search: String
    @ObservedObject private var model = SteamDealsModel.shared
    @Environment(\.openURL) private var openURL

    private var shown: [SteamDeal] {
        let q = search.trimmingCharacters(in: .whitespaces)
        return q.isEmpty ? model.deals : model.deals.filter { $0.name.localizedCaseInsensitiveContains(q) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Steam specials").font(.title2.bold())
                if let message = model.message {
                    Text(message).foregroundStyle(.secondary)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 20, alignment: .top)], spacing: 24) {
                    ForEach(shown) { deal in
                        Button { openURL(deal.storeURL) } label: { SteamDealCard(deal: deal) }
                            .buttonStyle(.plain)
                            .onAppear { if deal.id == model.deals.last?.id { model.loadMore() } }
                    }
                }
                if model.loading {
                    HStack { Spacer(); ProgressView(); Spacer() }.padding(.vertical, 12)
                } else if model.finished && !model.deals.isEmpty {
                    Text("That's every special Steam lists right now.")
                        .font(.footnote).foregroundStyle(.secondary).frame(maxWidth: .infinity).padding(.vertical, 12)
                } else if !model.deals.isEmpty {
                    // The filtered grid may be too short to bring the last card on screen.
                    Color.clear.frame(height: 1).onAppear { model.loadMore() }
                }
            }
            .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 110)
        }
        .background(Color(uiColor: .systemGroupedBackground).ignoresSafeArea())
        .refreshable { model.reload() }
        .onAppear { model.loadFirstIfNeeded() }
    }
}

struct SteamDealCard: View {
    let deal: SteamDeal

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Color.black.opacity(0.25)
                .aspectRatio(2.0 / 3.0, contentMode: .fit)
                .overlay {
                    AsyncImage(url: deal.portraitArt) { phase in
                        if let image = phase.image {
                            image.resizable().scaledToFill()
                        } else if phase.error != nil {
                            // No portrait art on the CDN: the wide header, centred.
                            AsyncImage(url: deal.headerArt) { header in
                                if let image = header.image { image.resizable().scaledToFit() }
                                else { Image(systemName: "gamecontroller.fill").font(.largeTitle).foregroundStyle(.secondary) }
                            }
                        } else {
                            ProgressView()
                        }
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            Text(deal.name).font(.headline).lineLimit(2).multilineTextAlignment(.leading)
            HStack(spacing: 8) {
                Text("-\(deal.discount)%")
                    .font(.subheadline.weight(.bold)).foregroundStyle(.black)
                    .padding(.horizontal, 7).padding(.vertical, 3)
                    .background(Color(red: 0.64, green: 0.81, blue: 0.20), in: RoundedRectangle(cornerRadius: 6))
                VStack(alignment: .leading, spacing: 0) {
                    if let original = deal.originalPrice {
                        Text(original).font(.caption2).strikethrough().foregroundStyle(.secondary)
                    }
                    Text(deal.finalPrice).font(.subheadline.weight(.semibold))
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
    }
}
