import SwiftUI
import UIKit
import QuartzCore

/// A view whose layer is a CAMetalLayer: the surface the Vulkan lab presents
/// to. Reports once it has a size, after MoltenVK's drawable size is set.
final class VulkanLabSurfaceView: UIView {
    override class var layerClass: AnyClass { CAMetalLayer.self }
    var metalLayer: CAMetalLayer { layer as! CAMetalLayer }
    var onReady: ((CAMetalLayer) -> Void)?
    private var reported = false

    override func layoutSubviews() {
        super.layoutSubviews()
        guard bounds.width > 0, bounds.height > 0 else { return }
        let scale = window?.screen.scale ?? UIScreen.main.scale
        metalLayer.contentsScale = scale
        metalLayer.drawableSize = CGSize(width: bounds.width * scale, height: bounds.height * scale)
        metalLayer.pixelFormat = .bgra8Unorm
        if !reported {
            reported = true
            let layer = metalLayer
            DispatchQueue.main.async { [weak self] in self?.onReady?(layer) }
        }
    }
}

struct VulkanLabSurface: UIViewRepresentable {
    let onReady: (CAMetalLayer) -> Void
    func makeUIView(context: Context) -> VulkanLabSurfaceView {
        let v = VulkanLabSurfaceView()
        v.backgroundColor = .black
        v.onReady = onReady
        return v
    }
    func updateUIView(_ v: VulkanLabSurfaceView, context: Context) {}
}

/// The Vulkan lab sheet (vulkan branch): MoltenVK draws a colour-cycling
/// triangle for about two seconds on the surface at the top, and every step is
/// listed below and written to the log as `[vulkan]`.
struct VulkanLabView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var lines: [String] = []
    @State private var running = false
    @State private var finished = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                VulkanLabSurface { layer in start(layer) }
                    .frame(height: 280)
                if finished, let result = lines.last(where: { $0.hasPrefix("RESULT") || $0.hasPrefix("FAILED") }) {
                    Text(result)
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(result.hasPrefix("FAILED") ? Color.red : Color.green)
                        .padding(8)
                }
                List {
                    ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                        Text(line).font(.system(.caption2, design: .monospaced))
                    }
                }
                .listStyle(.plain)
            }
            .navigationTitle("Vulkan lab")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") { MadeiraVulkanLabStop(); dismiss() }
                }
            }
        }
        .onDisappear { MadeiraVulkanLabStop() }
    }

    private func start(_ layer: CAMetalLayer) {
        guard !running, !finished else { return }
        running = true
        LogStore.shared.log("[vulkan] lab started (\(Int(layer.drawableSize.width))x\(Int(layer.drawableSize.height)))")
        MadeiraVulkanLabRun(layer, { line in
            LogStore.shared.log("[vulkan] \(line)")
            DispatchQueue.main.async { lines.append(line) }
        }, {
            DispatchQueue.main.async { running = false; finished = true }
        })
    }
}

/// The Settings section for the console-emulation experiments (vulkan branch).
/// Nothing here changes how games run; both rows only write to the log.
struct ConsoleLabSection: View {
    var open: (SettingsSheet) -> Void = { _ in }
    @State private var probing = false
    @State private var last = ""

    var body: some View {
        Section {
            Button { open(.vulkanLab) } label: {
                Label("Draw a Vulkan triangle", systemImage: "triangle")
            }
            Button {
                probing = true
                last = "Probing…"
                LogStore.shared.log("[addrspace] probe started")
                MadeiraAddressSpaceProbe({ line in
                    LogStore.shared.log("[addrspace] \(line)")
                    DispatchQueue.main.async { last = line }
                }, {
                    DispatchQueue.main.async { probing = false }
                })
            } label: {
                Label(probing ? "Probing address space…" : "Probe address space", systemImage: "memorychip")
            }
            .disabled(probing)
            if !last.isEmpty {
                Text(last).font(.caption).foregroundStyle(.secondary)
            }
        } header: { Text("Console lab") } footer: {
            Text("Experiments towards running PS4 and PS5 games inside Madeira. The triangle proves MoltenVK (Vulkan on Metal) works on this device: instance, device, swapchain, a SPIR-V pipeline and presentation. The probe reports how much address space iOS grants this app, and whether the fixed ranges console emulators reserve are free. Both only write to the log (Share log afterwards); nothing here changes how games run.")
        }
    }
}
