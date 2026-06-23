from __future__ import annotations

import os
import sys
import traceback

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

PAGE_KEY = "buff"
PAGE_MODULE = "modules.mod_buff"


def main() -> None:
    if "--smoke-import-page" in sys.argv:
        __import__(PAGE_MODULE)
        return

    if "--smoke-video-deps" in sys.argv:
        log_path = os.environ.get("DNF_PALETTE_BUFF_SMOKE_LOG")
        try:
            module = __import__(PAGE_MODULE, fromlist=["validate_video_dependencies"])
            module.validate_video_dependencies()
        except Exception:
            if log_path:
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(traceback.format_exc())
            raise
        return

    from main import MainApplication

    app = MainApplication()
    app.title("BUFF 替换")
    try:
        app.sidebar.pack_forget()
    except Exception:
        pass
    app.show_page(PAGE_KEY)
    app.mainloop()


if __name__ == "__main__":
    main()
