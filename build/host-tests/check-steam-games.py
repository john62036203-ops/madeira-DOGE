#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 125hz
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Installed Steam games in the library (app/Madeira/SteamGames.swift), on the host.

1. Swift: compiles the production SteamGamesRules with Madeira Dock's production
   discovery (MadeiraDock.games / game(manifest:), sliced as in
   check-dock-contract.py, and SteamKeyValues.swift) and checks, on a synthetic
   drive_c laid out as Steam's client writes it, that installed and partly
   installed games are found, plus the section, search, Play-blocker and
   artwork rules.
2. Source checks: the section uses Dock's discovery and Dock's launch path
   only (no environment, sign-in transfer, token or Wine call of its own), no
   program-name list, no account data in a log line, wired into the library,
   built by the Xcode project.

Synthetic data only: no Steam, Wine or credentials.
"""
from pathlib import Path
import os, re, shutil, subprocess, sys, tempfile

root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
SWIFTC = os.environ.get('SWIFTC') or shutil.which('swiftc') or str(Path.home() / '.local/share/swiftly/bin/swiftc')
failures = 0


def require(condition, label):
    global failures
    print(('PASS: ' if condition else 'FAIL: ') + label)
    if not condition:
        failures += 1


games = (app / 'SteamGames.swift').read_text()
dock = (app / 'MadeiraDock.swift').read_text()
library = (app / 'Library.swift').read_text()
project = (root / 'app/Madeira.xcodeproj/project.pbxproj').read_text()
rules = games[games.index('// MARK: - Rules'):games.index('// MARK: - Model')]

# ------------------------------------------------------------------ static
require(games.startswith('// SPDX-License-Identifier: GPL-3.0-or-later\n// Copyright 2026 125hz\n'
                         '// Madeira Converter Exception: see LICENSE-EXCEPTION.md\n'),
        'SteamGames.swift: GPL-3.0-or-later, Copyright 2026 125hz, Converter Exception')
require('/* SteamGames.swift in Sources */,' in project and 'path = "SteamGames.swift"' in project,
        'SteamGames.swift is built by the Xcode project')
require('SteamGamesSection(search: search, startDock: startDock)' in library, 'Library: the Steam section is in the library')
require('MadeiraDock.games(drive: drive)' in games and 'let drive = MadeiraDock.drive' in games,
        "the section lists exactly what Dock's own discovery finds")
require('startDock(game, dock.compactPool)' in games and games.count('startDock(') == 1,
        "Play goes through Dock's launch path, with Dock's per-launch pool toggle")
for forbidden in ['setenv(', 'unsetenv(', 'runWineFullSequence', 'writeHandoff', 'credentialsForDock', 'SteamTokenStore',
                  'refreshToken', 'SecItem', 'MADEIRA_EXE', 'MADEIRA_ARGS', 'jit_', 'JITPool', 'poolSize',
                  'steamwebhelper', 'steam.exe', 'SteamSetup', 'FEX_', 'DXMT']:
    require(forbidden not in games, f'SteamGames.swift: no {forbidden}')
require(not re.findall(r'"[^"\n]*\.exe"', games), 'SteamGames.swift: no program names')
for line in games.splitlines():
    if re.search(r'LogStore|SteamLog\.|print\(|NSLog|fputs', line):
        require(re.search(r'\\\((game\.name|name|account|token|signIn|path|folder|status|error)', line) is None,
                f'no account data, name or path in "{line.strip()[:70]}"')
require(re.search(r'\bView\b|SwiftUI', rules.replace('// MARK: - Rules', '')) is None, 'the rules are Foundation-only')
detail = games[games.index('struct SteamGameDetail: View'):]
require('MadeiraDock.requestLaunchOption(option, appID: game.id)\n                                    startDock(game, dock.compactPool)' in detail,
        'Play hands the chosen launch option to Dock right before its start')
require('SteamAppInfo.launchOptions(appID: appID, cache: cache)' in detail and 'Task.detached' in detail,
        "launch options come from Valve's app info cache, read off the main thread")
require("ForEach(launchOptions)" in detail and 'SteamGamesRules.showsLaunchOptions(launchOptions)' in detail,
        'the sheet offers the launch choice')

# ------------------------------------------------------------------ compiled
head = dock[dock.index('enum DockPerformancePolicy {'):dock.index('enum MadeiraDock {')]
body = (dock[dock.index('enum MadeiraDock {'):dock.index('    @MainActor private static var lastReport =')] +
        dock[dock.index("    /// The host's environment for one launch."):])
stubs = r'''
import Foundation
import Glibc
enum SteamSignIn {
    static func flag(_ name: String, default fallback: Bool) -> Bool { getenv(name).map { String(cString: $0) != "0" } ?? fallback }
}
enum SteamLog { static func event(_ m: String) {}; static func trace(_ m: @autoclosure () -> String) {} }
enum SteamRuntimeFiles {
    static let relativeRoot = "Program Files (x86)/Steam"
    static let windowsRoot = "C:\\Program Files (x86)\\Steam"
}
'''
checks = r'''
import Foundation
import Glibc
var failures = 0
func require(_ condition: @autoclosure () -> Bool, _ label: String) {
    if condition() { print("PASS: " + label) } else { print("FAIL: " + label); failures += 1 }
}
func write(_ url: URL, _ text: String) throws {
    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    try Data(text.utf8).write(to: url)
}
func record(_ appID: Int, _ name: String, _ folder: String, flags: Int) -> String {
    "\"AppState\"\n{\n\t\"appid\"\t\t\"\(appID)\"\n\t\"Universe\"\t\t\"1\"\n\t\"name\"\t\t\"\(name)\"\n\t\"StateFlags\"\t\t\"\(flags)\"\n" +
    "\t\"installdir\"\t\t\"\(folder)\"\n\t\"buildid\"\t\t\"100\"\n}\n"
}

// A synthetic appinfo.vdf as Valve's client writes it (binary KeyValues;
// version 29 names keys through a string table at the end of the file).
func le32(_ value: UInt32) -> [UInt8] { (0..<4).map { UInt8((value >> UInt32(8 * $0)) & 0xff) } }
func cstr(_ text: String) -> [UInt8] { Array(text.utf8) + [0] }
final class Keys {
    var table: [String]?
    init(indexed: Bool) { table = indexed ? [] : nil }
    func key(_ name: String) -> [UInt8] {
        guard var list = table else { return cstr(name) }
        if let index = list.firstIndex(of: name) { return le32(UInt32(index)) }
        list.append(name); table = list
        return le32(UInt32(list.count - 1))
    }
}
indirect enum KV { case text(String, String), int(String, UInt32), table(String, [KV]) }
func encode(_ items: [KV], _ keys: Keys) -> [UInt8] {
    var out: [UInt8] = []
    for item in items {
        switch item {
        case .text(let name, let value): out += [UInt8(1)] + keys.key(name) + cstr(value)
        case .int(let name, let value): out += [UInt8(2)] + keys.key(name) + le32(value)
        case .table(let name, let children): out += [UInt8(0)] + keys.key(name) + encode(children, keys)
        }
    }
    return out + [UInt8(8)]
}
func appinfo(version: UInt8, apps: [(UInt32, [KV])]) -> Data {
    let keys = Keys(indexed: version >= 0x29)
    var body: [UInt8] = []
    for (id, items) in apps {
        var entry = le32(2) + le32(1_700_000_000) + [UInt8](repeating: 0, count: 8) + [UInt8](repeating: 0xaa, count: 20) + le32(7)
        if version >= 0x28 { entry += [UInt8](repeating: 0xbb, count: 20) }
        entry += encode([.table("appinfo", items)], keys)
        body += le32(id) + le32(UInt32(entry.count)) + entry
    }
    body += le32(0)
    var header: [UInt8] = [version, 0x44, 0x56, 0x07] + le32(1)
    guard let table = keys.table else { return Data(header + body) }
    let offset = UInt32(header.count + 8 + body.count)
    header += le32(offset) + le32(0)
    var strings = le32(UInt32(table.count))
    for name in table { strings += cstr(name) }
    return Data(header + body + strings)
}
func launchEntry(_ key: String, _ items: [KV]) -> KV { .table(key, items) }
let fixtureLaunch: [KV] = [
    .int("appid", 4242),
    .table("common", [.text("name", "Fixture Game"), .text("type", "game")]),
    .table("config", [
        .text("installdir", "Fixture Game"),
        .table("launch", [
            launchEntry("0", [.text("executable", "game.bin"), .text("description", "Play"), .table("config", [.text("oslist", "windows")])]),
            launchEntry("1", [.text("executable", "x.bin"), .text("description", "Play the expansion"), .text("type", "option1"),
                              .table("config", [.text("oslist", "linux,windows"), .text("ownsdlc", "5001, 5002")])]),
            launchEntry("2", [.text("executable", "m.bin"), .text("description", "Other system"), .table("config", [.text("oslist", "macos")])]),
            launchEntry("3", [.text("executable", "b.bin"), .text("description", "Beta"), .table("config", [.text("BetaKey", "public_beta")])]),
            launchEntry("4", [.text("executable", "e.bin"), .table("description_loc", [.text("english", "Editor")])]),
            launchEntry("5", [.text("executable", "n.bin")]),
            launchEntry("9999", [.text("executable", "big.bin"), .text("description", "Out of range")]),
        ]),
    ]),
]
let otherApp: [KV] = [.int("appid", 77), .table("config", [.table("launch", [launchEntry("0", [.text("description", "Other app")])])])]

@main struct Checks {
    static func main() throws {
        typealias R = SteamGamesRules
        let fm = FileManager.default
        let drive = fm.temporaryDirectory.appendingPathComponent("madeira-steam-games-" + UUID().uuidString)
        defer { try? fm.removeItem(at: drive) }
        // Madeira's Steam library, as Steam's client lays it out.
        let apps = drive.appendingPathComponent("Program Files (x86)/Steam/steamapps")
        try write(apps.appendingPathComponent("appmanifest_4242.acf"), record(4242, "Fixture Game", "Fixture Game", flags: 4))
        try fm.createDirectory(at: apps.appendingPathComponent("common/Fixture Game"), withIntermediateDirectories: true)
        try write(apps.appendingPathComponent("appmanifest_4343.acf"), record(4343, "Second Fixture", "Second", flags: 1026))
        try write(apps.appendingPathComponent("appmanifest_bad.acf"), "not a record")
        try write(apps.appendingPathComponent("appmanifest_4444.acf"), record(4444, "Escape", "../x", flags: 4))

        let found = MadeiraDock.games(drive: drive)
        require(found.map(\.id) == [4242, 4343], "Dock's discovery finds the valid records, sorted by name: \(found.map(\.id))")
        let first = found.first { $0.id == 4242 }
        require(first?.installed == true && first?.installDir == "Fixture Game" && first?.library == "Program Files (x86)/Steam/steamapps",
                "a fully installed game (StateFlags 4) in Madeira's Steam library")
        require(found.first { $0.id == 4343 }?.installed == false, "an update in progress is not offered for Play")
        require(first?.windowsInstallPath == "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Fixture Game", "Windows install path")

        require(R.showsSection(dock: true, count: 2), "section shown with Dock and games")
        require(!R.showsSection(dock: false, count: 2), "no section without Dock (MADEIRA_DOCK=0 or no host)")
        require(!R.showsSection(dock: true, count: 0), "no empty section")
        require(R.matching(found, search: "").count == 2 && R.matching(found, search: "  ").count == 2, "empty search shows all")
        require(R.matching(found, search: "second").map(\.id) == [4343], "search is case-insensitive on the name")
        require(R.matching(found, search: "nothing").isEmpty, "search without a match")

        require(R.blocker(installed: true, client: true, signedIn: true) == nil, "Play offered when installed, client ready, signed in")
        require(R.blocker(installed: false, client: true, signedIn: true)?.contains("fully installed") == true, "not installed first")
        require(R.blocker(installed: true, client: false, signedIn: true)?.contains("client components") == true, "client components next")
        require(R.blocker(installed: true, client: true, signedIn: false)?.contains("Sign in") == true, "sign-in last")

        let cover = R.cover(4242)
        require(cover?.scheme == "https" && cover?.host == "cdn.cloudflare.steamstatic.com" && cover?.path.contains("/4242/") == true,
                "artwork from Steam's public store CDN by App ID")
        require(R.cover(0) == nil, "no artwork URL for an invalid App ID")
        // Launch options from Valve's app info cache.
        for version: UInt8 in [0x27, 0x28, 0x29] {
            let data = appinfo(version: version, apps: [(77, otherApp), (4242, fixtureLaunch)])
            let options = SteamAppInfo.app(4242, in: data).map { SteamAppInfo.launchOptions($0) } ?? []
            require(options.map(\.id) == [0, 1, 4, 5], "v\(String(version, radix: 16)): Windows entries in key order, other systems, betas and out-of-range keys left out: \(options.map(\.id))")
            require(options.first { $0.id == 1 }?.dlc == [5001, 5002] && options.first { $0.id == 0 }?.dlc == [],
                    "v\(String(version, radix: 16)): a DLC entry lists the DLC it needs")
            require(options.first { $0.id == 4 }?.title == "Editor" && options.first { $0.id == 5 }?.title == "Launch option 5",
                    "v\(String(version, radix: 16)): localized description, else a numbered title")
            require(SteamAppInfo.app(77, in: data).map { SteamAppInfo.launchOptions($0) }?.map(\.title) == ["Other app"], "v\(String(version, radix: 16)): each app is read on its own")
            require(SteamAppInfo.app(4343, in: data) == nil, "v\(String(version, radix: 16)): an app the cache does not list has no entry")
            for cut in [12, data.count / 2, data.count - 3] {
                _ = SteamAppInfo.app(4242, in: data.prefix(cut))
            }
        }
        let v28 = appinfo(version: 0x28, apps: [(4242, fixtureLaunch)])
        require(SteamAppInfo.app(4242, in: v28.prefix(v28.count - 10)) == nil, "a truncated cache is not read")
        var foreign = v28; foreign[0] = 0x30
        require(SteamAppInfo.app(4242, in: foreign) == nil, "an unknown cache version is not read")
        require(SteamAppInfo.app(0, in: v28) == nil && SteamAppInfo.app(-1, in: v28) == nil, "invalid App IDs are refused")
        let cache = R.appInfoCache(drive: drive)
        require(cache.path.hasSuffix("/Program Files (x86)/Steam/appcache/appinfo.vdf"), "the client's own app info cache in the prefix")
        require(SteamAppInfo.launchOptions(appID: 4242, cache: cache).isEmpty, "no cache yet: no choice")
        try fm.createDirectory(at: cache.deletingLastPathComponent(), withIntermediateDirectories: true)
        try appinfo(version: 0x29, apps: [(4242, fixtureLaunch)]).write(to: cache)
        let options = SteamAppInfo.launchOptions(appID: 4242, cache: cache)
        require(options.count == 4, "launch options read from the cache file")
        require(R.showsLaunchOptions(options) && !R.showsLaunchOptions(Array(options.prefix(1))) && !R.showsLaunchOptions([]),
                "the choice is offered only with more than one entry")
        require(R.defaultLaunchOption(options) == 0 && R.defaultLaunchOption(Array(options.dropFirst())) == 1 &&
                R.defaultLaunchOption(Array(options.suffix(1))) == 0 && R.defaultLaunchOption([]) == 0,
                "Steam's first entry by default; the first offered entry when 0 is not offered; 0 when nothing is offered")
        require(R.title(options[1]) == "Play the expansion (DLC)" && R.title(options[0]) == "Play", "DLC entries say so")

        if failures > 0 { print("FAILURES: \(failures)"); exit(1) }
        print("PASS: all Steam games Swift checks")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='madeira-steam-games-') as tmp:
    tmp = Path(tmp)
    (tmp / 'stubs.swift').write_text(stubs + head)
    (tmp / 'dock.swift').write_text('import Foundation\nimport Glibc\n' + body)
    (tmp / 'rules.swift').write_text('import Foundation\n' + rules)
    (tmp / 'checks.swift').write_text(checks)
    exe = tmp / 'check'
    build = subprocess.run([SWIFTC, '-parse-as-library', '-swift-version', '5', '-sanitize=address', '-o', str(exe),
                            str(tmp / 'stubs.swift'), str(tmp / 'dock.swift'), str(tmp / 'rules.swift'),
                            str(tmp / 'checks.swift'), str(app / 'SteamKeyValues.swift')], capture_output=True, text=True)
    require(build.returncode == 0, 'production Steam games rules and Dock discovery compile on the host')
    if build.returncode:
        sys.stdout.write(build.stderr[-4000:])
    else:
        run = subprocess.run([str(exe)], env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'), capture_output=True, text=True)
        sys.stdout.write(run.stdout)
        if run.returncode:
            sys.stdout.write(run.stderr[-4000:])
        require(run.returncode == 0, 'Steam games checks pass under AddressSanitizer')

if failures:
    print(f'check-steam-games: {failures} FAILED')
    sys.exit(1)
print('check-steam-games: PASS')
