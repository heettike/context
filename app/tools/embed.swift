// embed: sentence vectors from the models macOS ships, for ctx/semantic.py. No download, no network.
//
//   embed info [--model M]                 one json line: {"model": ..., "dim": ...}
//   embed vectors [--model M]              one text per line on stdin -> float32 vectors on stdout, unit length, in order
//   embed ask <file> [--model M]           stdin: line 1 a question (or several texts separated by tabs: the best
//                                          match counts), line 2 words separated by spaces. stdout: one json
//                                          line {"rows": n, "near": {word: [[neighbour, similarity], ...]}}, then n float32:
//                                          the cosine of the question against each unit vector in <file>, a flat float32
//                                          matrix. the neighbours come from the english word vectors. <file> "-" = no matrix
//                                          --dim N --queries <f>: compare with the float32 query vectors in <f> instead
//
// M: "sentence" (NLEmbedding.sentenceEmbedding, english, the default), "contextual" (NLContextualEmbedding, latin
// script, mean of the token vectors) or "both" (the two side by side, each scaled so the pair has unit length).
// A text that cannot be embedded gives a vector of zeros, so the output always lines up with the input.
// Built by the engine on first use: swiftc -O app/tools/embed.swift -o CTX_HOME/bin/embed
import Accelerate
import Foundation
import NaturalLanguage

func unit(_ v: [Float]) -> [Float] {
    var n: Float = 0
    vDSP_svesq(v, 1, &n, vDSP_Length(v.count))
    n = n.squareRoot()
    if n == 0 || !n.isFinite { return [Float](repeating: 0, count: v.count) }
    var out = [Float](repeating: 0, count: v.count)
    var d = n
    vDSP_vsdiv(v, 1, &d, &out, 1, vDSP_Length(v.count))
    return out
}

final class Model {
    let name: String
    var sentence: NLEmbedding?
    var contextual: AnyObject?
    var dim = 0

    init?(_ name: String) {
        self.name = name
        if name == "sentence" || name == "both" {
            guard let e = NLEmbedding.sentenceEmbedding(for: .english) else { return nil }
            sentence = e
            dim += e.dimension
        }
        if name == "contextual" || name == "both" {
            guard #available(macOS 14.0, *), let c = NLContextualEmbedding(script: .latin), c.hasAvailableAssets else { return nil }
            do { try c.load() } catch { return nil }
            contextual = c
            dim += c.dimension
        }
        if dim == 0 { return nil }
    }

    func one(_ text: String) -> [Float] {
        var out: [Float] = []
        if let e = sentence {
            let v = e.vector(for: text).map { unit($0.map { Float($0) }) } ?? [Float](repeating: 0, count: e.dimension)
            out += v
        }
        if #available(macOS 14.0, *), let c = contextual as? NLContextualEmbedding {
            var sum = [Float](repeating: 0, count: c.dimension)
            var n = 0
            if let r = try? c.embeddingResult(for: text, language: nil) {
                r.enumerateTokenVectors(in: text.startIndex..<text.endIndex) { v, _ in
                    for i in 0..<min(v.count, sum.count) { sum[i] += Float(v[i]) }
                    n += 1
                    return true
                }
            }
            out += n > 0 ? unit(sum) : sum
        }
        return name == "both" ? unit(out) : out
    }
}

func fail(_ s: String) -> Never {
    FileHandle.standardError.write((s + "\n").data(using: .utf8)!)
    exit(2)
}

var args = Array(CommandLine.arguments.dropFirst())
var modelName = "sentence"
if let i = args.firstIndex(of: "--model"), i + 1 < args.count {
    modelName = args[i + 1]
    args.removeSubrange(i...i + 1)
}
var dimArg = 0
if let i = args.firstIndex(of: "--dim"), i + 1 < args.count {
    dimArg = Int(args[i + 1]) ?? 0
    args.removeSubrange(i...i + 1)
}
var queryFile = ""
if let i = args.firstIndex(of: "--queries"), i + 1 < args.count {
    queryFile = args[i + 1]
    args.removeSubrange(i...i + 1)
}
guard let cmd = args.first else { fail("usage: embed info | vectors | ask <file> [--model sentence|contextual|both]") }
guard let model = Model(modelName) else { fail("model not available on this mac: " + modelName) }
let out = FileHandle.standardOutput

func put(_ v: [Float]) {
    v.withUnsafeBufferPointer { out.write(Data(buffer: $0)) }
}

switch cmd {
case "info":
    print("{\"model\": \"\(modelName)\", \"dim\": \(model.dim)}")
case "vectors":
    var buf: [Float] = []
    var n = 0
    while let line = readLine(strippingNewline: true) {
        buf += autoreleasepool { model.one(line) }
        n += 1
        if n % 64 == 0 { put(buf); buf.removeAll(keepingCapacity: true) }
    }
    put(buf)
case "ask":
    guard args.count >= 2 else { fail("ask needs the vector file, or -") }
    let question = readLine(strippingNewline: true) ?? ""
    let words = (readLine(strippingNewline: true) ?? "").split(separator: " ").map(String.init)
    var near: [String: [[Any]]] = [:]
    if let w = NLEmbedding.wordEmbedding(for: .english) {
        for word in words.prefix(24) {
            let ns = w.neighbors(for: word, maximumCount: 12, distanceType: .cosine)
            // the framework's "cosine" distance is the length of the difference of the unit vectors: cos = 1 - d*d/2
            let keep = ns.map { ($0.0.lowercased(), 1 - $0.1 * $0.1 / 2) }.filter { $0.1 >= 0.45 }.map { [$0.0, $0.1 as Any] }
            if !keep.isEmpty { near[word] = keep }
        }
    }
    // --dim N --queries <file>: the question was embedded elsewhere (another embedder); its float32 vectors are in the file
    var given: [[Float]] = []
    if !queryFile.isEmpty, dimArg > 0, let qd = try? Data(contentsOf: URL(fileURLWithPath: queryFile)) {
        let all = qd.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
        given = stride(from: 0, to: all.count - dimArg + 1, by: dimArg).map { Array(all[$0..<$0 + dimArg]) }
    }
    let dim = given.isEmpty ? model.dim : dimArg
    var res: [Float] = []
    if args[1] != "-", let data = try? Data(contentsOf: URL(fileURLWithPath: args[1]), options: .alwaysMapped) {
        let rows = data.count / (dim * MemoryLayout<Float>.size)
        res = [Float](repeating: -1, count: rows)
        if rows > 0 {
            // several texts on the question line, separated by tabs: a unit scores by the one it is closest to
            var one = [Float](repeating: 0, count: rows)
            let queries = given.isEmpty ? question.split(separator: "\t").prefix(6).map { model.one(String($0)) } : Array(given.prefix(6))
            for q in queries {
                data.withUnsafeBytes { raw in
                    let m = raw.bindMemory(to: Float.self).baseAddress!
                    vDSP_mmul(m, 1, q, 1, &one, 1, vDSP_Length(rows), 1, vDSP_Length(dim))
                }
                vDSP_vmax(res, 1, one, 1, &res, 1, vDSP_Length(rows))
            }
        }
    }
    let head = (try? JSONSerialization.data(withJSONObject: ["rows": res.count, "near": near])) ?? Data("{}".utf8)
    out.write(head)
    out.write(Data("\n".utf8))
    put(res)
default:
    fail("unknown command: " + cmd)
}
