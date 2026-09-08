"""Integration tests for AI Director commands, LLM planning, storyboard generation."""

from __future__ import annotations

import json

from tests.fakes import FakeResponse

PROJECT = "director-project"

SCRIPT = """INT. COFFEE SHOP - DAY

Sunlight cuts across empty tables. SARAH sits alone, staring at an unopened letter.

SARAH
I can't keep pretending this never happened.

She tears the envelope open.

EXT. CITY STREET - NIGHT

JOHN walks fast through the rain, phone pressed to his ear.
"""


def _gemini_json(payload: object) -> FakeResponse:
    return FakeResponse(
        status_code=200,
        json_payload={
            "candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]
        },
    )


def _command(client, name: str, params: dict | None = None) -> dict:
    response = client.post(
        f"/api/film/projects/{PROJECT}/director/command",
        json={"name": name, "params": params or {}},
    )
    assert response.status_code == 200
    return response.json()["results"][0]


class TestDirectorCommands:
    def test_full_shot_build_flow_mutates_shared_state(self, client):
        scene = _command(client, "create_scene", {"title": "Confrontation", "mood": "tense"})
        assert scene["ok"], scene["error"]
        scene_id = scene["result"]["id"]

        sarah = _command(
            client,
            "add_character",
            {"name": "Sarah", "appearance": "tall", "wardrobe": "red coat"},
        )
        assert sarah["ok"]

        shot = _command(
            client,
            "create_shot",
            {"scene_id": scene_id, "title": "OTS on Sarah", "duration_seconds": 6.0},
        )
        assert shot["ok"]
        shot_id = shot["result"]["id"]

        framing = _command(
            client,
            "set_framing",
            {"shot_id": shot_id, "shot_size": "medium", "camera_angle": "ots", "camera_elevation": "eye"},
        )
        assert framing["ok"], framing["error"]

        assigned = _command(
            client, "assign_character", {"shot_id": shot_id, "name": "Sarah", "emotion": "angry"}
        )
        assert assigned["ok"], assigned["error"]

        motion = _command(
            client, "set_camera_motion", {"shot_id": shot_id, "camera_move": "push_in"}
        )
        assert motion["ok"]

        # The UI reads the same store: everything the director did is visible.
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        stored_shot = project["scenes"][0]["shots"][0]
        assert stored_shot["framing"]["camera_angle"] == "ots"
        assert stored_shot["camera_move"] == "push_in"
        assert stored_shot["duration_seconds"] == 6.0
        assert len(stored_shot["characters"]) == 1
        assert stored_shot["characters"][0]["emotion"] == "angry"
        assert "over-the-shoulder" in stored_shot["visual_prompt"]
        assert "red coat" in stored_shot["visual_prompt"]

    def test_add_character_reuses_existing_by_name(self, client):
        first = _command(client, "add_character", {"name": "Sarah"})
        second = _command(client, "add_character", {"name": "sarah"})
        assert first["result"]["id"] == second["result"]["id"]
        assert second["result"]["existing"] is True

    def test_unknown_command_lists_valid_ones(self, client):
        result = _command(client, "explode_set")
        assert result["ok"] is False
        assert "create_shot" in result["error"]

    def test_command_error_is_reported_not_500(self, client):
        result = _command(client, "set_framing", {"shot_id": "missing", "shot_size": "wide"})
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_generate_shot_command_queues(self, client, test_state, create_fake_model_files):
        create_fake_model_files()
        test_state.state.app_settings.use_local_text_encoder = True
        scene_id = _command(client, "create_scene", {})["result"]["id"]
        shot_id = _command(client, "create_shot", {"scene_id": scene_id, "description": "beat"})[
            "result"
        ]["id"]
        result = _command(client, "generate_shot", {"shot_id": shot_id, "kind": "preview"})
        assert result["ok"], result["error"]
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        assert project["scenes"][0]["shots"][0]["versions"][0]["status"] == "complete"

    def test_apply_pose_records_pose_name(self, client):
        scene_id = _command(client, "create_scene", {})["result"]["id"]
        shot_id = _command(client, "create_shot", {"scene_id": scene_id})["result"]["id"]
        _command(client, "add_character", {"name": "John"})
        result = _command(
            client, "apply_pose", {"shot_id": shot_id, "name": "John", "pose_name": "sitting"}
        )
        assert result["ok"], result["error"]
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        assert project["scenes"][0]["shots"][0]["characters"][0]["pose_name"] == "sitting"


class TestDirectorInstruct:
    def test_instruction_plans_and_executes_commands(self, client, test_state):
        test_state.state.app_settings.gemini_api_key = "key"
        plan = {
            "summary": "Create a tense six second OTS shot of Sarah.",
            "commands": [
                {"name": "create_scene", "params": {"title": "Alley"}},
                {"name": "add_character", "params": {"name": "Sarah"}},
            ],
        }
        test_state.http.queue("post", _gemini_json(plan))
        response = client.post(
            f"/api/film/projects/{PROJECT}/director/instruct",
            json={"instruction": "Set up an alley scene with Sarah"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["plan_summary"].startswith("Create a tense")
        assert [r["ok"] for r in payload["results"]] == [True, True]
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        assert project["scenes"][0]["title"] == "Alley"
        assert project["assets"][0]["name"] == "Sarah"

    def test_instruct_without_key_400(self, client, test_state):
        test_state.state.app_settings.gemini_api_key = ""
        response = client.post(
            f"/api/film/projects/{PROJECT}/director/instruct",
            json={"instruction": "do something"},
        )
        assert response.status_code == 400
        assert "AI_DIRECTOR_KEY_MISSING" in response.text

    def test_instruct_stops_on_first_failure(self, client, test_state):
        test_state.state.app_settings.gemini_api_key = "key"
        plan = {
            "summary": "plan",
            "commands": [
                {"name": "set_framing", "params": {"shot_id": "missing"}},
                {"name": "create_scene", "params": {"title": "Should not run"}},
            ],
        }
        test_state.http.queue("post", _gemini_json(plan))
        response = client.post(
            f"/api/film/projects/{PROJECT}/director/instruct",
            json={"instruction": "broken plan"},
        )
        payload = response.json()
        assert len(payload["results"]) == 1
        assert payload["results"][0]["ok"] is False
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        assert project["scenes"] == []


class TestStoryboardGeneration:
    def test_heuristic_storyboard_from_script(self, client):
        client.put(f"/api/film/projects/{PROJECT}/script", json={"content": SCRIPT})
        response = client.post(
            f"/api/film/projects/{PROJECT}/storyboard/generate",
            json={"use_llm": False},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "draft_created"
        assert payload["scenes_created"] == 2
        assert payload["shots_created"] == 4
        assert payload["characters_created"] == 2
        assert payload["used_llm"] is False

        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        assert len(project["scenes"]) == 2
        first_scene = project["scenes"][0]
        assert first_scene["title"].startswith("INT. COFFEE SHOP")
        # All shots land as reviewable drafts, never auto-rendered.
        statuses = {s["status"] for scene in project["scenes"] for s in scene["shots"]}
        assert statuses == {"draft"}
        # First shot establishes wide; dialogue shot carries the line.
        assert first_scene["shots"][0]["framing"]["shot_size"] == "wide"
        dialogue_shots = [s for s in first_scene["shots"] if s["dialogue"]]
        assert len(dialogue_shots) == 1
        assert "pretending" in dialogue_shots[0]["dialogue"]
        # Characters extracted and linked to shots.
        names = {a["name"] for a in project["assets"]}
        assert names == {"Sarah", "John"}

    def test_empty_script_400(self, client):
        response = client.post(
            f"/api/film/projects/{PROJECT}/storyboard/generate", json={"use_llm": False}
        )
        assert response.status_code == 400

    def test_existing_scenes_conflict_without_replace(self, client):
        client.put(f"/api/film/projects/{PROJECT}/script", json={"content": SCRIPT})
        client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "Manual"})
        response = client.post(
            f"/api/film/projects/{PROJECT}/storyboard/generate", json={"use_llm": False}
        )
        assert response.status_code == 409
        replaced = client.post(
            f"/api/film/projects/{PROJECT}/storyboard/generate",
            json={"use_llm": False, "replace_existing": True},
        )
        assert replaced.status_code == 200
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        assert all(not s["title"].startswith("Manual") for s in project["scenes"])

    def test_llm_storyboard_path(self, client, test_state):
        test_state.state.app_settings.gemini_api_key = "key"
        client.put(f"/api/film/projects/{PROJECT}/script", json={"content": SCRIPT})
        plan = {
            "characters": ["SARAH"],
            "scenes": [
                {
                    "title": "INT. COFFEE SHOP - DAY",
                    "description": "A sunlit cafe",
                    "time_of_day": "Day",
                    "mood": "melancholy",
                    "shots": [
                        {
                            "description": "Wide establishing of the empty cafe, Sarah small at a corner table",
                            "action": "Sarah stares at the letter",
                            "dialogue": "",
                            "shot_size": "wide",
                            "camera_angle": "front",
                            "camera_elevation": "high",
                            "composition": "rightThird",
                            "camera_move": "push_in",
                            "duration_seconds": 5,
                            "characters": ["SARAH"],
                        }
                    ],
                }
            ],
        }
        test_state.http.queue("post", _gemini_json(plan))
        response = client.post(
            f"/api/film/projects/{PROJECT}/storyboard/generate", json={"use_llm": True}
        )
        assert response.status_code == 200
        assert response.json()["used_llm"] is True
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        shot = project["scenes"][0]["shots"][0]
        assert shot["framing"]["shot_size"] == "wide"
        assert shot["framing"]["camera_elevation"] == "high"
        assert shot["framing"]["composition"] == "rightThird"
        assert shot["camera_move"] == "push_in"
        assert shot["duration_seconds"] == 5.0
        assert project["assets"][0]["name"] == "Sarah"
