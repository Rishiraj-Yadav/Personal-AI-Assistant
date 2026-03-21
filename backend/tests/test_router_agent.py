import unittest
from unittest import mock

from app.agents.router_agent import RouterAgent


class RouterAgentFastPathTests(unittest.TestCase):
    def setUp(self):
        gen_model = mock.patch("app.agents.router_agent.genai.GenerativeModel")
        gen_configure = mock.patch("app.agents.router_agent.genai.configure")
        self.addCleanup(gen_model.stop)
        self.addCleanup(gen_configure.stop)
        gen_model.start()
        gen_configure.start()
        self.router = RouterAgent()

    def test_routes_interactive_browser_tasks_to_web_autonomous(self):
        result = self.router.classify_task("Go to github.com and open the issues page for this repo.")
        self.assertEqual(result["task_type"], "web_autonomous")

    def test_routes_live_data_questions_to_web(self):
        result = self.router.classify_task("What is the latest bitcoin price today?")
        self.assertEqual(result["task_type"], "web")

    def test_routes_host_control_to_desktop(self):
        result = self.router.classify_task("Take a screenshot of this window and move the mouse to the top right.")
        self.assertEqual(result["task_type"], "desktop")


if __name__ == "__main__":
    unittest.main()
