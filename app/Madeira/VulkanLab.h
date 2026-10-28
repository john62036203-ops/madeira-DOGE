#import <Foundation/Foundation.h>
#import <QuartzCore/QuartzCore.h>

/// The Vulkan lab (vulkan branch): proves MoltenVK works inside Madeira on this
/// device before any emulator is built on it. Creates a Vulkan instance and
/// device through the statically linked MoltenVK, a surface on `layer`, a
/// swapchain, and draws a colour triangle for about two seconds; then reports
/// what the device offers (version, limits, memory heaps, the extensions the
/// PS4/PS5 renderers need). Runs on a background queue; `log` gets each line
/// (any thread), `done` once at the end. Every line also goes to the app log
/// as `[vulkan]`.
void MadeiraVulkanLabRun(CALayer *_Nonnull layer,
                         void (^_Nonnull log)(NSString *_Nonnull line),
                         void (^_Nonnull done)(void));

/// Stops a running lab (the sheet closed). Safe to call when none runs.
void MadeiraVulkanLabStop(void);

/// The address-space probe: how much virtual memory iOS lets this process
/// reserve, in one piece and at the fixed addresses console emulators ask
/// for (PS4 games are linked for 0x400000, shadPS4 reserves its guest range
/// from 0x1000000000; the JIT pool and the guest image already hold their
/// parts). Reservations are PROT_NONE and released again. Same reporting
/// contract as the lab.
void MadeiraAddressSpaceProbe(void (^_Nonnull log)(NSString *_Nonnull line),
                              void (^_Nonnull done)(void));
