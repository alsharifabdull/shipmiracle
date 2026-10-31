## Stack rules — iOS (Swift / SwiftUI)
- Xcode project or Swift package; iOS deployment target as set in the project. SwiftUI first.
- Money as `Decimal`, never `Double`. Dates through `Calendar`, never string math.
- All user-facing strings in a String Catalog; respect the project's language and RTL rules.
- Accessibility: Dynamic Type, VoiceOver labels on icon-only controls, 44 pt targets.
- Use the Apple HIG and swiftui-pro skills in `.agents/skills` when designing or reviewing UI.
- Tests: `swift test` for packages, `xcodebuild test -scheme <Scheme> -destination 'platform=iOS Simulator,name=iPhone 17'` for the app. Run in the iOS Simulator panel for visual checks.
- No CI on GitHub runners (macOS minutes cost money); the Stop hook runs the tests locally.
- Secrets: Keychain only; file protection complete for local data.
