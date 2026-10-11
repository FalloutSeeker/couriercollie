# couriercollie's own RPM. Built from a git snapshot by devtools/build_rpm.sh.
Name:           couriercollie
Version:        %{app_version}
Release:        1%{?dist}
Summary:        Keep track of software from GitHub and GitLab, and update it
License:        LicenseRef-Not-Yet-Chosen
URL:            https://github.com/FalloutSeeker/couriercollie
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
cp -a couriercollie %{buildroot}%{python3_sitelib}/
find %{buildroot}%{python3_sitelib}/couriercollie -name __pycache__ -prune -exec rm -rf {} +
install -Dm755 data/couriercollie %{buildroot}%{_bindir}/couriercollie
install -Dm644 data/couriercollie.desktop %{buildroot}%{_datadir}/applications/couriercollie.desktop
install -Dm644 data/couriercollie.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/couriercollie.svg

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/couriercollie.desktop

%files
%doc README.md
%{_bindir}/couriercollie
%{python3_sitelib}/couriercollie/
%{_datadir}/applications/couriercollie.desktop
%{_datadir}/icons/hicolor/scalable/apps/couriercollie.svg

%changelog
* Sun Oct 11 2026 couriercollie - %{app_version}-1
- Snapshot build
