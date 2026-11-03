#!/usr/bin/env python3
"""Narration -> utterances mapped to the step on screen. Audio never leaves the machine: a transcript the
recorder wrote next to the audio wins; otherwise local ffmpeg + whisper.cpp transcribe it.

Raw utterances only ({seq, t, text}); parse_recording turns them into notes (this module must not import it)."""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

TOOL_TIMEOUT = 600  # seconds per tool call and audio segment
MODEL_ENV = "RECORDING_TO_TEST_WHISPER_MODEL"
DEFAULT_CONFIG = "~/.centertest/recording-to-test.json"
ISO = re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})(?:\.(\d+))?\s*(Z|[+-]\d{2}:?\d{2})?$")
INSTALL = {
    "macos": "brew install ffmpeg whisper-cpp",
    "windows": "winget install Gyan.FFmpeg, then whisper.cpp release zip (whisper-cli.exe) on PATH",
    "linux": "apt install ffmpeg; build whisper.cpp",
    "model": "download a ggml model and set whisperModel in ~/.centertest/recording-to-test.json "
             "(or the RECORDING_TO_TEST_WHISPER_MODEL environment variable)",
}
NOT_READABLE = "audio files are not readable from this input"


def to_ms(iso: str) -> int:
    """Milliseconds since the epoch of an RFC 3339 time. Go writes up to 9 fractional digits and 'Z';
    Python 3.9's fromisoformat takes neither, so both are normalised first."""
    match = ISO.match(iso.strip())
    if not match:
        raise ValueError(f"not an RFC 3339 time: {iso}")
    base, fraction, zone = match.groups()
    zone = "+00:00" if zone in (None, "Z") else (zone if ":" in zone else zone[:3] + ":" + zone[3:])
    moment = datetime.datetime.fromisoformat(base.replace(" ", "T") + zone)
    micros = int((fraction or "0")[:6].ljust(6, "0"))
    return int(moment.timestamp()) * 1000 + micros // 1000


def find_tools(env=os.environ, config_path: str = DEFAULT_CONFIG) -> dict:
    """{"ffmpeg", "whisper", "model"}: paths or None. Model: env var, then the config's whisperModel;
    a model path that is not a file counts as missing. A missing or malformed config is ignored."""
    model = env.get(MODEL_ENV)
    if not model:
        try:
            with open(os.path.expanduser(config_path), encoding="utf-8") as f:
                value = json.load(f).get("whisperModel")
            model = value if isinstance(value, str) else None
        except (OSError, ValueError, AttributeError):
            model = None
    model = os.path.expanduser(model) if model else None
    return {"ffmpeg": shutil.which("ffmpeg"), "whisper": shutil.which("whisper-cli"),
            "model": model if model and os.path.isfile(model) else None}


def assign_steps(utterances: list, steps: list, started_at: str) -> list:
    """Each utterance gets the seq of the last step whose offset (ms since started_at) is <= its time;
    the first step when it speaks before any."""
    origin = to_ms(started_at)
    timed = sorted((to_ms(s["time"]) - origin, s.get("seq")) for s in steps if s.get("time"))
    result = []
    for utterance in sorted(utterances, key=lambda u: u["t"]):
        seq = timed[0][1] if timed else None
        for offset, step_seq in timed:
            if offset <= utterance["t"]:
                seq = step_seq
        result.append(dict(utterance, seq=seq))
    return result


def stem_of(rel: str) -> str:
    return os.path.splitext(rel)[0]


def transcript_segments(read_bytes, rel: str):
    """Segments [{start, end, text}] from audio/<stem>.transcript.json, or None."""
    raw = read_bytes(stem_of(rel) + ".transcript.json")
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw)
        return [{"start": int(s["start"]), "end": int(s.get("end", s["start"])), "text": str(s["text"]).strip()}
                for s in data["segments"]]
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def run(args: list) -> None:
    subprocess.run(args, check=True, timeout=TOOL_TIMEOUT, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def whisper_segments(audio: bytes, index: int, tools: dict, workdir: str):
    """Segments from local ffmpeg + whisper-cli; raises on any failure. Temp files are removed."""
    source, wav, base = (os.path.join(workdir, f"narration-{index}{ext}") for ext in (".webm", ".wav", ""))
    produced = (source, wav, base + ".json")
    try:
        with open(source, "wb") as f:
            f.write(audio)
        run([tools["ffmpeg"], "-y", "-i", source, "-ar", "16000", "-ac", "1", wav])
        run([tools["whisper"], "-m", tools["model"], "-f", wav, "-oj", "-of", base])
        with open(base + ".json", encoding="utf-8") as f:
            data = json.load(f)
        return [{"start": int(t["offsets"]["from"]), "end": int(t["offsets"].get("to", t["offsets"]["from"])),
                 "text": t["text"].strip()} for t in data["transcription"] if t.get("text", "").strip()]
    finally:
        for path in produced:
            try:
                os.remove(path)
            except OSError:
                pass


def narrate(session: dict, read_bytes, tools: dict, workdir: str) -> dict:
    """{"source": none|transcript|whisper|unavailable, "segments", "utterances", "reason"?, "install"?}.
    segments carry times in ms since the recording started; one utterance per segment."""
    audio = session.get("audio") or []
    if not audio:
        return {"source": "none", "segments": [], "utterances": []}
    if read_bytes is None:
        return {"source": "unavailable", "segments": [], "utterances": [], "reason": NOT_READABLE}
    segments, sources, problems = [], set(), []
    can_whisper = all(tools.get(k) for k in ("ffmpeg", "whisper", "model"))
    for index, entry in enumerate(audio):
        rel, offset = entry.get("f", ""), int(entry.get("t") or 0)
        found = transcript_segments(read_bytes, rel)
        source = "transcript"
        if found is None:
            source = "whisper"
            if not can_whisper:
                problems.append(f"{rel}: no transcript file and ffmpeg / whisper-cli / model not all available")
                continue
            data = read_bytes(rel)
            if data is None:
                problems.append(f"{rel}: audio file not found")
                continue
            try:
                found = whisper_segments(data, index, tools, workdir)
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
                problems.append(f"{rel}: transcription failed ({type(error).__name__})")
                continue
        sources.add(source)
        segments += [{"file": rel, "start": offset + s["start"], "end": offset + s["end"], "text": s["text"]}
                     for s in found if s["text"]]
    result = {"source": "whisper" if "whisper" in sources else "transcript" if sources else "unavailable",
              "segments": segments, "utterances": []}
    result["utterances"] = assign_steps([{"t": s["start"], "text": s["text"]} for s in segments],
                                        session.get("steps") or [], session["startedAt"]) \
        if segments and session.get("startedAt") else []
    if problems:
        result["reason"] = "; ".join(problems)
    if not tools_ready(tools) and (result["source"] == "unavailable" or problems):
        result["install"] = dict(INSTALL)
    return result


def tools_ready(tools: dict) -> bool:
    return all(tools.get(k) for k in ("ffmpeg", "whisper", "model"))


def main_narrate(argv=None) -> int:
    """narrate <recording> [--out FILE]: the narration dict of a recording."""
    import parse_recording  # lazy: parse_recording imports this module
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="ct.py narrate", description="recording narration -> utterances")
    parser.add_argument("recording", help="the recording .zip, its folder, or its session.json")
    parser.add_argument("--out", help="write the narration here instead of stdout")
    args = parser.parse_args(argv)
    try:
        session = parse_recording.load_session(args.recording)
    except (parse_recording.RecordingError, ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    import tempfile
    with tempfile.TemporaryDirectory() as workdir:
        result = narrate(session, parse_recording.file_bytes(args.recording), find_tools(), workdir)
    text = json.dumps(result, indent=2, ensure_ascii=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)
    return 0


def main_tools(argv=None) -> int:
    """tools: which of ffmpeg / whisper-cli / the whisper model were found, as JSON."""
    print(json.dumps(find_tools(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main_narrate())
