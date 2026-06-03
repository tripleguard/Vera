"""Run all tests in this directory. Usage: python tests/run_all.py"""
import os
import sys
import unittest


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    # Make `tests` importable so unittest can import test_*.py as modules.
    if here not in sys.path:
        sys.path.insert(0, here)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in sorted(os.listdir(here)):
        if name.startswith("test_") and name.endswith(".py"):
            modname = name[:-3]
            try:
                suite.addTests(loader.loadTestsFromName(modname))
            except Exception as e:
                print(f"Failed to load {modname}: {e}")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
