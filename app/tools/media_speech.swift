// media_speech: words from a voice note or other audio file, recognised on this Mac. No network, no download.
//
// A file with no top-level code, so two things can compile it: the engine's command-line tool (media.swift, built by
// ctx/media.py) and the app target, should the app ever need to run transcription itself. Both get the same answer
// shape: a dictionary that becomes one json line.
//
//   MediaSpeech.info()                      what this Mac can do: {"modern": bool, "installed": [locales], "permission": "...",
//                                           "on_device": {locale: bool}}
//   MediaSpeech.transcribe(path, locale)    {"ok": true, "text": ..., "secs": ..., "conf": 0..1, "locale": ..., "engine": ...}
//                                           or {"ok": false, "why": ...}
//
// Two engines:
//   macOS 26 and later: SpeechAnalyzer with SpeechTranscriber. It reads a file with the models already installed and
//     asks for no permission, so a command-line tool can run it. It never downloads a model: a locale that is not
//     installed is refused with "not installed".
//   before macOS 26: SFSpeechRecognizer with requiresOnDeviceRecognition. It needs the speech recognition permission,
//     which only an app with a usage string can ask for. This file never asks: without the permission it answers
//     {"ok": false, "why": "needs permission"} and the app is the one to ask.
import AVFoundation
import Foundation
import Speech

enum MediaSpeech {
    /// The mac's own language as speech wants it ("en-GB"), or en-US when it will not say.
    static var systemLocale: String {
        let id = Locale.current.identifier.split(separator: "@").first.map(String.init) ?? ""
        let parts = id.replacingOccurrences(of: "_", with: "-").split(separator: "-")
        guard parts.count >= 2, let lang = parts.first, let region = parts.last, region.count == 2 else { return "en-US" }
        return lang.lowercased() + "-" + region.uppercased()
    }
    /// The locales `info` reports on: this mac's own, then en-US.
    static var wanted: [String] {
        var out = [systemLocale]
        for id in ["en-US"] where !out.contains(id) { out.append(id) }
        return out
    }

    static func permission() -> String {
        switch SFSpeechRecognizer.authorizationStatus() {       // reading the status never raises a prompt
        case .authorized: return "granted"
        case .denied: return "denied"
        case .restricted: return "restricted"
        default: return "not asked"
        }
    }

    /// Run an async job from a plain command-line main and wait for it.
    static func wait<T>(_ job: @escaping @Sendable () async -> T) -> T where T: Sendable {
        let sem = DispatchSemaphore(value: 0)
        let box = Box<T>()
        Task.detached {
            box.value = await job()
            sem.signal()
        }
        sem.wait()
        return box.value!
    }

    final class Box<T>: @unchecked Sendable { var value: T? }

    static func info() -> [String: Any] {
        var out: [String: Any] = ["permission": permission(), "modern": false, "installed": [String]()]
        var onDevice: [String: Bool] = [:]
        for id in wanted {
            onDevice[id] = SFSpeechRecognizer(locale: Locale(identifier: id))?.supportsOnDeviceRecognition ?? false
        }
        out["on_device"] = onDevice
        #if compiler(>=6.2)
        if #available(macOS 26.0, *) {
            out["modern"] = true
            out["installed"] = wait { await SpeechTranscriber.installedLocales.map { $0.identifier(.bcp47) }.sorted() }
        }
        #endif
        return out
    }

    static func seconds(_ url: URL) -> Double {
        guard let f = try? AVAudioFile(forReading: url), f.fileFormat.sampleRate > 0 else { return 0 }
        return Double(f.length) / f.fileFormat.sampleRate
    }

    static func transcribe(_ path: String, locale: String) -> [String: Any] {
        let url = URL(fileURLWithPath: path)
        let secs = seconds(url)
        #if compiler(>=6.2)
        if #available(macOS 26.0, *) {
            let r: [String: String] = wait { await modern(url, locale) }
            return finish(r, secs: secs, locale: locale, engine: "transcriber")
        }
        #endif
        return finish(classic(url, locale), secs: secs, locale: locale, engine: "recognizer")
    }

    static func finish(_ r: [String: String], secs: Double, locale: String, engine: String) -> [String: Any] {
        if let why = r["why"] { return ["ok": false, "why": why, "secs": secs] }
        return ["ok": true, "text": r["text"] ?? "", "secs": secs, "conf": Double(r["conf"] ?? "") ?? 0, "locale": locale, "engine": engine]
    }

    #if compiler(>=6.2)
    @available(macOS 26.0, *)
    static func modern(_ url: URL, _ localeId: String) async -> [String: String] {
        let installed = await SpeechTranscriber.installedLocales.map { $0.identifier(.bcp47) }
        guard installed.contains(localeId) else { return ["why": "not installed"] }
        do {
            let transcriber = SpeechTranscriber(locale: Locale(identifier: localeId), transcriptionOptions: [], reportingOptions: [],
                                                attributeOptions: [.transcriptionConfidence])
            let analyzer = SpeechAnalyzer(modules: [transcriber])
            let file = try AVAudioFile(forReading: url)
            async let collected: (String, Double, Int) = {
                var text = "", sum = 0.0, n = 0
                for try await r in transcriber.results {
                    text += String(r.text.characters)
                    for run in r.text.runs {
                        if let c = run.transcriptionConfidence {
                            sum += c
                            n += 1
                        }
                    }
                }
                return (text, sum, n)
            }()
            if let last = try await analyzer.analyzeSequence(from: file) {
                try await analyzer.finalizeAndFinish(through: last)
            } else {
                await analyzer.cancelAndFinishNow()
            }
            let (text, sum, n) = try await collected
            return ["text": text.trimmingCharacters(in: .whitespacesAndNewlines), "conf": String(n > 0 ? sum / Double(n) : 0)]
        } catch {
            return ["why": "could not be read as audio"]
        }
    }
    #endif

    /// The older engine. Used only when the permission is already there: this never asks for it.
    static func classic(_ url: URL, _ localeId: String) -> [String: String] {
        guard SFSpeechRecognizer.authorizationStatus() == .authorized else { return ["why": "needs permission"] }
        guard let rec = SFSpeechRecognizer(locale: Locale(identifier: localeId)), rec.supportsOnDeviceRecognition else { return ["why": "not installed"] }
        let req = SFSpeechURLRecognitionRequest(url: url)
        req.requiresOnDeviceRecognition = true          // never the network
        req.shouldReportPartialResults = false
        let sem = DispatchSemaphore(value: 0)
        let box = Box<[String: String]>()
        box.value = ["why": "could not be read as audio"]
        let task = rec.recognitionTask(with: req) { result, error in
            if let r = result, r.isFinal {
                let segs = r.bestTranscription.segments
                let conf = segs.isEmpty ? 0 : segs.map { Double($0.confidence) }.reduce(0, +) / Double(segs.count)
                box.value = ["text": r.bestTranscription.formattedString, "conf": String(conf)]
                sem.signal()
            } else if error != nil {
                sem.signal()
            }
        }
        if sem.wait(timeout: .now() + 600) == .timedOut { task.cancel() }
        return box.value!
    }
}
