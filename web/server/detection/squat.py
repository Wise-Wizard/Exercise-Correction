import cv2
import mediapipe as mp
import numpy as np
import pandas as pd
import pickle

from .utils import calculate_distance, extract_important_keypoints, get_static_file_url

mp_pose = mp.solutions.pose


def analyze_foot_knee_placement(
    results,
    stage: str,
    foot_shoulder_ratio_thresholds: list,
    knee_foot_ratio_thresholds: dict,
    visibility_threshold: int,
) -> dict:
    """
    Calculate the ratio between the foot and shoulder for FOOT PLACEMENT analysis

    Calculate the ratio between the knee and foot for KNEE PLACEMENT analysis

    Return result explanation:
        -1: Unknown result due to poor visibility
        0: Correct knee placement
        1: Placement too tight
        2: Placement too wide
    """
    analyzed_results = {
        "foot_placement": -1,
        "knee_placement": -1,
    }

    landmarks = results.pose_landmarks.landmark

    # * Visibility check of important landmarks for foot placement analysis
    left_foot_index_vis = landmarks[
        mp_pose.PoseLandmark.LEFT_FOOT_INDEX.value
    ].visibility
    right_foot_index_vis = landmarks[
        mp_pose.PoseLandmark.RIGHT_FOOT_INDEX.value
    ].visibility

    left_knee_vis = landmarks[mp_pose.PoseLandmark.LEFT_KNEE.value].visibility
    right_knee_vis = landmarks[mp_pose.PoseLandmark.RIGHT_KNEE.value].visibility

    # If visibility of any keypoints is low cancel the analysis
    if (
        left_foot_index_vis < visibility_threshold
        or right_foot_index_vis < visibility_threshold
        or left_knee_vis < visibility_threshold
        or right_knee_vis < visibility_threshold
    ):
        return analyzed_results

    # * Calculate shoulder width
    left_shoulder = [
        landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER.value].x,
        landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER.value].y,
    ]
    right_shoulder = [
        landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER.value].x,
        landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER.value].y,
    ]
    shoulder_width = calculate_distance(left_shoulder, right_shoulder)

    # * Calculate 2-foot width
    left_foot_index = [
        landmarks[mp_pose.PoseLandmark.LEFT_FOOT_INDEX.value].x,
        landmarks[mp_pose.PoseLandmark.LEFT_FOOT_INDEX.value].y,
    ]
    right_foot_index = [
        landmarks[mp_pose.PoseLandmark.RIGHT_FOOT_INDEX.value].x,
        landmarks[mp_pose.PoseLandmark.RIGHT_FOOT_INDEX.value].y,
    ]
    foot_width = calculate_distance(left_foot_index, right_foot_index)

    # * Calculate foot and shoulder ratio
    foot_shoulder_ratio = round(foot_width / shoulder_width, 1)

    # * Analyze FOOT PLACEMENT
    min_ratio_foot_shoulder, max_ratio_foot_shoulder = foot_shoulder_ratio_thresholds
    if min_ratio_foot_shoulder <= foot_shoulder_ratio <= max_ratio_foot_shoulder:
        analyzed_results["foot_placement"] = 0
    elif foot_shoulder_ratio < min_ratio_foot_shoulder:
        analyzed_results["foot_placement"] = 1
    elif foot_shoulder_ratio > max_ratio_foot_shoulder:
        analyzed_results["foot_placement"] = 2

    # * Visibility check of important landmarks for knee placement analysis
    left_knee_vis = landmarks[mp_pose.PoseLandmark.LEFT_KNEE.value].visibility
    right_knee_vis = landmarks[mp_pose.PoseLandmark.RIGHT_KNEE.value].visibility

    # If visibility of any keypoints is low cancel the analysis
    if left_knee_vis < visibility_threshold or right_knee_vis < visibility_threshold:
        print("Cannot see foot")
        return analyzed_results

    # * Calculate 2 knee width
    left_knee = [
        landmarks[mp_pose.PoseLandmark.LEFT_KNEE.value].x,
        landmarks[mp_pose.PoseLandmark.LEFT_KNEE.value].y,
    ]
    right_knee = [
        landmarks[mp_pose.PoseLandmark.RIGHT_KNEE.value].x,
        landmarks[mp_pose.PoseLandmark.RIGHT_KNEE.value].y,
    ]
    knee_width = calculate_distance(left_knee, right_knee)

    # * Calculate foot and shoulder ratio
    knee_foot_ratio = round(knee_width / foot_width, 1)

    # * Analyze KNEE placement
    up_min_ratio_knee_foot, up_max_ratio_knee_foot = knee_foot_ratio_thresholds.get(
        "up"
    )
    (
        middle_min_ratio_knee_foot,
        middle_max_ratio_knee_foot,
    ) = knee_foot_ratio_thresholds.get("middle")
    down_min_ratio_knee_foot, down_max_ratio_knee_foot = knee_foot_ratio_thresholds.get(
        "down"
    )

    if stage == "up":
        if up_min_ratio_knee_foot <= knee_foot_ratio <= up_max_ratio_knee_foot:
            analyzed_results["knee_placement"] = 0
        elif knee_foot_ratio < up_min_ratio_knee_foot:
            analyzed_results["knee_placement"] = 1
        elif knee_foot_ratio > up_max_ratio_knee_foot:
            analyzed_results["knee_placement"] = 2
    elif stage == "middle":
        if middle_min_ratio_knee_foot <= knee_foot_ratio <= middle_max_ratio_knee_foot:
            analyzed_results["knee_placement"] = 0
        elif knee_foot_ratio < middle_min_ratio_knee_foot:
            analyzed_results["knee_placement"] = 1
        elif knee_foot_ratio > middle_max_ratio_knee_foot:
            analyzed_results["knee_placement"] = 2
    elif stage == "down":
        if down_min_ratio_knee_foot <= knee_foot_ratio <= down_max_ratio_knee_foot:
            analyzed_results["knee_placement"] = 0
        elif knee_foot_ratio < down_min_ratio_knee_foot:
            analyzed_results["knee_placement"] = 1
        elif knee_foot_ratio > down_max_ratio_knee_foot:
            analyzed_results["knee_placement"] = 2

    return analyzed_results


class SquatDetection:
    ML_MODEL_PATH = get_static_file_url("model/squat_model.pkl")

    PREDICTION_PROB_THRESHOLD = 0.7
    VISIBILITY_THRESHOLD = 0.6
    FOOT_SHOULDER_RATIO_THRESHOLDS = [1.2, 2.8]
    KNEE_FOOT_RATIO_THRESHOLDS = {
        "up": [0.5, 1.0],
        "middle": [0.7, 1.0],
        "down": [0.7, 1.1],
    }

    def __init__(self) -> None:
        self.init_important_landmarks()
        self.load_machine_learning_model()

        self.current_stage = ""
        self.counter = 0

    def init_important_landmarks(self) -> None:
        """
        Determine Important landmarks for squat detection
        """

        self.important_landmarks = [
            "NOSE",
            "LEFT_SHOULDER",
            "RIGHT_SHOULDER",
            "LEFT_HIP",
            "RIGHT_HIP",
            "LEFT_KNEE",
            "RIGHT_KNEE",
            "LEFT_ANKLE",
            "RIGHT_ANKLE",
        ]

        # Generate all columns of the data frame
        self.headers = ["label"]  # Label column

        for lm in self.important_landmarks:
            self.headers += [
                f"{lm.lower()}_x",
                f"{lm.lower()}_y",
                f"{lm.lower()}_z",
                f"{lm.lower()}_v",
            ]

    def load_machine_learning_model(self) -> None:
        """
        Load machine learning model
        """
        if not self.ML_MODEL_PATH:
            raise Exception("Cannot found squat model")

        try:
            with open(self.ML_MODEL_PATH, "rb") as f:
                self.model = pickle.load(f)
        except Exception as e:
            raise Exception(f"Error loading model, {e}")

    def detect(self, mp_results, image) -> None:
        """
        Make Squat Errors detection
        """
        try:
            # * Model prediction for SQUAT counter
            # Extract keypoints from frame for the input
            row = extract_important_keypoints(mp_results, self.important_landmarks)
            X = pd.DataFrame([row], columns=self.headers[1:])

            # Make prediction and its probability
            predicted_class = self.model.predict(X)[0]
            prediction_probabilities = self.model.predict_proba(X)[0]
            prediction_probability = round(
                prediction_probabilities[prediction_probabilities.argmax()], 2
            )

            # Evaluate model prediction
            if (
                predicted_class == "down"
                and prediction_probability >= self.PREDICTION_PROB_THRESHOLD
            ):
                self.current_stage = "down"
            elif (
                self.current_stage == "down"
                and predicted_class == "up"
                and prediction_probability >= self.PREDICTION_PROB_THRESHOLD
            ):
                self.current_stage = "up"
                self.counter += 1

            # Analyze squat pose
            analyzed_results = analyze_foot_knee_placement(
                results=mp_results,
                stage=self.current_stage,
                foot_shoulder_ratio_thresholds=self.FOOT_SHOULDER_RATIO_THRESHOLDS,
                knee_foot_ratio_thresholds=self.KNEE_FOOT_RATIO_THRESHOLDS,
                visibility_threshold=self.VISIBILITY_THRESHOLD,
            )

            foot_placement_evaluation = analyzed_results["foot_placement"]
            knee_placement_evaluation = analyzed_results["knee_placement"]

            # * Evaluate FEET PLACEMENT error
            if foot_placement_evaluation == -1:
                feet_placement = "UNK"
            elif foot_placement_evaluation == 0:
                feet_placement = "Correct"
            elif foot_placement_evaluation == 1:
                feet_placement = "Too tight"
            elif foot_placement_evaluation == 2:
                feet_placement = "Too wide"

            # * Evaluate KNEE PLACEMENT error
            if knee_placement_evaluation == -1:
                knee_placement = "UNK"
            elif knee_placement_evaluation == 0:
                knee_placement = "Correct"
            elif knee_placement_evaluation == 1:
                knee_placement = "Too tight"
            elif knee_placement_evaluation == 2:
                knee_placement = "Too wide"

            # Visualization
            # Status box
            cv2.rectangle(image, (0, 0), (500, 60), (245, 117, 16), -1)

            # Display class
            cv2.putText(
                image,
                "COUNT",
                (10, 12),
                cv2.FONT_HERSHEY_COMPLEX,
                0.5,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )
            cv2.putText(
                image,
                f'{str(self.counter)}, {predicted_class.split(" ")[0]}, {str(prediction_probability)}',
                (5, 40),
                cv2.FONT_HERSHEY_COMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

            # Display Feet and Shoulder width ratio
            cv2.putText(
                image,
                "FEET",
                (200, 12),
                cv2.FONT_HERSHEY_COMPLEX,
                0.5,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )
            cv2.putText(
                image,
                feet_placement,
                (195, 40),
                cv2.FONT_HERSHEY_COMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

            # Display knee and Shoulder width ratio
            cv2.putText(
                image,
                "KNEE",
                (330, 12),
                cv2.FONT_HERSHEY_COMPLEX,
                0.5,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )
            cv2.putText(
                image,
                knee_placement,
                (325, 40),
                cv2.FONT_HERSHEY_COMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

        except Exception as e:
            print(f"Error while detecting squat errors: {e}")
