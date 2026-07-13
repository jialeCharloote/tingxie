"""Global hotkey listeners.

Two backends:
  - FnListener: Quartz CGEvent tap for the fn/🌐 key (pynput can't see it).
    fn arrives as a flagsChanged event with keycode 63; pressed/released is
    read from the SecondaryFn modifier flag.
  - ChordListener: pynput-based chord (e.g. "<ctrl>+<alt>+<space>").

Both call on_press() when the hotkey goes down and on_release() when it goes up.
"""

import threading

FN_KEYCODE = 63  # kVK_Function


class FnListener:
    """Push-to-talk on the fn/🌐 key via a Quartz event tap.

    Also detects double-tap: two presses within 0.3s → calls on_double_tap.
    """

    def __init__(self, on_press, on_release, on_double_tap=None):
        self.on_press = on_press
        self.on_release = on_release
        self.on_double_tap = on_double_tap or (lambda: None)
        self._down = False
        self._last_press = 0.0  # time of the last fn press (for double-tap detection)
        import time

        self._time = time

    def _callback(self, proxy, type_, event, refcon):
        # Never let an exception escape: it would tear down the CFRunLoop and
        # silently kill the global hotkey for the rest of the session.
        try:
            self._handle(event)
        except Exception:
            import traceback

            traceback.print_exc()
        return event

    def _handle(self, event):
        import Quartz

        type_ = Quartz.CGEventGetType(event)
        if type_ == Quartz.kCGEventFlagsChanged:
            keycode = Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventKeycode
            )
            if keycode == FN_KEYCODE:
                pressed = bool(
                    Quartz.CGEventGetFlags(event)
                    & Quartz.kCGEventFlagMaskSecondaryFn
                )
                if pressed and not self._down:
                    self._down = True
                    now = self._time.monotonic()
                    if now - self._last_press < 0.3:  # double-tap within 300ms
                        self.on_double_tap()
                    self._last_press = now
                    self.on_press()
                elif not pressed and self._down:
                    self._down = False
                    self.on_release()

    def run(self):
        """Block forever listening for fn. Requires Input Monitoring permission."""
        import Quartz

        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,  # observe only, don't swallow keys
            Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged),
            self._callback,
            None,
        )
        if tap is None:
            raise PermissionError(
                "Could not create event tap. Grant your terminal Input Monitoring "
                "permission in System Settings > Privacy & Security, then restart it."
            )
        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopCommonModes
        )
        Quartz.CGEventTapEnable(tap, True)
        Quartz.CFRunLoopRun()


class ChordListener:
    """Push-to-talk on a pynput chord like '<ctrl>+<alt>+<space>'."""

    def __init__(self, chord, on_press, on_release):
        self.chord = chord
        self.on_press = on_press
        self.on_release = on_release
        self._active = False

    def run(self):
        from pynput import keyboard

        def activate():
            self._active = True
            self.on_press()

        hotkey = keyboard.HotKey(keyboard.HotKey.parse(self.chord), activate)

        def press(key):
            hotkey.press(listener.canonical(key))

        def release(key):
            hotkey.release(listener.canonical(key))
            if self._active:
                self._active = False
                self.on_release()

        with keyboard.Listener(on_press=press, on_release=release) as listener:
            listener.join()


def make_listener(hotkey, on_press, on_release, on_double_tap=None):
    if hotkey.lower() in ("fn", "globe", "<fn>"):
        return FnListener(on_press, on_release, on_double_tap)
    return ChordListener(hotkey, on_press, on_release)


if __name__ == "__main__":
    # Quick manual test: prints press/release events for the configured hotkey.
    import config

    listener = make_listener(
        config.HOTKEY,
        lambda: print("fn DOWN  → would start recording"),
        lambda: print("fn UP    → would transcribe + paste"),
    )
    print(f"Listening for '{config.HOTKEY}'… press it (Ctrl+C to quit)")
    try:
        listener.run()
    except KeyboardInterrupt:
        pass
