from __future__ import annotations

import sys
from pathlib import Path


if __package__:
    from .scraper import main
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from onepiece_card_scraper.scraper import main


if __name__ == "__main__":
    raise SystemExit(main())
