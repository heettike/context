// draws the context mark. run through tools/logo.sh. geometry here is the source of truth for the svg and the in-app mark.
// the mark: an open ring (everything before now) and a dot resting in its mouth (now). the dot closes the circle.
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let paper = CGColor(red: 0xF5 / 255, green: 0xF4 / 255, blue: 0xF0 / 255, alpha: 1)
let ink = CGColor(red: 0x17 / 255, green: 0x18 / 255, blue: 0x1A / 255, alpha: 1)
let dotColor = CGColor(red: 0xF2 / 255, green: 0x6B / 255, blue: 0x3A / 255, alpha: 1)

/// mark inside a square of side `s` centred at (cx, cy). ring radius .34s, stroke .19s, mouth 84 degrees, dot radius .088s.
func mark(_ g: CGContext, cx: CGFloat, cy: CGFloat, s: CGFloat, ring: CGColor, dot: CGColor) {
    let r = 0.34 * s, w = 0.19 * s, half = 42.0 * CGFloat.pi / 180
    g.setStrokeColor(ring); g.setLineWidth(w); g.setLineCap(.round)
    g.addArc(center: CGPoint(x: cx, y: cy), radius: r, startAngle: half, endAngle: 2 * .pi - half, clockwise: false)
    g.strokePath()
    g.setFillColor(dot)
    let d = 0.088 * s
    g.fillEllipse(in: CGRect(x: cx + r - d, y: cy - d, width: 2 * d, height: 2 * d))
}

func png(_ w: Int, _ h: Int, _ path: String, _ draw: (CGContext) -> Void) {
    let g = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    draw(g)
    let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: path) as CFURL, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(dest, g.makeImage()!, nil)
    CGImageDestinationFinalize(dest)
}

let out = CommandLine.arguments[1]
// app icon: paper tile on apple's 1024 grid (824 tile, 100 margin), flat, mark at 58% of the tile
png(1024, 1024, out + "/icon-1024.png") { g in
    let tile = CGRect(x: 100, y: 100, width: 824, height: 824)
    g.addPath(CGPath(roundedRect: tile, cornerWidth: 185, cornerHeight: 185, transform: nil))
    g.setFillColor(paper); g.fillPath()
    g.addPath(CGPath(roundedRect: tile.insetBy(dx: 1, dy: 1), cornerWidth: 184, cornerHeight: 184, transform: nil))
    g.setStrokeColor(CGColor(gray: 0, alpha: 0.08)); g.setLineWidth(2); g.strokePath()
    mark(g, cx: 512 - 12, cy: 512, s: 560, ring: ink, dot: dotColor)
}
// the mark alone, for docs
png(512, 512, out + "/mark.png") { g in mark(g, cx: 256 - 6, cy: 256, s: 500, ring: ink, dot: dotColor) }
// github social card, 1280 x 640
png(1280, 640, out + "/social.png") { g in
    g.setFillColor(paper); g.fill(CGRect(x: 0, y: 0, width: 1280, height: 640))
    mark(g, cx: 640 - 6, cy: 320, s: 300, ring: ink, dot: dotColor)
}
