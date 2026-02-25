"""Tests for speaker_detect.py — all offline, no real ffmpeg/pyannote calls."""

import io
import json
import math
import struct
import sys
import wave
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools"))
from speaker_detect import (
    detect_speakers,
    _rms_energy,
    _compute_chunk_energies,
    _normalize_energies,
    _assign_speakers_by_energy,
    _diarize_with_pyannote,
    ENERGY_CHANGE_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers — WAV generation
# ---------------------------------------------------------------------------


def _make_wav_bytes(
    samples: list[int],
    sample_rate: int = 16000,
    sample_width: int = 2,
    num_channels: int = 1,
) -> bytes:
    """Build a valid WAV file in memory from 16-bit PCM samples."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        raw = struct.pack(f"<{len(samples)}h", *samples)
        wf.writeframes(raw)
    return buf.getvalue()


def _make_uniform_samples(duration_s: float, amplitude: int = 5000, sr: int = 16000) -> list[int]:
    """Generate uniform-amplitude samples for given duration."""
    n = int(duration_s * sr)
    return [amplitude] * n


def _make_varying_samples(
    durations: list[float],
    amplitudes: list[int],
    sr: int = 16000,
) -> list[int]:
    """Generate samples with different amplitudes per segment.

    durations and amplitudes must be same length. Each segment gets
    constant amplitude for its duration.
    """
    samples = []
    for dur, amp in zip(durations, amplitudes):
        n = int(dur * sr)
        samples.extend([amp] * n)
    return samples


def _make_chunks(n: int, chunk_duration: float = 10.0) -> list[dict]:
    """Build n sequential chunks of chunk_duration seconds each."""
    return [
        {"id": i, "start": i * chunk_duration, "end": (i + 1) * chunk_duration}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Mock subprocess — writes a real WAV file on ffmpeg calls
# ---------------------------------------------------------------------------


class WavMocker:
    """Configurable mock for subprocess.run that writes WAV data on ffmpeg calls."""

    def __init__(self, wav_bytes: bytes):
        self.wav_bytes = wav_bytes

    def __call__(self, cmd, **kwargs):
        prog = cmd[0] if cmd else ""
        if prog == "ffmpeg":
            # Find the output path — it is the argument before -y.
            try:
                y_idx = cmd.index("-y")
                out_path = Path(cmd[y_idx - 1])
            except (ValueError, IndexError):
                # Fallback: look for .wav in args.
                out_path = None
                for arg in cmd:
                    if arg.endswith(".wav"):
                        out_path = Path(arg)
                        break
            if out_path:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(self.wav_bytes)
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")


def _mock_ffmpeg_fail(cmd, **kwargs):
    """Mock where ffmpeg returns non-zero exit code."""
    return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="error")


# ---------------------------------------------------------------------------
# Tests: RMS energy computation
# ---------------------------------------------------------------------------


class TestRmsEnergy:
    """Test _rms_energy helper."""

    def test_empty_samples(self):
        assert _rms_energy([]) == 0.0

    def test_single_sample(self):
        assert _rms_energy([100]) == pytest.approx(100.0)

    def test_known_values(self):
        """RMS of [3, 4] = sqrt((9+16)/2) = sqrt(12.5)."""
        expected = math.sqrt(12.5)
        assert _rms_energy([3, 4]) == pytest.approx(expected)

    def test_uniform_samples(self):
        """RMS of constant value equals that value."""
        assert _rms_energy([5000] * 100) == pytest.approx(5000.0)


# ---------------------------------------------------------------------------
# Tests: Energy method — output schema
# ---------------------------------------------------------------------------


class TestOutputSchema:
    """Test that detect_speakers returns correct schema keys and types."""

    @patch("speaker_detect.subprocess.run")
    def test_schema_keys_present(self, mock_sub, tmp_path):
        """Output dict has all required top-level keys."""
        wav_data = _make_wav_bytes(_make_uniform_samples(30.0))
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "test.mp4"
        video.write_text("fake")
        chunks = _make_chunks(3)

        result = detect_speakers(str(video), chunks=chunks, output_dir=str(tmp_path))

        assert "source" in result
        assert "method" in result
        assert "speakers" in result
        assert "segments" in result
        assert "chunk_speakers" in result
        assert result["source"] == "test.mp4"
        assert result["method"] == "energy"
        assert isinstance(result["speakers"], list)
        assert isinstance(result["segments"], list)
        assert isinstance(result["chunk_speakers"], dict)

    @patch("speaker_detect.subprocess.run")
    def test_segment_schema(self, mock_sub, tmp_path):
        """Each segment has start, end, speaker keys."""
        wav_data = _make_wav_bytes(_make_uniform_samples(30.0))
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "test.mp4"
        video.write_text("fake")

        result = detect_speakers(str(video), output_dir=str(tmp_path))

        for seg in result["segments"]:
            assert "start" in seg
            assert "end" in seg
            assert "speaker" in seg
            assert isinstance(seg["start"], (int, float))
            assert isinstance(seg["end"], (int, float))
            assert isinstance(seg["speaker"], str)

    @patch("speaker_detect.subprocess.run")
    def test_chunk_speakers_keys_are_strings(self, mock_sub, tmp_path):
        """chunk_speakers keys are string chunk IDs."""
        wav_data = _make_wav_bytes(_make_uniform_samples(30.0))
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "test.mp4"
        video.write_text("fake")
        chunks = _make_chunks(3)

        result = detect_speakers(str(video), chunks=chunks, output_dir=str(tmp_path))

        for key in result["chunk_speakers"]:
            assert isinstance(key, str)
            int(key)  # Should not raise — keys are numeric strings.


# ---------------------------------------------------------------------------
# Tests: Speaker change detection (energy shift > 30%)
# ---------------------------------------------------------------------------


class TestSpeakerChangeDetection:
    """Test that >30% energy shifts mark speaker changes."""

    @patch("speaker_detect.subprocess.run")
    def test_large_energy_shift_creates_new_speaker(self, mock_sub, tmp_path):
        """A dramatic amplitude change between chunks flags a speaker change."""
        # 3 chunks at 10s each: low, HIGH, low
        samples = _make_varying_samples(
            durations=[10.0, 10.0, 10.0],
            amplitudes=[1000, 10000, 1000],
        )
        wav_data = _make_wav_bytes(samples)
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "talk.mp4"
        video.write_text("fake")
        chunks = _make_chunks(3)

        result = detect_speakers(str(video), chunks=chunks, output_dir=str(tmp_path))

        # Should have more than one speaker.
        assert len(result["speakers"]) > 1
        # Chunk 0 and chunk 1 should have different speakers.
        assert result["chunk_speakers"]["0"] != result["chunk_speakers"]["1"]

    @patch("speaker_detect.subprocess.run")
    def test_multiple_changes(self, mock_sub, tmp_path):
        """Multiple energy shifts create multiple speaker labels."""
        # low, high, low, high — 4 chunks
        samples = _make_varying_samples(
            durations=[10.0, 10.0, 10.0, 10.0],
            amplitudes=[1000, 10000, 1000, 10000],
        )
        wav_data = _make_wav_bytes(samples)
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "multi.mp4"
        video.write_text("fake")
        chunks = _make_chunks(4)

        result = detect_speakers(str(video), chunks=chunks, output_dir=str(tmp_path))

        # Each transition is a change, so we should have at least 3 segments.
        assert len(result["segments"]) >= 3


# ---------------------------------------------------------------------------
# Tests: No speaker change (uniform energy)
# ---------------------------------------------------------------------------


class TestNoSpeakerChange:
    """Test that uniform energy produces a single speaker."""

    @patch("speaker_detect.subprocess.run")
    def test_uniform_energy_one_speaker(self, mock_sub, tmp_path):
        """Constant amplitude across all chunks -> one speaker only."""
        samples = _make_uniform_samples(50.0, amplitude=5000)
        wav_data = _make_wav_bytes(samples)
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "mono.mp4"
        video.write_text("fake")
        chunks = _make_chunks(5)

        result = detect_speakers(str(video), chunks=chunks, output_dir=str(tmp_path))

        assert result["speakers"] == ["SPEAKER_0"]
        assert len(result["segments"]) == 1
        assert result["segments"][0]["speaker"] == "SPEAKER_0"
        # All chunks assigned to same speaker.
        for cid in result["chunk_speakers"]:
            assert result["chunk_speakers"][cid] == "SPEAKER_0"


# ---------------------------------------------------------------------------
# Tests: Pyannote import failure
# ---------------------------------------------------------------------------


class TestPyannoteImportFailure:
    """Test that pyannote import failure is handled gracefully."""

    def test_diarize_returns_none_without_pyannote(self, tmp_path):
        """_diarize_with_pyannote returns None when pyannote not installed."""
        wav = tmp_path / "audio.wav"
        wav.write_bytes(_make_wav_bytes(_make_uniform_samples(10.0)))

        result = _diarize_with_pyannote(wav, chunks=None, num_speakers=None)
        assert result is None

    @patch("speaker_detect.subprocess.run")
    def test_pyannote_method_falls_back_to_energy(self, mock_sub, tmp_path):
        """When method='pyannote' but pyannote unavailable, falls back to energy."""
        samples = _make_uniform_samples(20.0)
        wav_data = _make_wav_bytes(samples)
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "clip.mp4"
        video.write_text("fake")

        result = detect_speakers(
            str(video), method="pyannote", output_dir=str(tmp_path),
        )

        # Should succeed with energy fallback.
        assert "error" not in result
        assert result["method"] == "energy"


# ---------------------------------------------------------------------------
# Tests: No chunks provided
# ---------------------------------------------------------------------------


class TestNoChunksProvided:
    """Test that detection works when no chunks are given."""

    @patch("speaker_detect.subprocess.run")
    def test_auto_chunks_created(self, mock_sub, tmp_path):
        """Without explicit chunks, synthetic 10s chunks are generated."""
        # 30 seconds of audio -> should get 3 synthetic chunks.
        samples = _make_uniform_samples(30.0)
        wav_data = _make_wav_bytes(samples)
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "auto.mp4"
        video.write_text("fake")

        result = detect_speakers(str(video), chunks=None, output_dir=str(tmp_path))

        assert "error" not in result
        assert len(result["chunk_speakers"]) == 3
        assert "0" in result["chunk_speakers"]
        assert "1" in result["chunk_speakers"]
        assert "2" in result["chunk_speakers"]

    @patch("speaker_detect.subprocess.run")
    def test_auto_chunks_with_varying_energy(self, mock_sub, tmp_path):
        """Synthetic chunks still detect speaker changes from energy shifts."""
        samples = _make_varying_samples(
            durations=[10.0, 10.0, 10.0],
            amplitudes=[1000, 10000, 1000],
        )
        wav_data = _make_wav_bytes(samples)
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "autovar.mp4"
        video.write_text("fake")

        result = detect_speakers(str(video), chunks=None, output_dir=str(tmp_path))

        assert len(result["speakers"]) > 1


# ---------------------------------------------------------------------------
# Tests: With chunks provided
# ---------------------------------------------------------------------------


class TestWithChunksProvided:
    """Test that provided chunks get speaker assignments."""

    @patch("speaker_detect.subprocess.run")
    def test_all_chunks_assigned(self, mock_sub, tmp_path):
        """Every provided chunk gets a speaker label in chunk_speakers."""
        samples = _make_uniform_samples(50.0)
        wav_data = _make_wav_bytes(samples)
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "full.mp4"
        video.write_text("fake")
        chunks = _make_chunks(5)

        result = detect_speakers(str(video), chunks=chunks, output_dir=str(tmp_path))

        assert len(result["chunk_speakers"]) == 5
        for i in range(5):
            assert str(i) in result["chunk_speakers"]

    @patch("speaker_detect.subprocess.run")
    def test_segments_cover_full_range(self, mock_sub, tmp_path):
        """Segments should cover from first chunk start to last chunk end."""
        samples = _make_uniform_samples(40.0)
        wav_data = _make_wav_bytes(samples)
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "cover.mp4"
        video.write_text("fake")
        chunks = _make_chunks(4)

        result = detect_speakers(str(video), chunks=chunks, output_dir=str(tmp_path))

        assert result["segments"][0]["start"] == 0.0
        assert result["segments"][-1]["end"] == 40.0


# ---------------------------------------------------------------------------
# Tests: Error handling (bad input path)
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Test graceful error handling for bad inputs."""

    @patch("speaker_detect.subprocess.run", side_effect=_mock_ffmpeg_fail)
    def test_bad_input_returns_error(self, mock_sub, tmp_path):
        """Non-existent or unreadable file returns error dict."""
        result = detect_speakers(
            str(tmp_path / "nonexistent.mp4"),
            output_dir=str(tmp_path),
        )

        assert "error" in result
        assert result["error"] == "audio extraction failed"
        assert result["source"] == "nonexistent.mp4"

    @patch("speaker_detect.subprocess.run", side_effect=FileNotFoundError("ffmpeg not found"))
    def test_ffmpeg_not_found(self, mock_sub, tmp_path):
        """FileNotFoundError (no ffmpeg) returns error dict."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")

        result = detect_speakers(str(video), output_dir=str(tmp_path))

        assert "error" in result
        assert result["source"] == "clip.mp4"


# ---------------------------------------------------------------------------
# Tests: num_speakers limit
# ---------------------------------------------------------------------------


class TestNumSpeakersLimit:
    """Test that num_speakers merges excess speaker labels."""

    @patch("speaker_detect.subprocess.run")
    def test_merge_to_two_speakers(self, mock_sub, tmp_path):
        """With num_speakers=2, result has at most 2 speakers."""
        # 4 alternating amplitudes -> without limit would be 4 speakers.
        samples = _make_varying_samples(
            durations=[10.0, 10.0, 10.0, 10.0],
            amplitudes=[1000, 10000, 1000, 10000],
        )
        wav_data = _make_wav_bytes(samples)
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "merge.mp4"
        video.write_text("fake")
        chunks = _make_chunks(4)

        result = detect_speakers(
            str(video), chunks=chunks, num_speakers=2,
            output_dir=str(tmp_path),
        )

        assert len(result["speakers"]) <= 2

    @patch("speaker_detect.subprocess.run")
    def test_merge_to_one_speaker(self, mock_sub, tmp_path):
        """With num_speakers=1, everything merges to a single speaker."""
        samples = _make_varying_samples(
            durations=[10.0, 10.0, 10.0],
            amplitudes=[1000, 10000, 1000],
        )
        wav_data = _make_wav_bytes(samples)
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "one.mp4"
        video.write_text("fake")
        chunks = _make_chunks(3)

        result = detect_speakers(
            str(video), chunks=chunks, num_speakers=1,
            output_dir=str(tmp_path),
        )

        assert result["speakers"] == ["SPEAKER_0"]
        for cid in result["chunk_speakers"]:
            assert result["chunk_speakers"][cid] == "SPEAKER_0"


# ---------------------------------------------------------------------------
# Tests: Output file written
# ---------------------------------------------------------------------------


class TestOutputFileWritten:
    """Test that speaker_map.json is written to output dir."""

    @patch("speaker_detect.subprocess.run")
    def test_speaker_map_json_exists(self, mock_sub, tmp_path):
        """speaker_map.json should be written after successful detection."""
        wav_data = _make_wav_bytes(_make_uniform_samples(20.0))
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = detect_speakers(str(video), output_dir=str(out))

        map_path = out / "speaker_map.json"
        assert map_path.exists(), "speaker_map.json was not written"

        with open(map_path) as f:
            data = json.load(f)

        assert data["source"] == "clip.mp4"
        assert data["method"] == "energy"
        assert "speakers" in data
        assert "segments" in data
        assert "chunk_speakers" in data

        # Return value matches file content.
        assert result == data

    @patch("speaker_detect.subprocess.run", side_effect=_mock_ffmpeg_fail)
    def test_no_file_on_error(self, mock_sub, tmp_path):
        """speaker_map.json should NOT be written when extraction fails."""
        out = tmp_path / "out"
        out.mkdir()

        detect_speakers(str(tmp_path / "bad.mp4"), output_dir=str(out))

        map_path = out / "speaker_map.json"
        assert not map_path.exists()


# ---------------------------------------------------------------------------
# Tests: WAV cleanup
# ---------------------------------------------------------------------------


class TestWavCleanup:
    """Test that temporary WAV file is cleaned up."""

    @patch("speaker_detect.subprocess.run")
    def test_temp_wav_removed(self, mock_sub, tmp_path):
        """Temporary WAV file should be deleted after processing."""
        wav_data = _make_wav_bytes(_make_uniform_samples(10.0))
        mock_sub.side_effect = WavMocker(wav_data)

        video = tmp_path / "clip.mp4"
        video.write_text("fake")

        detect_speakers(str(video), output_dir=str(tmp_path))

        wav_path = tmp_path / "clip_speaker_audio.wav"
        assert not wav_path.exists(), "Temporary WAV file was not cleaned up"


# ---------------------------------------------------------------------------
# Tests: Normalize energies edge cases
# ---------------------------------------------------------------------------


class TestNormalizeEnergies:
    """Test _normalize_energies helper."""

    def test_empty_list(self):
        assert _normalize_energies([]) == []

    def test_all_zero_energy(self):
        """All-zero energies normalize to all 0.0."""
        ces = [{"id": 0, "energy": 0.0}, {"id": 1, "energy": 0.0}]
        result = _normalize_energies(ces)
        for ce in result:
            assert ce["energy_norm"] == 0.0

    def test_max_normalizes_to_one(self):
        """The chunk with max energy normalizes to 1.0."""
        ces = [
            {"id": 0, "energy": 100.0},
            {"id": 1, "energy": 200.0},
            {"id": 2, "energy": 50.0},
        ]
        result = _normalize_energies(ces)
        assert result[1]["energy_norm"] == 1.0
        assert result[0]["energy_norm"] == pytest.approx(0.5)
        assert result[2]["energy_norm"] == pytest.approx(0.25)
