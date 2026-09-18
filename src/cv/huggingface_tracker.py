"""Zero-shot ball/player detection via a local Grounding DINO model - the
only genuinely zero-credential detector backend of the three (ball_tracker.py
needs nothing either, but its COCO "sports ball" class is a poor match for a
football; roboflow_tracker.py needs a paid-tier-adjacent API key).

Correction on a claim made earlier in this project's history: Hugging Face's
*hosted* Inference API (`router.huggingface.co`) was assumed to allow
anonymous free access - tested directly and confirmed that's no longer true,
it now 401s without a token, same as Roboflow. What IS still free and
credential-free is running the model locally via `transformers`, which is
what this module does - no API key, but a real cost: `pip install
transformers torch` is a large (multi-GB) install, and the model itself
downloads a few hundred MB to ~1.7GB on first run. CPU inference will be
slow; a GPU matters a lot more here than for the other two backends.

Grounding DINO is a genuine open-vocabulary detector - you give it a text
prompt ("football.", "person.") instead of a fixed class list, so it needs
no football-specific fine-tuning to try. Tradeoff: zero-shot detectors are
generally less precise on small fast-moving objects than a model actually
fine-tuned for the task (see roboflow_tracker.py) - this hasn't been run
against real broadcast video in this environment, same caveat as the other
two backends.
"""

from src.cv.trajectory import Detection

try:
    import torch
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
except ImportError:
    torch = None
    AutoModelForZeroShotObjectDetection = None
    AutoProcessor = None

_DEFAULT_MODEL_ID = "IDEA-Research/grounding-dino-tiny"
_BALL_PROMPT = "football."
_PERSON_PROMPT = "person."


class HuggingFaceTracker:
    def __init__(self, model_id=_DEFAULT_MODEL_ID, confidence=0.3):
        if AutoModelForZeroShotObjectDetection is None:
            raise RuntimeError(
                "transformers and torch are required for the Hugging Face detector. Install with: "
                "pip install transformers torch (large download; a GPU is strongly recommended for "
                "anything close to real-time). No API key needed - this runs locally."
            )
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(self.device)
        self.confidence = confidence

    def detect(self, frame, frame_idx) -> Detection:
        from PIL import Image
        image = Image.fromarray(frame[:, :, ::-1])  # BGR (cv2) -> RGB (PIL)

        ball_boxes = self._detect_prompt(image, _BALL_PROMPT)
        person_boxes = self._detect_prompt(image, _PERSON_PROMPT)

        return Detection(
            frame_idx=frame_idx,
            ball_xy=self._center(ball_boxes[0]) if ball_boxes else None,
            person_boxes=[self._to_xywh(b) for b in person_boxes],
        )

    def _detect_prompt(self, image, prompt):
        """Returns a list of (x1, y1, x2, y2) boxes for the given text prompt."""
        inputs = self.processor(images=image, text=prompt, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)

        results = self.processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, box_threshold=self.confidence,
            text_threshold=self.confidence, target_sizes=[image.size[::-1]],
        )[0]
        return [tuple(b.tolist()) for b in results["boxes"]]

    @staticmethod
    def _center(box):
        x1, y1, x2, y2 = box
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @staticmethod
    def _to_xywh(box):
        x1, y1, x2, y2 = box
        return (x1, y1, x2 - x1, y2 - y1)
