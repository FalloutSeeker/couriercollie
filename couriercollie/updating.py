"""Updating what's tracked: the Update and Install buttons, and install scripts. Part of the Backend
(backend.py), kept apart so each file stays readable; the work itself is in updater.py.

Uses the Backend's settings (`_config`), page data (`_details`), check results (`_checks`), worker thread (`_run`)
and signals.
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Slot

from . import applying, assets, checker, config, flatpaks, icons, integration, packages, sources, updater
from .config import FOLLOW_BRANCH, FOLLOW_RELEASES, NOT_INSTALLED, TrackedRepo
from .sources import RepoRef

# The last lines of a step's output kept to show: enough to see how it ended.
STEP_OUTPUT_LINES = 300


@dataclass
class StepRun:
    """A run of a clone's step after an update (applying.run), while the app is open."""
    version: str  # the clone's version it applies
    running: bool = True
    stopped: bool = False
    output: list[str] = field(default_factory=list)
    result: str = ""  # "applied", "failed", "password" (it asked for one), "stopped"
    code: int = 0
    process: object = None

if TYPE_CHECKING:
    from .backend import Details


def _newest_version(repo: TrackedRepo, d: Details) -> str:
    """The newest version of what the repo follows: the newest release (a test version too, if they're shown), or
    the latest commit on the branch."""
    if repo.follow == FOLLOW_BRANCH:
        return _head(repo, d)
    release = _newest_release(repo.prereleases, d.releases)
    return release.tag if release else ""


def _newest_release(prereleases: bool, releases: list):
    """The release Update installs: the newest, leaving out test versions unless they're shown (as the check and the
    page do). None if there's none."""
    return next((r for r in releases if prereleases or not r.prerelease), None)


def _head(repo: TrackedRepo, d: Details) -> str:
    """The newest commit on the branch the repo follows, or "" if it isn't known."""
    return next((b.sha for b in d.branches if b.name == (repo.branch or d.default_branch)), "")


def _is_clone(repo: TrackedRepo) -> bool:
    """A git clone on this computer: found by a scan, or made by Install."""
    return repo.source == config.SOURCE_SCANNED and repo.kind == assets.KIND_GIT and bool(repo.local_path)


def _is_appimage(repo: TrackedRepo) -> bool:
    """Following an AppImage file in each release."""
    return repo.follow == FOLLOW_RELEASES and repo.kind == assets.KIND_APPIMAGE and bool(repo.asset_pattern)


def _is_program(repo: TrackedRepo) -> bool:
    """Following a release archive with a ready-made program inside."""
    return repo.follow == FOLLOW_RELEASES and repo.kind == assets.KIND_PROGRAM and bool(repo.asset_pattern)


def _is_package(repo: TrackedRepo) -> bool:
    """Following a package in each release (an .rpm, .deb or Arch package), installed with the package manager."""
    return repo.follow == FOLLOW_RELEASES and repo.kind in packages.LABELS and bool(repo.asset_pattern)


def _is_flatpak(repo: TrackedRepo) -> bool:
    """Following a Flatpak bundle in each release, installed for you (not one installed for all users: flatpaks.py)."""
    return (repo.follow == FOLLOW_RELEASES and repo.kind == assets.KIND_FLATPAK and bool(repo.asset_pattern)
            and flatpaks.from_place(repo.local_path)[1] != "system")


def _new_copy(repo: TrackedRepo) -> bool:
    """An AppImage or program you have, added by hand: where your copy is isn't known, so Install puts a new one in
    place (and updates that from then on) rather than replacing yours. A package is different: the package manager
    finds and replaces it."""
    return ((_is_appimage(repo) or _is_program(repo)) and repo.source != config.SOURCE_SCANNED
            and repo.installed not in ("", NOT_INSTALLED))


def _package_name(repo: TrackedRepo) -> str:
    """The name of the package you have, once it's on this computer: its place reads 'RPM package “name”'."""
    found = packages.from_place(repo.local_path) if repo.source == config.SOURCE_SCANNED else None
    return found[1] if found else ""


def _can_clone(repo: TrackedRepo) -> bool:
    """A project added by hand that you don't have yet, following a branch, or with releases of source code only:
    Install clones it (updater.clone), at the branch or the newest release's tag. Never a project built only for
    other systems (repo.other_systems), whatever is followed: an Android app's source is no use here. Nor what the
    package manager or Flatpak installed (repo.managed_by): that's already here."""
    return (repo.source != config.SOURCE_SCANNED and repo.installed == NOT_INSTALLED and not repo.other_systems
            and not repo.managed_by
            and (repo.follow == FOLLOW_BRANCH or repo.kind == assets.KIND_VERSIONS))


def _can_update(repo: TrackedRepo) -> bool:
    """Whether Update (or Install) can do anything for this repo: a git clone found by a scan (pulled, or moved to
    the newest release's tag), a release's AppImage, program archive or package (downloaded, checked and put in
    place), or a project to clone. Never for what the package manager or Flatpak installed (repo.managed_by): they
    keep it up to date, and two updaters would fight over the same files."""
    if repo.managed_by:
        return False
    if _is_clone(repo) and updater.someone_elses(repo.local_path):
        return False  # another person's clone: its updates are theirs (shown only)
    return (_is_clone(repo) or _is_appimage(repo) or _is_program(repo) or _is_package(repo) or _is_flatpak(repo)
            or _can_clone(repo))


def _needs_password(repo: TrackedRepo) -> bool:
    """Whether Update asks for your password: the package manager installs a package for the whole system; a clone
    may belong to it."""
    return _is_package(repo) or (_is_clone(repo) and updater.needs_password(repo.local_path))


class Updating:
    """The Backend's updating slots (a mixin: PySide6 makes these slots of the Backend)."""

    def _init_updates(self):
        # Updates running now, and how the last one for each repo went: (kind, text), kind "done", "warning" or
        # "error".
        self._updating: set[str] = set()
        self._update_notes: dict[str, tuple[str, str]] = {}
        self._progress: dict[str, float] = {}  # a download's progress, 0 to 1, per repo
        self._steps: dict[str, StepRun] = {}  # each clone's last step run after an update, while the app is open
        self._program_choices: dict[str, list[str]] = {}  # programs to choose from, when an archive has several
        self._phases: dict[str, str] = {}  # "installing" once an RPM's download is done and dnf runs
        # How many updates (or steps) have finished for each repo, while the app is open: a page or a scan that read
        # the disk before one finished has read it as it was before (loadDetails, _scan_done).
        self._finished: dict[str, int] = {}
        self._load_after: set[str] = set()  # pages to load again once their update is done
        self._approved: dict[str, tuple] = {}  # whether each step is still as approved, for the page
        self._reviewed: dict[tuple[str, str], str] = {}  # each step as the window last showed it (reviewStep)

    def _here_now(self, repo_id: str):
        """Updated or installed: it's on this computer now, whatever the page found before ("Not found")."""
        if d := self._details.get(repo_id):
            d.local_missing = False

    def _done_updating(self, repo_id: str):
        """An update (or its step) for this repo is over."""
        self._updating.discard(repo_id)
        self._finished[repo_id] = self._finished.get(repo_id, 0) + 1
        if repo_id in self._load_after:
            self._load_after.discard(repo_id)
            QTimer.singleShot(0, lambda: self.loadDetails(repo_id, True))  # (once the update has set what it did)

    @Slot(str)
    def updateRepo(self, repo_id):
        """Update (or Install) clicked: a clone is pulled or moved to the newest release (updater.pull,
        checkout_release); anything else is downloaded (_update_download)."""
        repo = self._config.find(repo_id)
        if not repo or repo_id in self._updating or not _can_update(repo) or self._part_of(repo):
            return
        if self._asks_first(repo):
            self.askStep.emit(repo_id, "update")  # the first time: what runs after it downloads (updateWithStep)
            return
        if _can_clone(repo):
            self._install_clone(repo)
            return
        if not _is_clone(repo):
            self._update_download(repo)
            return
        d = self._details.get(repo_id)
        branch = repo.branch or (d.default_branch if d else "")
        path, ids, by_branch = repo.local_path, [repo.id, *repo.aliases], repo.follow == FOLLOW_BRANCH
        # The release to move to: the newest the page or the last check knows of.
        result = self._checks.results.get(repo_id)
        tag = (_newest_version(repo, d) if d and d.state == "ready" else "") or (result.newest if result else "")
        if not by_branch and not tag:
            self._update_notes[repo_id] = ("error", "The newest release isn\u2019t known yet: Refresh, then try "
                                                    "again.")
            self.detailsChanged.emit(repo_id)
            return
        self._updating.add(repo_id)
        self._update_notes.pop(repo_id, None)
        self.reposChanged.emit()
        self.detailsChanged.emit(repo_id)

        def done(result, error):
            self._done_updating(repo_id)
            repo = self._config.find(repo_id)
            if repo and error:
                self._update_notes[repo_id] = ("error", self._error_text(error))
            elif repo and by_branch:
                self._here_now(repo_id)
                _before, after, count = result
                self._pulled(repo, branch, after)
                self._update_notes[repo_id] = ("done", "Already up to date." if not count else "Pulled 1 new commit."
                                               if count == 1 else f"Pulled {count} new commits.")
                if count:
                    self._updated_here(repo)
            elif repo:
                self._here_now(repo_id)
                _before, left = result
                repo.installed = tag
                self._version_changed(repo)
                self._changed(repo_id)
                back = f" Your branch {left} is unchanged; git switch {left} goes back to it." if left else ""
                self._update_notes[repo_id] = ("done", f"Now at {tag}.{back}")
                self._updated_here(repo)
            self.reposChanged.emit()
            self.detailsChanged.emit(repo_id)
            if repo and error:
                self.updateFailed.emit(repo_id)

        self._run(lambda: updater.pull(path, branch, ids) if by_branch else updater.checkout_release(path, tag, ids),
                  done)

    def _install_clone(self, repo: TrackedRepo):
        """Install, for a project you don't have that's followed by branch or version: cloned into ~/src, after which
        it's a clone like one a scan found (its version read from disk, Update pulls it)."""
        repo_id, d = repo.id, self._details.get(repo.id)
        by_branch = repo.follow == FOLLOW_BRANCH
        ready = d is not None and d.state == "ready"
        ref = (repo.branch or (d.default_branch if d else "")) if by_branch else (_newest_version(repo, d) if ready
                                                                                   else "")
        if not ref:
            self._update_notes[repo_id] = ("error", "What to clone isn\u2019t known yet: Refresh, then try again.")
            self.detailsChanged.emit(repo_id)
            return
        project = RepoRef.from_id(repo_id)
        self._updating.add(repo_id)
        self._update_notes.pop(repo_id, None)
        self.reposChanged.emit()
        self.detailsChanged.emit(repo_id)

        def work():
            folder = updater.clone(project.git_url, ref, project.name)
            return folder, updater.git_out(str(folder), "rev-parse", "HEAD"), updater.install_scripts(str(folder))

        def done(result, error):
            self._done_updating(repo_id)
            repo = self._config.find(repo_id)
            if repo and error:
                self._update_notes[repo_id] = ("error", self._error_text(error))
            elif repo:
                self._here_now(repo_id)
                folder, head, scripts = result
                # From now on it's a clone like one a scan found.
                repo.source, repo.local_path, repo.kind, repo.asset_pattern = \
                    config.SOURCE_SCANNED, str(folder), assets.KIND_GIT, ""
                if d := self._details.get(repo_id):
                    d.install_scripts, d.branch_on_disk = scripts, ref if by_branch else ""
                if by_branch:
                    self._pulled(repo, ref, head)
                else:
                    repo.installed = ref
                self._version_changed(repo)
                self._changed(repo_id)
                where = updater.shown(folder)
                what = f"Cloned {ref} into {where}." if by_branch else f"Cloned {project.name} at {ref} into {where}."
                self._update_notes[repo_id] = ("done", what)
            self.reposChanged.emit()
            self.detailsChanged.emit(repo_id)
            if repo and error:
                self.updateFailed.emit(repo_id)
            elif repo and self._asks_first(repo):
                self.askStep.emit(repo_id, "installed")  # cloned: what installs it, now and after each update

        self._run(work, done)

    def _update_download(self, repo: TrackedRepo):
        """Download the newest release's file, check it, and put it in place: an AppImage (into ~/Applications, with a
        menu entry, if you don't have it yet), a program from an archive (its own folder, with a link in
        ~/.local/bin), a package (the package manager) or a Flatpak bundle (for you). See updater.py."""
        repo_id, d = repo.id, self._details.get(repo.id)
        is_program, is_package, package, kind = _is_program(repo), _is_package(repo), _package_name(repo), repo.kind
        is_flatpak, app_id = _is_flatpak(repo), flatpaks.from_place(repo.local_path)[0]
        here_link = Path(repo.local_path) if is_program and repo.local_path else None
        wanted = repo.program or (here_link.name if here_link and here_link.is_symlink() else "")
        hints = [RepoRef.from_id(repo.id).name, repo.name, repo.asset_pattern.split("-")[0].split("*")[0]]
        ref, host, pattern, name, icon = RepoRef.from_id(repo.id), repo.host, repo.asset_pattern, repo.name, repo.icon
        known = d.releases if d and d.state == "ready" else None
        prereleases = repo.prereleases
        here = Path(repo.local_path) if repo.source == config.SOURCE_SCANNED and repo.local_path else None
        old = here if here and here.is_file() and not (is_program or is_package or is_flatpak) else None
        folder = old.parent if old else updater.apps_dir()
        self._updating.add(repo_id)
        self._update_notes.pop(repo_id, None)
        self._program_choices.pop(repo_id, None)
        self._progress[repo_id] = 0
        self.reposChanged.emit()
        self.detailsChanged.emit(repo_id)
        shown = {"step": -1}

        def progress(done, total):
            step = int(done * 100 / total) if total else -1
            if step != shown["step"]:  # at most a hundred times a download
                shown["step"] = step
                self._deliver.emit(lambda: (self._progress.__setitem__(repo_id, step / 100 if step >= 0 else -1),
                                            self.detailsChanged.emit(repo_id)))

        def work():
            """Returns (the release's tag, where it now is, whether it was checked against a published checksum,
            what was done, in a sentence)."""
            rels = known if known is not None else sources.releases(ref, host)
            release = _newest_release(prereleases, rels)
            if not release:
                raise updater.UpdateError("Only test versions so far: tick \u201cInclude & Update from test versions\u201d to install one."
                                          if rels else "This project has no releases to install.")
            chosen = assets.pick(pattern, [a.name for a in release.assets])
            asset = next((a for a in release.assets if a.name == chosen), None)
            if not asset:
                raise updater.UpdateError(f"The newest release ({release.tag}) doesn\u2019t include your file "
                                          f"({pattern}). Choose it again under Your Build File.")
            tag = release.tag
            if is_package:
                def installing():
                    self._deliver.emit(lambda: (self._phases.__setitem__(repo_id, "installing"),
                                                self.detailsChanged.emit(repo_id)))

                found, _version, verified, tool = updater.install_package(asset, release.assets, kind, package,
                                                                          progress, installing)
                return tag, packages.place(kind, found), verified, (
                    f"Updated to {tag} with {tool}." if package else
                    f"Installed {tag} with {tool} (package \u201c{found}\u201d).")
            if is_flatpak:
                found, verified = updater.install_flatpak(asset, release.assets, app_id, progress)
                return tag, flatpaks.place(found), verified, (
                    f"Updated to {tag}." if app_id else f"Installed {tag} with Flatpak, for you (\u201c{found}\u201d).")
            if is_program:
                link, verified, replaced = updater.install_program(repo_id, tag, asset, release.assets, wanted,
                                                                    hints, progress)
                on_path = str(updater.bin_dir()) in os.environ.get("PATH", "").split(os.pathsep)
                run = f" Run it as \u201c{link.name}\u201d." if on_path else \
                    f" Run it as {updater.shown(link)} ({updater.shown(updater.bin_dir())} isn\u2019t where your " \
                    "terminal looks for commands)."
                return tag, str(link), verified, (f"Updated to {tag}." if replaced else f"Installed {tag}.") + run
            new, verified = updater.install_appimage(asset, release.assets, folder, old, progress)
            if old:
                updater.repoint_menu_entries(old, new)
            if not updater.menu_entry_for(new):
                found = icons.from_appimage(repo_id, new)
                updater.write_menu_entry(repo_id, name, new, found.removeprefix("file:") if found
                                         else icon.removeprefix("theme:") if icon.startswith("theme:") else "")
            return tag, str(new), verified, (
                f"Updated to {tag}." if old else f"Installed {tag} as {updater.shown(new)}, with a menu entry.")

        def done(result, error):
            self._done_updating(repo_id)
            self._progress.pop(repo_id, None)
            self._phases.pop(repo_id, None)
            repo = self._config.find(repo_id)
            if repo and error:
                self._update_notes[repo_id] = ("error", self._error_text(error))
                if isinstance(error, updater.SeveralPrograms):
                    self._program_choices[repo_id] = error.choices
            elif repo:
                self._here_now(repo_id)
                tag, where, verified, what = result
                # From now on its version is read from where it is, like one a scan found.
                repo.source, repo.local_path, repo.installed = config.SOURCE_SCANNED, where, tag
                self._version_changed(repo)
                self._changed(repo_id)
                check = " Checked against the project\u2019s published checksum." if verified else \
                    " The project publishes no checksum for it, so the download couldn\u2019t be checked."
                self._update_notes[repo_id] = ("done" if verified else "warning", what + check)
            self.reposChanged.emit()
            self.detailsChanged.emit(repo_id)
            if repo and error:
                self.updateFailed.emit(repo_id)

        self._run(work, done)

    def _updated_here(self, repo: TrackedRepo):
        """The clone was just updated here. A running program doesn't use the new files yet: its approved step runs
        now, finishing the job. If the update changed what it runs, the page asks first."""
        self._steps.pop(repo.id, None)  # the last run was for the version before: it says nothing about this one
        if d := self._details.get(repo.id):  # what it could run, as the update left it
            d.install_scripts, d.builds = updater.install_scripts(repo.local_path), applying.builds(repo.local_path)
        self._changed(repo.id)
        if repo.apply_command and (gone := applying.missing(repo.local_path, repo.apply_command)):
            # Removed or renamed by the update: nothing to run, and nothing to look at again.
            _kind, text = self._update_notes.get(repo.id, ("done", ""))
            name = gone[0].removeprefix("./")
            self._update_notes[repo.id] = ("warning", f"{text} {name} is no longer in the clone, so nothing ran "
                                                      "after the download.".strip())
            self.detailsChanged.emit(repo.id)
        elif repo.apply_command and self._step_still_approved(repo):
            self.runStep(repo.id)
        elif repo.apply_command:
            self.askStep.emit(repo.id, "changed")

    def _step_still_approved(self, repo: TrackedRepo, fresh: bool = True) -> bool:
        """Whether the step and the scripts it runs are as approved. Before it runs, always worked out afresh; for the
        page (asked on each redraw, and it reads files and asks git), once, then again after an update, a Refresh, or
        this being worked out afresh."""
        key = (repo.local_path, repo.apply_command, repo.apply_approved)
        if not fresh and (known := self._approved.get(repo.id)) and known[0] == key:
            return known[1]
        ok = applying.fingerprint(repo.local_path, repo.apply_command) == repo.apply_approved
        self._approved[repo.id] = (key, ok)
        return ok

    def _asks_first(self, repo: TrackedRepo) -> bool:
        """Whether Update first asks what runs after it downloads: a clone, with something to run, and neither a
        step approved nor Only Download chosen."""
        return (_is_clone(repo) and not repo.apply_command and not repo.apply_skip
                and bool(self._step_choices(repo, self._details.get(repo.id))))

    def _pulled(self, repo: TrackedRepo, branch: str, head: str):
        """After a pull, the clone is at the branch's newest commit (as just fetched): your version, the page and the
        list's result all say so, without asking the site."""
        if d := self._details.get(repo.id):
            for b in d.branches:
                if b.name == branch:
                    b.sha = head
            d.comparison, d.commits_base, d.commits_head = sources.Comparison(sources.SAME), head, head
        if (old := self._checks.results.get(repo.id)) and old.status in (checker.UPDATE, checker.UP_TO_DATE):
            self._checks.results[repo.id] = dataclasses.replace(old, status=checker.UP_TO_DATE, text="Up to date",
                                                                newest=head, not_rechecked=False)
            self._save_checks()
        if head and head != repo.installed:
            repo.installed = head
            self._changed(repo.id)

    @Slot(str, str)
    def chooseProgram(self, repo_id, name):
        """Which program in a release's archive to run, when it has several."""
        if (repo := self._config.find(repo_id)) and name in self._program_choices.get(repo_id, [name]):
            repo.program = name
            self._program_choices.pop(repo_id, None)
            self._update_notes.pop(repo_id, None)
            self._changed(repo_id)

    # -- the step after an update (applying.py) -----------------------------------------------------------------

    @Slot(str, str, result=str)
    def reviewStep(self, repo_id, command):
        """The command and the files it names, to read before approving it."""
        repo = self._config.find(repo_id)
        if not repo or not _is_clone(repo):
            return ""
        # What's shown is what approving approves: changed after, it's asked about again before it runs. (And the
        # commit it's at, so a change after can be shown as what changed.)
        command = command.strip()
        self._reviewed[(repo_id, command)] = (applying.fingerprint(repo.local_path, command),
                                              updater.git_out(repo.local_path, "rev-parse", "HEAD"))
        since = repo.apply_commit if command == repo.apply_command else ""
        return applying.review_text(repo.local_path, command, since)

    @Slot(str, str, result=str)
    def stepBlocked(self, repo_id, command):
        """Why this step can't be approved here (it couldn't be shown whole), or ""."""
        repo = self._config.find(repo_id)
        if not repo or not _is_clone(repo) or not command.strip():
            return ""
        return applying.unapprovable(repo.local_path, command.strip())

    @Slot(str, result=str)
    def stepChanges(self, repo_id):
        """The files that changed in the approved step since it was approved ("lib/common.sh, install.sh"), or ""."""
        repo = self._config.find(repo_id)
        if not repo or not _is_clone(repo) or not repo.apply_command:
            return ""
        names, _diff = applying.changes(repo.local_path, repo.apply_command, repo.apply_commit)
        names = [applying._shown(n) for n in names]  # (what can't be seen, shown as its code)
        return ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")

    @Slot(str, result="QVariantMap")
    def readmeSteps(self, repo_id):
        """The README's own steps for updating (or installing), to read beside the step: never run."""
        repo = self._config.find(repo_id)
        if not repo or not _is_clone(repo):
            return {"heading": "", "text": ""}
        heading, text = applying.readme_section(repo.local_path)
        return {"heading": heading, "text": text}

    @Slot(str, str)
    def approveStep(self, repo_id, command):
        """Run this after each update, as it is now: what it names is remembered, so a change is noticed. Only one
        of the choices (_step_choices): nothing typed in."""
        repo = self._config.find(repo_id)
        if not repo or not _is_clone(repo) or not (command := command.strip()) \
                or command not in (c["command"] for c in self._step_choices(repo, self._details.get(repo_id))):
            return
        # As the window showed it (reviewStep): never what wasn't shown, nor what couldn't be shown whole.
        if (shown := self._reviewed.pop((repo_id, command), None)) is None \
                or applying.unapprovable(repo.local_path, command):
            return
        repo.apply_command, (repo.apply_approved, repo.apply_commit) = command, shown
        repo.apply_skip = False
        self._changed(repo_id)

    @Slot(str)
    def skipStep(self, repo_id):
        """Only Download: Update only downloads, and doesn't ask again."""
        if repo := self._config.find(repo_id):
            repo.apply_command, repo.apply_approved, repo.apply_commit, repo.apply_skip = "", "", "", True
            self._steps.pop(repo_id, None)
            self._changed(repo_id)

    @Slot(str, str)
    def updateWithStep(self, repo_id, command):
        """Update, the first time (the page asked): download, then run this, now and after each update."""
        self.approveStep(repo_id, command)
        self.updateRepo(repo_id)

    @Slot(str)
    def updateOnly(self, repo_id):
        """Update, the first time, choosing Only Download."""
        self.skipStep(repo_id)
        self.updateRepo(repo_id)

    @Slot(str)
    def runStep(self, repo_id):
        """Run the approved step now, in the clone's folder, its output shown on the page. Only as approved."""
        repo = self._config.find(repo_id)
        if not repo or not repo.apply_command or repo_id in self._updating or not _is_clone(repo):
            return
        if applying.missing(repo.local_path, repo.apply_command) or not self._step_still_approved(repo):
            self.detailsChanged.emit(repo_id)  # the page asks for it to be looked at again (or says it's gone)
            return
        # sudo in the step asks for the password in the desktop's own window (couriercollie never sees it). Without
        # one (it couldn't be set up), sudo stops, and the page offers the command for a terminal.
        try:
            asking = applying.password_window(integration.runtime_dir() / "sudo")
        except OSError:
            asking = {}
        run = self._steps[repo_id] = StepRun(version=repo.installed)
        self._updating.add(repo_id)
        self.reposChanged.emit()
        self.detailsChanged.emit(repo_id)
        path, command = repo.local_path, repo.apply_command

        def line(text):
            def add():
                run.output.append(text)
                del run.output[:-STEP_OUTPUT_LINES]
                self.detailsChanged.emit(repo_id)
            self._deliver.emit(add)

        def started(process):
            run.process = process

        def done(code, error):
            self._done_updating(repo_id)
            run.process, run.running = None, False
            if error:
                run.result, run.output = "failed", [*run.output, str(error)]
            elif run.stopped:
                run.result = "stopped"
            elif code == 0:
                run.result = "applied"
            else:
                run.result, run.code = ("password" if applying.asked_for_password(run.output) else "failed"), code
            self.reposChanged.emit()
            self.detailsChanged.emit(repo_id)

        self._run(lambda: applying.run(path, command, line, started, asking), done)

    @Slot(str)
    def stopStep(self, repo_id):
        if (run := self._steps.get(repo_id)) and run.process:
            run.stopped = True
            applying.stop(run.process)
