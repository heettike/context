// media: what is in a picture, a pdf, a voice note or a video, read on this Mac with Apple's own frameworks, for
// ctx/media.py. No download, no network, nothing leaves the Mac. It only ever reads the files it is given.
//
//   media info                 one json line: the languages text recognition knows, and what speech can do here
//   media read [options]       stdin: one json object per line, {"kind": "image" | "pdf" | "audio" | "video", "path": ...}
//                              stdout: one json line per input line, in order, written as soon as it is known
//       --max-chars N          keep at most N characters of a pdf's text (default 20000); "chars" is the full length seen
//       --ocr-pages N          recognise text on at most N pdf pages that have no text layer (default 8)
//       --labels X             keep "what is in the picture" labels at or above this confidence (default 0.5)
//       --locale L             the speech locale for audio (default: this mac's own language)
//
// image -> {"ok": true, "text": ..., "conf": 0..1, "labels": [[name, confidence], ...], "w": px, "h": px}
// pdf   -> {"ok": true, "text": ..., "pages": n, "chars": n, "ocr_pages": n} or {"ok": false, "why": "locked"}
// audio -> see media_speech.swift
// video -> {"ok": true, "secs": ..., "w": px, "h": px}
// Every answer carries "ms", the time it took. A file that cannot be read answers {"ok": false, "why": ...}.
//
// Built by the engine on first use:
//   swiftc -O -parse-as-library app/tools/media.swift app/tools/media_speech.swift -o CTX_HOME/bin/media
import AVFoundation
import CoreGraphics
import Foundation
import ImageIO
import PDFKit
import Vision

struct Options {
    var maxChars = 20000
    var ocrPages = 8
    var labels: Float = 0.5
    var locale = MediaSpeech.systemLocale
}

func emit(_ d: [String: Any]) {
    let data = (try? JSONSerialization.data(withJSONObject: d, options: [])) ?? Data("{\"ok\":false,\"why\":\"unreadable\"}".utf8)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

/// The words and the labels of one picture. Text is read at the accurate level, the language found by Vision itself.
func look(_ image: CGImage, labels: Float, classify: Bool) -> [String: Any] {
    let text = VNRecognizeTextRequest()
    text.recognitionLevel = .accurate
    text.usesLanguageCorrection = true
    if #available(macOS 13.0, *) { text.automaticallyDetectsLanguage = true }
    let kind = VNClassifyImageRequest()
    do {
        try VNImageRequestHandler(cgImage: image, options: [:]).perform(classify ? [text, kind] : [text])
    } catch {
        return ["ok": false, "why": "could not be read as a picture"]
    }
    var lines: [String] = [], sum: Float = 0
    for o in text.results ?? [] {
        guard let c = o.topCandidates(1).first, c.confidence >= 0.3 else { continue }
        lines.append(c.string)
        sum += c.confidence
    }
    var found: [[Any]] = []
    if classify {
        for c in (kind.results ?? []).filter({ $0.confidence >= labels }).prefix(6) {
            found.append([c.identifier.replacingOccurrences(of: "_", with: " "), Double((c.confidence * 100).rounded() / 100)])
        }
    }
    return ["ok": true, "text": lines.joined(separator: "\n"), "conf": lines.isEmpty ? 0 : Double(sum / Float(lines.count)), "labels": found]
}

/// A see-through picture laid on white: dark text on a clear background is otherwise read as black on black.
func onWhite(_ image: CGImage) -> CGImage {
    switch image.alphaInfo {
    case .none, .noneSkipFirst, .noneSkipLast: return image
    default: break
    }
    guard let ctx = CGContext(data: nil, width: image.width, height: image.height, bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return image }
    let all = CGRect(x: 0, y: 0, width: image.width, height: image.height)
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(all)
    ctx.draw(image, in: all)
    return ctx.makeImage() ?? image
}

func readImage(_ path: String, _ opt: Options) -> [String: Any] {
    let url = URL(fileURLWithPath: path) as CFURL
    guard let src = CGImageSourceCreateWithURL(url, nil), CGImageSourceGetCount(src) > 0 else { return ["ok": false, "why": "could not be read as a picture"] }
    let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any] ?? [:]
    let w = props[kCGImagePropertyPixelWidth] as? Int ?? 0, h = props[kCGImagePropertyPixelHeight] as? Int ?? 0
    if w > 0 && h > 0 && min(w, h) < 100 { return ["ok": true, "text": "", "conf": 0, "labels": [[Any]](), "w": w, "h": h, "tiny": true] }
    // decoded upright, and no larger than a long page needs: a 12000 px panorama costs memory and adds no words
    let thumb: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceCreateThumbnailWithTransform: true,
                                  kCGImageSourceThumbnailMaxPixelSize: 6000]
    guard let decoded = CGImageSourceCreateThumbnailAtIndex(src, 0, thumb as CFDictionary) else { return ["ok": false, "why": "could not be read as a picture"] }
    var out = look(onWhite(decoded), labels: opt.labels, classify: true)
    out["w"] = w
    out["h"] = h
    return out
}

func render(_ page: PDFPage) -> CGImage? {
    let box = page.bounds(for: .mediaBox)
    guard box.width > 1, box.height > 1 else { return nil }
    let scale = min(2200 / max(box.width, box.height), 4)
    let w = Int(box.width * scale), h = Int(box.height * scale)
    guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.scaleBy(x: scale, y: scale)
    ctx.translateBy(x: -box.minX, y: -box.minY)
    page.draw(with: .mediaBox, to: ctx)
    return ctx.makeImage()
}

func readPDF(_ path: String, _ opt: Options) -> [String: Any] {
    guard let doc = PDFDocument(url: URL(fileURLWithPath: path)) else { return ["ok": false, "why": "could not be read as a pdf"] }
    if doc.isLocked { return ["ok": false, "why": "locked"] }
    var text = "", chars = 0, ocr = 0
    let pages = doc.pageCount
    for i in 0..<min(pages, 400) {          // "chars" is counted over the first 400 pages; a longer book is not weighed whole
        guard let page = doc.page(at: i) else { continue }
        var s = (page.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if s.count < 20 && ocr < opt.ocrPages && text.count < opt.maxChars, let image = render(page) {
            ocr += 1
            s = (look(image, labels: 1, classify: false)["text"] as? String) ?? s
        }
        chars += s.count
        if text.count < opt.maxChars && !s.isEmpty { text += (text.isEmpty ? "" : "\n\n") + s }
    }
    return ["ok": true, "text": String(text.prefix(opt.maxChars)), "pages": pages, "chars": chars, "ocr_pages": ocr]
}

func readVideo(_ path: String) -> [String: Any] {
    let asset = AVURLAsset(url: URL(fileURLWithPath: path))
    let secs = CMTimeGetSeconds(asset.duration)
    guard secs.isFinite, secs > 0 else { return ["ok": false, "why": "could not be read as a video"] }
    var out: [String: Any] = ["ok": true, "secs": (secs * 10).rounded() / 10]
    if let t = asset.tracks(withMediaType: .video).first {
        let size = t.naturalSize.applying(t.preferredTransform)
        out["w"] = Int(abs(size.width))
        out["h"] = Int(abs(size.height))
    }
    return out
}

@main
enum Media {
    static func main() {
        let args = CommandLine.arguments
        var opt = Options()
        func value(_ flag: String) -> String? {
            guard let i = args.firstIndex(of: flag), i + 1 < args.count else { return nil }
            return args[i + 1]
        }
        opt.maxChars = Int(value("--max-chars") ?? "") ?? opt.maxChars
        opt.ocrPages = Int(value("--ocr-pages") ?? "") ?? opt.ocrPages
        opt.labels = Float(value("--labels") ?? "") ?? opt.labels
        opt.locale = value("--locale") ?? opt.locale
        switch args.count > 1 ? args[1] : "" {
        case "info":
            let req = VNRecognizeTextRequest()
            req.recognitionLevel = .accurate
            emit(["ocr_languages": (try? req.supportedRecognitionLanguages()) ?? [String](), "speech": MediaSpeech.info()])
        case "read":
            while let line = readLine(strippingNewline: true) {
                let t0 = Date()
                var out: [String: Any] = ["ok": false, "why": "bad request"]
                if let d = (try? JSONSerialization.jsonObject(with: Data(line.utf8))) as? [String: Any], let path = d["path"] as? String {
                    autoreleasepool {
                        switch d["kind"] as? String ?? "" {
                        case "image": out = readImage(path, opt)
                        case "pdf": out = readPDF(path, opt)
                        case "audio": out = MediaSpeech.transcribe(path, locale: (d["locale"] as? String) ?? opt.locale)
                        case "video": out = readVideo(path)
                        default: break
                        }
                    }
                }
                out["ms"] = Int(Date().timeIntervalSince(t0) * 1000)
                emit(out)
            }
        default:
            FileHandle.standardError.write(Data("usage: media info | media read [--max-chars N] [--ocr-pages N] [--labels X] [--locale L]\n".utf8))
            exit(2)
        }
    }
}
