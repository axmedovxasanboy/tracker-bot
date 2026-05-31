"""Launcher:  python run.py"""
import logging

from bot.main import main

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        pass
