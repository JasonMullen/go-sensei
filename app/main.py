from __future__ import annotations

def _enable_windows_high_dpi() -> None:
    try:
        import ctypes

        # Best option on modern Windows.
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)  # PER_MONITOR_AWARE_V2
            return
        except Exception:
            pass

        # Fallback.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            return
        except Exception:
            pass

        # Older fallback.
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    except Exception:
        pass


_enable_windows_high_dpi()

from app.ui.board_window import main

if __name__ == "__main__":
    main()
