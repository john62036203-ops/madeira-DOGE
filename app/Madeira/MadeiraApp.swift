import Foundation
import SwiftUI

@main
struct MadeiraApp: App {
    init() {
        // madeira-bcd: the Metal Performance HUD's performance insights (the
        // notes that stack up left of its panel: shader compiles, similar render
        // passes, blit encoders) cover the game. Off unless madeira.cfg says
        // env.MTL_HUD_INSIGHTS_ENABLED = 1, which is exported later and wins.
        setenv("MTL_HUD_INSIGHTS_ENABLED", "0", 0)
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .modifier(ClaimGamepadEvents())
                .onAppear { GamepadInput.shared.start() }
                // madeira-bcd: madeira://play?exe=... (Home Screen shortcuts)
                .onOpenURL { ShortcutRouter.shared.handle($0) }
        }
    }
}
