"""Entry point redirecting to src.app."""

from taxo_trainer.app import main

if __name__ in {"__main__", "__mp_main__"}:
    main()
