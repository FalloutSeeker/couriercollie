from couriercollie import backend

# Whether a project is also installed from the package manager's repositories (or Flathub) is asked of this computer's
# real package manager; the tests don't ask it (tests of that ask stand-ins, in test_assets.py).
backend._managed_elsewhere = lambda repo_ids: ""
