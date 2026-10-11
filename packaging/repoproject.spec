# RepoProject's own RPM. Built from a git snapshot by devtools/build_rpm.sh.
Name:           repoproject
Version:        %{app_version}
Release:        1%{?dist}
Summary:        Keep track of software from GitHub and GitLab, and update it
License:        LicenseRef-Not-Yet-Chosen
URL:            https://github.com/FalloutSeeker/RepoProject
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3
BuildRequires:  desktop-file-utils
# Where Python modules go, also without Fedora's Python macros (python3-rpm-macros) installed.
%{!?python3_sitelib: %global python3_sitelib %(python3 -c "import sysconfig; print(sysconfig.get_path('purelib', vars={'base': '/usr'}))")}

Requires:       python3
Requires:       python3-pyside6
Requires:       kf6-kirigami
# KDE's look for the window's controls; without it, Qt's Fusion is used.
Recommends:     kf6-qqc2-desktop-style
# Fills in icons the desktop's theme lacks (e.g. on GNOME).
Requires:       breeze-icon-theme
# Notifications, git clones, updates that need your password, and the GitHub sign-in's keyring.
Requires:       libnotify
Requires:       git-core
Requires:       polkit
Requires:       libsecret

%description
A desktop app that keeps track of software you got straight from GitHub or GitLab: git clones, AppImages, programs
from release archives, and RPMs installed from downloaded files. It checks for new versions on a schedule, and
updates them with a click.

%prep
%autosetup

%build

%install
install -d %{buildroot}%{python3_sitelib}
cp -a repoproject %{buildroot}%{python3_sitelib}/
find %{buildroot}%{python3_sitelib}/repoproject -name __pycache__ -prune -exec rm -rf {} +
install -Dm755 /dev/stdin %{buildroot}%{_bindir}/repoproject <<'LAUNCHER'
#!/bin/sh
# -I: only the installed app, never a "repoproject" folder in the current one.
exec /usr/bin/python3 -I -m repoproject "$@"
LAUNCHER
install -Dm644 data/repoproject.desktop %{buildroot}%{_datadir}/applications/repoproject.desktop
install -Dm644 data/repoproject.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/repoproject.svg

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/repoproject.desktop

%files
%doc README.md
%{_bindir}/repoproject
%{python3_sitelib}/repoproject/
%{_datadir}/applications/repoproject.desktop
%{_datadir}/icons/hicolor/scalable/apps/repoproject.svg

%changelog
* Sun Oct 11 2026 RepoProject - %{app_version}-1
- Snapshot build
