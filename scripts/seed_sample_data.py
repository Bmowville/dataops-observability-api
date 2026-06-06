import sys
from os import chdir
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    chdir(ROOT)
    sys.path.insert(0, str(ROOT))

    from app.db.session import SessionLocal
    from app.services.sample_data import seed_sample_data

    with SessionLocal() as db:
        summary = seed_sample_data(db)
    print(summary.model_dump_json(indent=2))


if __name__ == "__main__":
    main()