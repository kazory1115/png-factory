import sys


def main() -> None:
    if "--smoke-test" in sys.argv:
        from app.remover import IMPORT_ERROR, rembg_remove

        if rembg_remove is None:
            raise RuntimeError("AI removal engine failed to load") from IMPORT_ERROR
        return

    from app.ui import run_app

    run_app()


if __name__ == "__main__":
    main()
