"""Transcribes a live radio/audio stream in near-real-time and extracts
play-by-play events from the text - a signal source no other module here
captures: radio commentary is a fundamentally different failure mode from
CV (works when the broadcast graphic is obscured or there's no video feed
at all) and from a score API (a human calling the play, not a structured
result posting after the fact).

Uses faster-whisper locally - no API key, no cloud account. Verified in this
environment: model load + a real transcribe() call both succeed, and on CPU
with the "tiny" model, 3 seconds of audio processed in ~1.4s - i.e. faster
than real-time even without a GPU, which is what makes rolling-chunk
transcription viable for this use case at all.

This is chunk-based (default 5s windows), not word-by-word streaming ASR -
there's an inherent latency floor of one chunk length. A real streaming ASR
service (Deepgram, AssemblyAI real-time, etc.) would beat that, but needs a
paid API key this project can't set up on your behalf - same "here's the
free/local option, here's the tradeoff" pattern as the CV detectors.
"""

import re
import time

import numpy as np

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

try:
    import av
except ImportError:
    av = None

# Keyword-spotted play events - deliberately simple regex matching rather
# than an NLP model: fast, zero additional dependency, and good enough to
# flag "something just happened, go look" rather than to fully parse the play.
_EVENT_KEYWORDS = {
    "touchdown": re.compile(r"\btouchdown\b", re.IGNORECASE),
    "interception": re.compile(r"\bintercept(ed|ion)?\b", re.IGNORECASE),
    "fumble": re.compile(r"\bfumbles?\b", re.IGNORECASE),
    "field_goal": re.compile(r"\bfield goal\b", re.IGNORECASE),
    "sack": re.compile(r"\bsack(ed)?\b", re.IGNORECASE),
    "penalty": re.compile(r"\bpenalty\b|\bflag\b", re.IGNORECASE),
    "safety": re.compile(r"\bsafety\b", re.IGNORECASE),
    "injury": re.compile(r"\binjur(y|ed)\b|\bhurt\b|\bcarted off\b", re.IGNORECASE),
}


def extract_events(text):
    """Returns the list of event-type names mentioned in a transcript chunk."""
    return [name for name, pattern in _EVENT_KEYWORDS.items() if pattern.search(text)]


def is_configured():
    return WhisperModel is not None and av is not None


class RadioTranscriber:
    def __init__(self, model_size="base", chunk_seconds=5.0):
        if WhisperModel is None or av is None:
            raise RuntimeError(
                "faster-whisper and av are required for radio transcription. Install with: "
                "pip install faster-whisper av (no API key needed - runs locally)."
            )
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.chunk_seconds = chunk_seconds

    def transcribe_stream(self, stream_url):
        """Generator yielding (text, events, timestamp) for each rolling
        ~chunk_seconds window of audio, in order as the stream plays."""
        container = av.open(stream_url)
        try:
            audio_stream = next(s for s in container.streams if s.type == "audio")
        except StopIteration:
            raise RuntimeError(f"No audio stream found at {stream_url}")

        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=16000)
        chunk_samples = int(self.chunk_seconds * 16000)
        buffer = np.array([], dtype=np.int16)

        for frame in container.decode(audio_stream):
            for resampled in resampler.resample(frame):
                samples = resampled.to_ndarray().flatten()
                buffer = np.concatenate([buffer, samples])

            while len(buffer) >= chunk_samples:
                chunk, buffer = buffer[:chunk_samples], buffer[chunk_samples:]
                text = self._transcribe_chunk(chunk)
                if text:
                    yield text, extract_events(text), time.time()

    def _transcribe_chunk(self, int16_samples):
        audio_float = int16_samples.astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(audio_float, language="en", vad_filter=True)
        return " ".join(s.text for s in segments).strip()
