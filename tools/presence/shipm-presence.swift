// shipm-presence: asks the person at this Mac to prove they are there, once. Used by the escalating `shipm autopilot ...` commands (docs/plans/2026-10-21-owner-proof-design.md).
// A program cannot touch the sensor or type into the system password dialog, so a "yes" from here means a human was present.
//   shipm-presence --reason "text shown in the system dialog" [--policy strong|owner] [--timeout SECONDS]
//   shipm-presence --probe          (no dialog) prints the policies this Mac can evaluate now: "strong", "owner", both, or "none"
// Policies: strong = Touch ID (or Apple Watch / Touch ID keyboard), no password button; owner = Touch ID or Watch if usable, else the Mac password in the system dialog.
// Prints ONE line on stdout and exits: ok (0) | refused (1: cancelled, failed, timed out) | unavailable (2: the policy cannot be evaluated now) | usage (3). No network, no files.
import Foundation
import LocalAuthentication

func finish(_ word: String, _ code: Int32) -> Never {
    print(word)
    exit(code)
}

func strongPolicy() -> LAPolicy {
    if #available(macOS 15.0, *) { return .deviceOwnerAuthenticationWithBiometricsOrCompanion }
    if #available(macOS 10.15, *) { return .deviceOwnerAuthenticationWithBiometricsOrWatch }
    return .deviceOwnerAuthenticationWithBiometrics
}

var reason = ""
var timeout: Double = 60
var policyName = "strong"
var probe = false
var args = Array(CommandLine.arguments.dropFirst())
while !args.isEmpty {
    let a = args.removeFirst()
    if a == "--reason", !args.isEmpty {
        reason = args.removeFirst()
    } else if a == "--policy", !args.isEmpty {
        policyName = args.removeFirst()
        if policyName != "strong" && policyName != "owner" { finish("usage", 3) }
    } else if a == "--timeout", !args.isEmpty, let t = Double(args.removeFirst()), t >= 1, t <= 120 {
        timeout = t
    } else if a == "--probe" {
        probe = true
    } else {
        finish("usage", 3)
    }
}

if probe {
    var words: [String] = []
    var e1: NSError?
    if LAContext().canEvaluatePolicy(strongPolicy(), error: &e1) { words.append("strong") }
    var e2: NSError?
    if LAContext().canEvaluatePolicy(.deviceOwnerAuthentication, error: &e2) { words.append("owner") }
    finish(words.isEmpty ? "none" : words.joined(separator: " "), 0)
}

if reason.isEmpty { finish("usage", 3) }
if reason.count > 200 { reason = String(reason.prefix(199)) + "…" }

let policy: LAPolicy = policyName == "strong" ? strongPolicy() : .deviceOwnerAuthentication
let context = LAContext()
if policyName == "strong" { context.localizedFallbackTitle = "" }      // no "Enter Password" button on the strong policy
var error: NSError?
if !context.canEvaluatePolicy(policy, error: &error) {
    finish("unavailable", 2)
}
let sem = DispatchSemaphore(value: 0)
var result: Int32 = 1
context.evaluatePolicy(policy, localizedReason: reason) { ok, _ in
    result = ok ? 0 : 1
    sem.signal()
}
if sem.wait(timeout: .now() + timeout) == .timedOut {
    context.invalidate()
    finish("refused", 1)
}
finish(result == 0 ? "ok" : "refused", result)
