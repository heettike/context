import AppKit
import SwiftUI

/// the context mark: an open ring (everything before now) with a dot resting in its mouth (now).
/// it is the app's mark, in the window and the dock. the menu bar has a mark of its own, below.
/// geometry matches tools/logo.swift: ring radius .34, stroke .19, mouth 84 degrees, dot radius .088 of the side.
struct LogoMark: View {
    var size: CGFloat = 18
    var coloured = true
    static let dot = Color(red: 0xF2 / 255, green: 0x6B / 255, blue: 0x3A / 255)

    var body: some View {
        ZStack {
            Circle()
                .trim(from: 42.0 / 360, to: 318.0 / 360)
                .stroke(Ink.ink, style: StrokeStyle(lineWidth: 0.19 * size, lineCap: .round))
                .frame(width: 0.68 * size, height: 0.68 * size)
            Circle()
                .fill(coloured ? LogoMark.dot : Ink.ink)
                .frame(width: 0.176 * size, height: 0.176 * size)
                .offset(x: 0.34 * size)
        }
        .frame(width: size, height: size)
        .accessibilityLabel("context")
    }

    /// The menu-bar mark: a dot between two square brackets, "you, in context". It is not the app's ring: at
    /// 18 points an open ring is a letter c, and a c in the menu bar is somebody else's product.
    /// 1.8 pt strokes with round caps and joins; the brackets stand 3.6 to 6.6 pt either side of the centre and
    /// reach 6 pt above and below it; the dot is 2 pt in radius.
    static func drawMenuBarMark(in rect: NSRect, ink: NSColor, dot: NSColor, dotRadius: CGFloat = 2.0) {
        let c = NSPoint(x: rect.midX, y: rect.midY), k = min(rect.width, rect.height) / 18
        ink.setStroke()
        for side: CGFloat in [-1, 1] {
            let b = NSBezierPath()
            b.move(to: NSPoint(x: c.x + side * 3.6 * k, y: c.y + 6 * k))
            b.line(to: NSPoint(x: c.x + side * 6.6 * k, y: c.y + 6 * k))
            b.line(to: NSPoint(x: c.x + side * 6.6 * k, y: c.y - 6 * k))
            b.line(to: NSPoint(x: c.x + side * 3.6 * k, y: c.y - 6 * k))
            b.lineWidth = 1.8 * k
            b.lineCapStyle = .round
            b.lineJoinStyle = .round
            b.stroke()
        }
        dot.setFill()
        let r = dotRadius * k
        NSBezierPath(ovalIn: NSRect(x: c.x - r, y: c.y - r, width: r * 2, height: r * 2)).fill()
    }

    /// one-colour template for the menu bar.
    static func menuBarImage() -> NSImage {
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { rect in
            drawMenuBarMark(in: rect, ink: .black, dot: .black)
            return true
        }
        image.isTemplate = true
        return image
    }
}
