import tempfile
import unittest
from pathlib import Path

from couriercollie import applying


class ReadmeStepsTest(unittest.TestCase):
    """The README's update steps, quoted on a clone's page: shown, never followed."""

    def steps(self, readme, name="README.md"):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / name).write_text(readme)
            return applying.readme_steps(folder)

    def test_a_section_about_updating(self):
        readme = ("# App\n\nIntro.\n\n## Install\n\nmake install\n\n## Updating\n\nPull, then:\n\n```sh\n"
                  "# not a heading\nmake install\n```\n\n### Notes\n\nKeep your config.\n\n## License\n\nMIT\n")
        self.assertEqual(self.steps(readme), "Pull, then:\n\n```sh\n# not a heading\nmake install\n```\n\n### Notes\n\n"
                                             "Keep your config.")

    def test_a_paragraph_that_starts_to_update(self):
        readme = "# App\n\nRun it with `npm start`.\n\nTo update: the update button in the header.\nOr git pull.\n\nMore.\n"
        self.assertEqual(self.steps(readme), "To update: the update button in the header.\nOr git pull.")
        self.assertEqual(self.steps("**To upgrade**, run ./upgrade.sh.\n"), "**To upgrade**, run ./upgrade.sh.")

    def test_none(self):
        self.assertEqual(self.steps("# App\n\nIt updates your files automatically.\n"), "")  # a mention isn't steps
        self.assertEqual(self.steps("# App\n\n## Updating\n\n## License\n"), "")  # an empty section
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(applying.readme_steps(folder), "")  # no README

    def test_long_steps_are_shortened_without_leaving_code_open(self):
        steps = self.steps("## Upgrade\n\n```\n" + "step\n" * 600 + "```\n")
        self.assertLessEqual(len(steps), applying.STEPS_MAX_CHARS + 10)
        self.assertEqual(steps.count("```") % 2, 0)
        self.assertTrue(steps.endswith("…"))


class ComposeTest(unittest.TestCase):
    """Containers running from a clone's compose files, told by the labels Compose puts on them."""

    def labels(self, working_dir, service, files="/c/docker-compose.yml,/c/deploy/compose.gpu.yml"):
        return {"com.docker.compose.project": "board", "com.docker.compose.project.working_dir": working_dir,
                "com.docker.compose.project.config_files": files, "com.docker.compose.service": service}

    def test_found_with_its_files_and_running_services(self):
        with tempfile.TemporaryDirectory() as folder:
            running = {"podman": [self.labels(folder, "nginx"), self.labels(folder, "app"),
                                  self.labels("/elsewhere", "db")], "docker": []}
            c = applying.running_compose(folder, containers=lambda engine: running[engine])
            self.assertEqual((c.project, c.files, c.services),
                             ("board", ["/c/docker-compose.yml", "/c/deploy/compose.gpu.yml"], ["app", "nginx"]))
            command = applying.compose_command(c)
            # Only the running services are rebuilt, with the same files: a profile that's off stays off.
            self.assertIn("/c/deploy/compose.gpu.yml", command)
            self.assertEqual(command[command.index("up"):], ["up", "-d", "--build", "--force-recreate", "app", "nginx"])
            self.assertEqual(command[command.index("-p"):command.index("-p") + 2], ["-p", "board"])

    def test_docker_when_podman_has_none(self):
        with tempfile.TemporaryDirectory() as folder:
            running = {"podman": [], "docker": [self.labels(folder, "web")]}
            c = applying.running_compose(folder, containers=lambda engine: running[engine])
            self.assertEqual((c.tool, c.services), (["docker", "compose"], ["web"]))

    def test_nothing_running_from_here(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(applying.running_compose(folder, containers=lambda engine: [self.labels("/x", "a")]))


if __name__ == "__main__":
    unittest.main()
