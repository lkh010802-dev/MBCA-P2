import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from adventure_service import RANDOM_QUESTS, recommend_random_quest
from main import app


client = TestClient(app)


class RandomQuestServiceTests(unittest.TestCase):
    def test_all_supported_activities_return_quest_from_own_pool(self):
        for activity, quests in RANDOM_QUESTS.items():
            with self.subTest(activity=activity):
                result = recommend_random_quest(activity)
                self.assertEqual(result["activity"], activity)
                self.assertIn(result["quest"], quests)

    def test_choice_receives_requested_activity_pool(self):
        received = []

        def choose(pool):
            received.append(pool)
            return pool[-1]

        result = recommend_random_quest("cafe", choice_fn=choose)

        self.assertEqual(received, [RANDOM_QUESTS["cafe"]])
        self.assertEqual(result["quest"], RANDOM_QUESTS["cafe"][-1])

    def test_does_not_call_recommendation_services(self):
        with (
            patch("adventure_service.recommend_places") as places,
            patch("adventure_service.calculate_course") as course,
            patch("congestion_service.get_congestion_data") as congestion,
        ):
            recommend_random_quest("walk", choice_fn=lambda pool: pool[0])

        places.assert_not_called()
        course.assert_not_called()
        congestion.assert_not_called()


class RandomQuestApiTests(unittest.TestCase):
    def test_endpoint_supports_every_activity(self):
        for activity, quests in RANDOM_QUESTS.items():
            with self.subTest(activity=activity):
                response = client.post(
                    "/recommend/adventure/quest",
                    json={"activity": activity},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["activity"], activity)
                self.assertIn(response.json()["quest"], quests)

    def test_endpoint_rejects_unsupported_activity(self):
        response = client.post(
            "/recommend/adventure/quest",
            json={"activity": "sports"},
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
