"""Poses from the photo into the 3D composer.

Asked 2026-10-01 with a screenshot: the composer showed the clothed reference
image's woman - hands on hips, feet apart - as a mannequin standing at
attention. Nothing read a pose: figures were always seeded at rest. DWPose
keypoints now become the figure's joint rotations, and the test that matters
runs those rotations back through the rig's chain (torso → shoulder → elbow,
pelvis → hip → knee): every limb must point where it points in the photo.
"""

from __future__ import annotations

import math

import pytest

from film.pose_from_keypoints import facing_camera, joints_from_keypoints, share_inside
from film.scene_solver import composer_scene_from_layout, layout_from_composition, layout_from_spec
from film.shot_spec import ShotSpec, SpecPose, SpecSource, SpecSubject

#: Read off the reference image (1125 x 2000): hands on hips, feet apart, her
#: left side on the image right. COCO order, [x, y, score].
HANDS_ON_HIPS = [
    [0.52, 0.07, 0.9], [0.54, 0.06, 0.9], [0.50, 0.06, 0.9], [0.57, 0.07, 0.9], [0.47, 0.07, 0.9],
    [0.66, 0.18, 0.9], [0.36, 0.18, 0.9], [0.80, 0.33, 0.9], [0.22, 0.33, 0.9], [0.68, 0.42, 0.9], [0.34, 0.42, 0.9],
    [0.60, 0.46, 0.9], [0.42, 0.46, 0.9], [0.62, 0.68, 0.9], [0.40, 0.68, 0.9], [0.64, 0.92, 0.9], [0.38, 0.92, 0.9],
]
PORTRAIT = 1125 / 2000

LIMBS = {
    # joint chain (parents first) → the keypoint segment it draws
    ("torso", "l_arm"): (5, 7), ("torso", "l_arm", "l_elbow"): (7, 9),
    ("torso", "r_arm"): (6, 8), ("torso", "r_arm", "r_elbow"): (8, 10),
    ("l_leg",): (11, 13), ("l_leg", "l_knee"): (13, 15),
    ("r_leg",): (12, 14), ("r_leg", "r_knee"): (14, 16),
}


def _z(joints: dict[str, list[float]], name: str) -> float:
    return joints.get(name, [0.0, 0.0, 0.0])[2]


def _drawn_direction(chain: tuple[str, ...], joints: dict[str, list[float]], side: float) -> float:
    """Image-plane direction (degrees) of a limb the rig hangs along -Y, after
    the chain's Z rotations, as the camera in front of the figure sees it."""
    theta = math.radians(sum(_z(joints, name) for name in chain))
    fx, fy = math.sin(theta), -math.cos(theta)
    return math.degrees(math.atan2(-fy, side * fx))  # image x right, y down


def _photo_direction(points: list[list[float]], a: int, b: int, aspect: float) -> float:
    return math.degrees(math.atan2(points[b][1] - points[a][1], (points[b][0] - points[a][0]) * aspect))


def _angle_gap(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


class TestPoseFromKeypoints:
    def test_every_limb_of_the_figure_points_where_it_does_in_the_photo(self):
        joints = joints_from_keypoints(HANDS_ON_HIPS, PORTRAIT)
        for chain, (a, b) in LIMBS.items():
            drawn = _drawn_direction(chain, joints, side=1.0)
            photo = _photo_direction(HANDS_ON_HIPS, a, b, PORTRAIT)
            assert _angle_gap(drawn, photo) < 1.0, (chain, drawn, photo)

    def test_hands_on_hips_reads_as_elbows_out_and_hands_back_in(self):
        joints = joints_from_keypoints(HANDS_ON_HIPS, PORTRAIT)
        assert _z(joints, "l_arm") > 25 and _z(joints, "r_arm") < -25, joints
        assert _z(joints, "l_elbow") < -60 and _z(joints, "r_elbow") > 60, joints
        assert _z(joints, "l_leg") > 0 and _z(joints, "r_leg") < 0, "feet apart"

    def test_standing_at_attention_needs_no_rotation(self):
        straight = [
            [0.5, 0.05, 0.9], [0.52, 0.04, 0.9], [0.48, 0.04, 0.9], [0.54, 0.05, 0.9], [0.46, 0.05, 0.9],
            [0.6, 0.18, 0.9], [0.4, 0.18, 0.9], [0.6, 0.33, 0.9], [0.4, 0.33, 0.9], [0.6, 0.46, 0.9], [0.4, 0.46, 0.9],
            [0.56, 0.5, 0.9], [0.44, 0.5, 0.9], [0.56, 0.72, 0.9], [0.44, 0.72, 0.9], [0.56, 0.94, 0.9], [0.44, 0.94, 0.9],
        ]
        assert joints_from_keypoints(straight, PORTRAIT) == {}

    def test_seen_from_behind_the_figure_turns_and_the_limbs_still_line_up(self):
        # The same body mirrored in x: the left shoulder now sits on the image left.
        behind = [[1.0 - x, y, s] for x, y, s in HANDS_ON_HIPS]
        assert facing_camera(behind) is False
        joints = joints_from_keypoints(behind, PORTRAIT)
        for chain, (a, b) in LIMBS.items():
            drawn = _drawn_direction(chain, joints, side=-1.0)
            photo = _photo_direction(behind, a, b, PORTRAIT)
            assert _angle_gap(drawn, photo) < 1.0, (chain, drawn, photo)

    def test_a_joint_whose_points_are_not_seen_stays_at_rest(self):
        hidden = [list(p) for p in HANDS_ON_HIPS]
        hidden[9][2] = 0.1  # left wrist behind the back
        joints = joints_from_keypoints(hidden, PORTRAIT)
        assert "l_elbow" not in joints and "l_arm" in joints

    @pytest.mark.parametrize("box, expected", [([0.2, 0.0, 0.65, 1.0], 1.0), ([0.0, 0.0, 0.1, 0.1], 0.0)])
    def test_a_person_is_matched_to_the_box_holding_their_points(self, box, expected):
        assert share_inside(HANDS_ON_HIPS, box) == pytest.approx(expected)


def _portrait_spec(points: list[list[float]]) -> ShotSpec:
    spec = ShotSpec()
    spec.source = SpecSource(width=1125, height=2000, aspect="9:16")
    spec.subjects = [SpecSubject(label="woman", bbox=[0.13, 0.006, 0.747, 0.976])]
    spec.poses = [SpecPose(bbox=[0.2, 0.05, 0.62, 0.88], score=0.9, keypoints=points)]
    return spec


class TestPosedFigures:
    def test_the_figure_takes_the_pose_of_the_person_in_its_box(self):
        layout = layout_from_spec(_portrait_spec(HANDS_ON_HIPS))
        figure = next(o for o in layout.objects if o.kind == "figure")
        assert figure.joints == joints_from_keypoints(HANDS_ON_HIPS, PORTRAIT)
        scene = composer_scene_from_layout(layout, duration=4.0)
        posed = next(o for o in scene.objects if o.type == "figure")
        assert posed.pose["l_elbow"][2] < -60 and posed.pose["r_elbow"][2] > 60

    def test_a_back_view_turns_the_figure(self):
        behind = [[1.0 - x, y, s] for x, y, s in HANDS_ON_HIPS]
        figure = next(o for o in layout_from_spec(_portrait_spec(behind)).objects if o.kind == "figure")
        assert figure.rot[1] == pytest.approx(math.pi, abs=1e-3)

    def test_the_composer_round_trip_keeps_the_pose(self):
        layout = layout_from_spec(_portrait_spec(HANDS_ON_HIPS))
        back = layout_from_composition(composer_scene_from_layout(layout, duration=4.0))
        assert next(o for o in back.objects if o.kind == "figure").joints == next(o for o in layout.objects if o.kind == "figure").joints

    def test_a_pose_outside_the_figure_is_not_given_to_it(self):
        spec = _portrait_spec([[x * 0.1, y * 0.1, s] for x, y, s in HANDS_ON_HIPS])  # someone tiny in the corner
        spec.subjects[0].bbox = [0.5, 0.3, 0.4, 0.65]
        figure = next(o for o in layout_from_spec(spec).objects if o.kind == "figure")
        assert figure.joints == {}
