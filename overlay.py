"""Floating recording indicator — a small pill at the bottom of the screen.

Minimal, Apple-like: a compact translucent dark pill. While recording it shows
a small red dot + "Listening…" in white; while transcribing, a dimmed
"Processing…". Floats above all windows, click-through, on every Space.
All AppKit calls are dispatched to the main thread via AppHelper.callAfter.
"""

import AppKit
from PyObjCTools import AppHelper

import config

_WIDTH, _HEIGHT = 132, 30
_MARGIN_BOTTOM = 60
_BG_ALPHA = 0.82
_FONT_SIZE = 12.5


class Overlay:
    def __init__(self):
        self._panel = None
        self._label = None

    # ── public API (safe to call from any thread) ─────────────────────────
    def recording(self, text="Listening…"):
        AppHelper.callAfter(self._show, text, True)

    def processing(self):
        AppHelper.callAfter(self._show, "Processing…", False)

    def hide(self):
        AppHelper.callAfter(self._hide)

    # ── main-thread internals ─────────────────────────────────────────────
    def _ensure_panel(self):
        if self._panel is not None:
            return
        screen = AppKit.NSScreen.mainScreen().frame()
        rect = AppKit.NSMakeRect(
            (screen.size.width - _WIDTH) / 2, _MARGIN_BOTTOM, _WIDTH, _HEIGHT
        )
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(AppKit.NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setIgnoresMouseEvents_(True)
        panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        content = AppKit.NSView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, _WIDTH, _HEIGHT)
        )
        content.setWantsLayer_(True)
        content.layer().setBackgroundColor_(
            AppKit.NSColor.blackColor().colorWithAlphaComponent_(_BG_ALPHA).CGColor()
        )
        content.layer().setCornerRadius_(_HEIGHT / 2)

        label = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, (_HEIGHT - 18) / 2, _WIDTH, 18)
        )
        label.setEditable_(False)
        label.setBordered_(False)
        label.setDrawsBackground_(False)
        label.setAlignment_(AppKit.NSTextAlignmentCenter)
        # Live preview can outgrow the pill: keep the END of the text visible
        # (newest words), truncating with "…" at the head.
        label.cell().setLineBreakMode_(AppKit.NSLineBreakByTruncatingHead)
        content.addSubview_(label)

        panel.setContentView_(content)
        self._panel = panel
        self._label = label

    def _attributed(self, text, with_dot):
        """'● text' with only the dot in red, or dimmed plain text."""
        para = AppKit.NSMutableParagraphStyle.alloc().init()
        para.setAlignment_(AppKit.NSTextAlignmentCenter)
        font = AppKit.NSFont.systemFontOfSize_weight_(
            _FONT_SIZE, AppKit.NSFontWeightMedium
        )
        if with_dot:
            result = AppKit.NSMutableAttributedString.alloc().initWithString_attributes_(
                "● ",
                {
                    AppKit.NSFontAttributeName: font,
                    AppKit.NSForegroundColorAttributeName: AppKit.NSColor.systemRedColor(),
                    AppKit.NSParagraphStyleAttributeName: para,
                },
            )
            result.appendAttributedString_(
                AppKit.NSAttributedString.alloc().initWithString_attributes_(
                    text,
                    {
                        AppKit.NSFontAttributeName: font,
                        AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor().colorWithAlphaComponent_(0.95),
                        AppKit.NSParagraphStyleAttributeName: para,
                    },
                )
            )
            return result
        return AppKit.NSAttributedString.alloc().initWithString_attributes_(
            text,
            {
                AppKit.NSFontAttributeName: font,
                AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor().colorWithAlphaComponent_(0.6),
                AppKit.NSParagraphStyleAttributeName: para,
            },
        )

    def _show(self, text, with_dot):
        self._ensure_panel()
        attributed = self._attributed(text, with_dot)
        self._label.setAttributedStringValue_(attributed)
        # Grow the pill to fit the text, but stay compact — long previews are
        # head-truncated by the label, so the newest words always show.
        screen = AppKit.NSScreen.mainScreen().frame()
        width = min(
            max(_WIDTH, attributed.size().width + 36),
            config.OVERLAY_MAX_WIDTH,
            screen.size.width * 0.6,
        )
        self._panel.setFrame_display_(
            AppKit.NSMakeRect(
                (screen.size.width - width) / 2, _MARGIN_BOTTOM, width, _HEIGHT
            ),
            True,
        )
        self._panel.contentView().setFrame_(AppKit.NSMakeRect(0, 0, width, _HEIGHT))
        self._label.setFrame_(
            AppKit.NSMakeRect(12, (_HEIGHT - 18) / 2, width - 24, 18)
        )
        self._panel.orderFrontRegardless()

    def _hide(self):
        if self._panel is not None:
            self._panel.orderOut_(None)
