from couriercollie import backend, checker

# Whether a project is also installed from the package manager's repositories (or Flathub) is asked of this computer's
# real package manager; the tests don't ask it (tests of that ask stand-ins, in test_assets.py).
backend._managed_elsewhere = lambda repo_ids: ("", "", "")
find_managed = checker.find_managed  # the real one, for its own test
checker.find_managed = lambda repos: {}
