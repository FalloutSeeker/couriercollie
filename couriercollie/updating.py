"""Updating what's tracked (stage 5): the Update and Install buttons, and install scripts. Part of the Backend
(backend.py), kept apart so each file stays readable; the work itself is in updater.py.

Uses the Backend's settings (`_config`), page data (`_details`), check results (`_checks`), worker thread (`_run`)
and signals.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QProcess, Slot

from . import assets, checker, config, flatpaks, icons, packages, sources, updater
from .config import FOLLOW_BRANCH, FOLLOW_RELEASES, NOT_INSTALLED, TrackedRepo
from .sources import RepoRef

if TYPE_CHECKING:
    from .backend import Details


def _newest_version(repo: TrackedRepo, d: Details) -> str:
    """The newest version of what the repo follows: the newest full release, or the latest commit on the branch."""
    if repo.follow == FOLLOW_BRANCH:
        return _head(repo, d)
    release = next((r for r in d.releases if not r.prerelease), d.releases[0] if d.releases else None)
    return release.tag if release else ""


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


def _package_name(repo: TrackedRepo) -> str:
    """The name of the package you have, once it's on this computer: its place reads 'RPM package “name”'."""
    found = packages.from_place(repo.local_path) if repo.source == config.SOURCE_SCANNED else None
    return found[1] if found else ""


def _can_clone(repo: TrackedRepo) -> bool:
    """A project added by hand that you don't have yet, following a branch, or releases with nothing to download for
    this computer: Install clones it (updater.clone), at the branch or the newest release's tag."""
    return (repo.source != config.SOURCE_SCANNED and repo.installed == NOT_INSTALLED
            and (repo.follow == FOLLOW_BRANCH or repo.kind == assets.KIND_VERSIONS))


def _can_update(repo: TrackedRepo) -> bool:
    """Whether Update (or Install) can do anything for this repo: a git clone found by a scan (pulled, or moved to
    the newest release's tag), a release's AppImage, program archive or package (downloaded, checked and put in
    place), or a project to clone."""
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
        self._program_choices: dict[str, list[str]] = {}  # programs to choose from, when an archive has several
        self._phases: dict[str, str] = {}  # "installing" once an RPM's download is done and dnf runs

    @Slot(str)
    def updateRepo(self, repo_id):
        """Update (or Install) clicked: a clone is pulled or moved to the newest release (updater.pull,
        checkout_release); anything else is downloaded (_update_download)."""
        repo = self._config.find(repo_id)
        if not repo or repo_id in self._updating or not _can_update(repo):
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
            self._updating.discard(repo_id)
            repo = self._config.find(repo_id)
            scripts = " If the project needs installing again, run its install script (under Tracking)." \
                if (d := self._details.get(repo_id)) and d.install_scripts else ""
            if repo and error:
                self._update_notes[repo_id] = ("error", self._error_text(error))
            elif repo and by_branch:
                _before, after, count = result
                self._pulled(repo, branch, after)
                self._update_notes[repo_id] = ("done", ("Already up to date." if not count else "Pulled 1 new commit."
                                                        if count == 1 else f"Pulled {count} new commits.") + scripts)
            elif repo:
                _before, left = result
                repo.installed = tag
                self._version_changed(repo)
                self._changed(repo_id)
                back = f" Your branch {left} is unchanged; git switch {left} goes back to it." if left else ""
                self._update_notes[repo_id] = ("done", f"Now at {tag}.{back}{scripts}")
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
            self._updating.discard(repo_id)
            repo = self._config.find(repo_id)
            if repo and error:
                self._update_notes[repo_id] = ("error", self._error_text(error))
            elif repo:
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
                self._update_notes[repo_id] = ("done", what + (" To install it, run its install script (under "
                                                               "Tracking)." if scripts else ""))
            self.reposChanged.emit()
            self.detailsChanged.emit(repo_id)
            if repo and error:
                self.updateFailed.emit(repo_id)

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
            release = next((r for r in rels if not r.prerelease), rels[0] if rels else None)
            if not release:
                raise updater.UpdateError("This project has no releases to install.")
            asset = next((a for a in release.assets if assets.matches(pattern, a.name)), None)
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
            self._updating.discard(repo_id)
            self._progress.pop(repo_id, None)
            self._phases.pop(repo_id, None)
            repo = self._config.find(repo_id)
            if repo and error:
                self._update_notes[repo_id] = ("error", self._error_text(error))
                if isinstance(error, updater.SeveralPrograms):
                    self._program_choices[repo_id] = error.choices
            elif repo:
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

    @Slot(str, str, result=str)
    def scriptText(self, repo_id, name):
        """An install script's text, to read before running it; or why it can't be shown."""
        repo = self._config.find(repo_id)
        try:
            return updater.script_text(repo.local_path if repo else "", name)
        except (updater.UpdateError, OSError) as e:
            return f"# {e}"

    @Slot(str, str, result=str)
    def runInstallScript(self, repo_id, name):
        """Run an install script in a terminal window, from the clone's folder. Only ever from a click, after the
        script was shown (DECISIONS.md, D6). Returns why it couldn't start, or ""."""
        repo = self._config.find(repo_id)
        if not repo or not _can_update(repo):
            return "This repo has no clone on this computer to run a script in."
        try:
            program, args = updater.terminal_command(repo.local_path, name)
        except updater.UpdateError as e:
            return str(e)
        started, _pid = QProcess.startDetached(program, args, repo.local_path)
        if not started:
            return f"Couldn\u2019t open {Path(program).name}."
        if repo.script_run_at != repo.installed:
            repo.script_run_at = repo.installed
            self._changed(repo_id)
        return ""
