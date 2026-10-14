# couriercollie's own RPM, for Fedora and openSUSE. Built from a git snapshot by devtools/build_rpm.sh (here) or
# devtools/build_package.sh (in a container).
Name:           couriercollie
Version:        %{app_version}
Release:        1%{?dist}
Summary:        Keep track of software from GitHub and GitLab, and update it
# The app, and the Breeze icons it brings along (couriercollie/icons/COPYING-ICONS).
License:        GPL-3.0-or-later AND LGPL-3.0-or-later
URL:            https://github.com/FalloutSeeker/couriercollie
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3
BuildRequires:  desktop-file-utils
# Where Python modules go, also without Fedora's Python macros (python3-rpm-macros) installed.
%{!?python3_sitelib: %global python3_sitelib %(python3 -c "import sysconfig; print(sysconfig.get_path('purelib', vars={'base': '/usr'}))")}

# The window: PySide6 and Kirigami (KDE's toolkit, a Qt library: not the rest of KDE). The icons come with the app.
Requires:       python3
Requires:       python3-pyside6
# KDE's look for the window's controls; without it, Qt's Fusion is used.
Recommends:     kf6-qqc2-desktop-style
# Git clones, and updates that need your password.
Requires:       git-core
Requires:       polkit
# Package names differ between Fedora and openSUSE for these: Kirigami's QML parts, notify-send, and secret-tool
# (which keeps the GitHub sign-in in the desktop's password store).
%if 0%{?suse_version}
Requires:       kf6-kirigami-imports
Requires:       libnotify-tools
Requires:       secret-tool
%else
Requires:       kf6-kirigami
Requires:       libnotify
Requires:       libsecret
%endif

%description
A desktop app that keeps track of software you got straight from GitHub or GitLab: git clones, AppImages, programs
from release archives, packages installed from downloaded files and Flatpak bundles. It checks for new versions on a
schedule, and updates them with a click.

%prep
%autosetup

%build

%install
install -d %{buildroot}%{python3_sitelib}
cp -a couriercollie %{buildroot}%{python3_sitelib}/
find %{buildroot}%{python3_sitelib}/couriercollie -name __pycache__ -prune -exec rm -rf {} +
install -Dm755 data/couriercollie %{buildroot}%{_bindir}/couriercollie
install -Dm644 data/couriercollie.desktop %{buildroot}%{_datadir}/applications/couriercollie.desktop
install -d %{buildroot}%{_datadir}/icons
cp -a data/icons/hicolor %{buildroot}%{_datadir}/icons/

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/couriercollie.desktop

%files
%license LICENSE
%doc README.md
%{_bindir}/couriercollie
%{python3_sitelib}/couriercollie/
%{_datadir}/applications/couriercollie.desktop
%{_datadir}/icons/hicolor/*/apps/couriercollie.png

%changelog
* Sun Oct 11 2026 couriercollie - %{app_version}-1
- Snapshot build
