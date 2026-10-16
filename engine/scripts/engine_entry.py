import multiprocessing

from claudebolt.cli import app

if __name__ == "__main__":
    multiprocessing.freeze_support()
    app()
