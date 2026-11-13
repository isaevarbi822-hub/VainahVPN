"""Render a 30-second orbital introduction with continuous narration.

Optional tools: numpy, Pillow, espeakng-loader and FFmpeg. No network or secrets.
Run: python scripts/render_intro_video.py
"""
from __future__ import annotations

import ctypes as ct
import json
import math
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
from espeakng_loader import get_data_path, load_library
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "storefront/assets/video"
STEM = "vainah-orbit-30"
SCENES = [
    ("Твой мир.\nТвои правила.", "VAINAH VPN", "Личное пространство в сети.",
     "Вайнах Ви Пи Эн — твоё соединение, твои правила."),
    ("Под твой\nритм.", "ДЛЯ ТЕБЯ", "Тарифы для коротких и долгих планов.",
     "Выбирай подписку для короткой поездки или на долгий срок."),
    ("Ближе\nдруг к другу.", "ДЛЯ СЕМЬИ", "До 6 устройств по одной подписке.",
     "Подключай близких: семейные тарифы рассчитаны на шесть устройств."),
    ("На привычном\nустройстве.", "ТЕЛЕФОН И КОМПЬЮТЕР", "Через совместимый VPN-клиент.",
     "Пользуйся телефоном и компьютером через совместимый Ви Пи Эн клиент."),
    ("Всё\nпод контролем.", "ЛИЧНЫЙ КАБИНЕТ", "Подписка, срок и история заказов.",
     "Срок подписки и история заказов доступны в личном кабинете."),
    ("Начни\nсо знакомства.", "ПРОБНЫЙ ДЕНЬ", "24 часа · 10 ГБ · без карты.",
     "Начни с пробного дня: двадцать четыре часа, десять гигабайт, без банковской карты."),
]


class SpeechEvent(ct.Structure):
    _fields_ = [("type", ct.c_int), ("identifier", ct.c_uint),
                ("text_position", ct.c_int), ("length", ct.c_int),
                ("audio_position", ct.c_int), ("sample", ct.c_int),
                ("user_data", ct.c_void_p), ("id", ct.c_uint64)]


def narration(directory):
    library = load_library()
    library.espeak_Initialize.argtypes = [ct.c_int, ct.c_int, ct.c_char_p, ct.c_int]
    sample_rate = library.espeak_Initialize(2, 0, get_data_path().encode(), 0)
    if sample_rate <= 0:
        raise RuntimeError("Speech initialization failed")
    callback_type = ct.CFUNCTYPE(ct.c_int, ct.POINTER(ct.c_short), ct.c_int,
                                ct.POINTER(SpeechEvent))
    samples, sentence_times = [], []

    @callback_type
    def collect(pointer, length, events):
        if pointer and length:
            samples.append(ct.string_at(pointer, length * 2))
        index = 0
        while events and events[index].type:
            event = events[index]
            if event.type == 2:
                sentence_times.append(event.audio_position / 1000)
            index += 1
        return 0

    library.espeak_SetSynthCallback(collect)
    library.espeak_SetVoiceByName.argtypes = [ct.c_char_p]
    if library.espeak_SetVoiceByName(b"ru") != 0:
        raise RuntimeError("Russian voice unavailable")
    library.espeak_SetParameter(1, 145, 0)
    library.espeak_Synth.argtypes = [ct.c_void_p, ct.c_size_t, ct.c_uint, ct.c_int,
                                    ct.c_uint, ct.c_uint, ct.c_void_p, ct.c_void_p]
    # A single synthesis and encoding pass: no five-second joins, cuts or resets.
    script = "\n".join(scene[3] for scene in SCENES)
    buffer = ct.create_string_buffer(script.encode())
    if library.espeak_Synth(buffer, len(buffer), 0, 1, 0, 1, None, None) != 0:
        raise RuntimeError("Speech synthesis failed")
    library.espeak_Synchronize()
    pcm = b"".join(samples)
    duration = len(pcm) / (sample_rate * 2)
    tempo = max(.85, duration / 28.8)
    if len(sentence_times) != 6:
        raise RuntimeError(f"Expected six narration cues, received {sentence_times}")
    raw = directory / "continuous.wav"
    with wave.open(str(raw), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    audio = directory / "master.wav"
    # Fixed headroom preserves sample timing; dynamic look-ahead normalization
    # can shift narration relative to the chapter cues.
    processed = directory / "processed.wav"
    filters = (f"highpass=f=65,lowpass=f=9500,atempo={tempo},"
               "aresample=48000,volume=0.85,asetpts=N/SR/TB")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
                    "-af", filters, "-ar", "48000", "-ac", "2", str(processed)], check=True)
    # Assemble the final PCM by sample count. This avoids timestamp offsets,
    # channel-specific delays and trimming words at AAC or scene boundaries.
    with wave.open(str(processed)) as wav:
        speech = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(-1, 2)
    lead = round(.35 * 48000)
    if len(speech) + lead > 30 * 48000:
        raise RuntimeError("Narration exceeds the video; refusing to truncate speech")
    master = np.zeros((30 * 48000, 2), dtype=np.float64)
    master[lead:lead + len(speech)] = speech
    master[:4800] *= np.linspace(0, 1, 4800)[:, None]
    master[-24000:] *= np.linspace(1, 0, 24000)[:, None]
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(np.rint(master).astype("<i2").tobytes())
    starts = [0.0] + [round(value / tempo + .35, 3) for value in sentence_times[1:]]
    print(f"Continuous narration: {duration:.2f}s, scene cues: {starts}", flush=True)
    return audio, starts


class Globe:
    def __init__(self):
        mask = Image.new("L", (1440, 720))
        draw = ImageDraw.Draw(mask)
        data = json.loads((ROOT / "scripts/media/earth-land.geojson").read_text())
        for feature in data["features"]:
            geometry = feature["geometry"]
            polygons = geometry["coordinates"]
            if geometry["type"] == "Polygon":
                polygons = [polygons]
            for polygon in polygons:
                for index, ring in enumerate(polygon):
                    points = [((lon + 180) * 4, (90 - lat) * 4) for lon, lat in ring]
                    draw.polygon(points, fill=255 if index == 0 else 0)
        self.land = np.asarray(mask, dtype=float) / 255
        self.coast = np.asarray(mask.filter(ImageFilter.FIND_EDGES), dtype=float) / 255
        self.size = 560
        ys, xs = np.mgrid[-1:1:complex(self.size), -1:1:complex(self.size)]
        self.inside = xs ** 2 + ys ** 2 < .995
        z = np.sqrt(np.clip(1 - xs ** 2 - ys ** 2, 0, 1))
        tilt = .23
        self.world_y = -ys * math.cos(tilt) - z * math.sin(tilt)
        self.world_z = ys * math.sin(tilt) + z * math.cos(tilt)
        self.xs = xs
        self.latitude = np.arcsin(np.clip(self.world_y, -1, 1))
        self.light = np.clip(-xs * .35 - ys * .45 + z * .85, 0, 1)
        self.alpha = np.uint8(self.inside * 255)

    def frame(self, time):
        longitude = np.arctan2(self.xs, self.world_z) + time * .115 + .45
        column = ((longitude + np.pi) / (2 * np.pi) * 1440).astype(int) % 1440
        row = np.clip(((np.pi / 2 - self.latitude) / np.pi * 720).astype(int), 0, 719)
        land = self.land[row, column]
        coast = self.coast[row, column]
        light = .18 + .82 * self.light
        water = np.array([20, 45, 37])[None, None, :]
        ground = np.array([95, 142, 78])[None, None, :]
        color = (water * (1 - land[:, :, None]) + ground * land[:, :, None]) * light[:, :, None]
        grid = (np.abs(np.sin(longitude * 12)) < .025) | (np.abs(np.sin(self.latitude * 12)) < .025)
        color += grid[:, :, None] * np.array([12, 21, 13])
        color += coast[:, :, None] * np.array([30, 47, 25]) * light[:, :, None]
        rgba = np.dstack([np.uint8(np.clip(color, 0, 255)), self.alpha])
        return Image.fromarray(rgba)


def render():
    width, height, fps = 1280, 720, 24
    accent = (208, 247, 135)
    fonts = Path("/usr/share/fonts/truetype/dejavu")
    heading = ImageFont.truetype(str(fonts / "DejaVuSans-Bold.ttf"), 50)
    regular = ImageFont.truetype(str(fonts / "DejaVuSans.ttf"), 19)
    small = ImageFont.truetype(str(fonts / "DejaVuSans.ttf"), 12)
    globe = Globe()
    stars = np.random.default_rng(37).uniform([560, 30], [1250, 650], (70, 2))
    base = Image.new("RGB", (width, height), (12, 19, 17))
    with tempfile.TemporaryDirectory(prefix="vainah-orbit-") as tmp:
        audio, starts = narration(Path(tmp))
        process = subprocess.Popen([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", "-i", str(audio),
            "-c:v", "libx264", "-preset", "fast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-t", "30", "-movflags", "+faststart", str(ASSETS / f"{STEM}.mp4")], stdin=subprocess.PIPE)
        for frame in range(30 * fps):
            time = frame / fps
            index = max(i for i, start in enumerate(starts) if start <= time)
            local = time - starts[index]
            image = base.copy()
            draw = ImageDraw.Draw(image)
            for number, (x, y) in enumerate(stars):
                brightness = int(35 + 20 * (1 + math.sin(time * .6 + number)))
                draw.ellipse((x, y, x + 1, y + 1), fill=(brightness, brightness + 12, brightness))
            cx, cy = 942 + 15 * math.sin(time * .24), 353 + 14 * math.sin(time * .35)
            radius = 234 + 16 * math.sin(time * .18)
            # Moving orbital paths are an illustration, never a live service status.
            for orbit in range(3):
                angle = orbit * .85 - .5
                points = []
                for phase in np.linspace(0, 2 * math.pi, 181):
                    x = math.cos(phase) * (radius + 48)
                    y = math.sin(phase) * (65 + orbit * 27)
                    points.append((cx + x * math.cos(angle) - y * math.sin(angle),
                                   cy + x * math.sin(angle) + y * math.cos(angle)))
                draw.line(points, fill=(45, 66, 45), width=1)
                node = points[int((time * 10 + orbit * 50) % 180)]
                draw.ellipse((node[0] - 3, node[1] - 3, node[0] + 3, node[1] + 3), fill=accent)
            earth = globe.frame(time).resize((int(radius * 2), int(radius * 2)), Image.Resampling.LANCZOS)
            image.paste(earth, (int(cx - radius), int(cy - radius)), earth)
            draw = ImageDraw.Draw(image)
            draw.ellipse((cx - radius - 2, cy - radius - 2, cx + radius + 2, cy + radius + 2), outline=(121, 170, 95), width=2)
            draw.arc((cx - radius - 10, cy - radius - 10, cx + radius + 10, cy + radius + 10), 160, 295, fill=(65, 90, 57), width=2)
            title, label, description, _ = SCENES[index]
            draw.text((64, 47), "V / VAINAH VPN", font=regular, fill=accent)
            draw.text((64, 186), label, font=small, fill=accent)
            fade = min(1, local * 3)
            ink = tuple(round(16 + (value - 16) * fade) for value in (240, 241, 233))
            draw.multiline_text((60, 237 + int((1 - fade) * 12)), title, font=heading, fill=ink, spacing=9)
            draw.text((64, 410), description, font=regular, fill=(166, 187, 155))
            if index == 5:
                draw.rounded_rectangle((64, 472, 335, 526), radius=12, fill=accent)
                draw.text((82, 489), "Попробовать бесплатно", font=regular, fill=(20, 30, 17))
            draw.text((64, 624), f"0{index + 1} / 06", font=small, fill=accent)
            draw.text((160, 624), "ТВОЁ СОЕДИНЕНИЕ. ТВОИ ПРАВИЛА.", font=small, fill=(135, 159, 125))
            draw.text((800, 655), "ГЛОБАЛЬНАЯ СВЯЗЬ / ВИЗУАЛЬНАЯ ИЛЛЮСТРАЦИЯ", font=small, fill=(104, 137, 96))
            draw.line((64, 670, 500, 670), fill=(46, 65, 44), width=2)
            draw.line((64, 670, 64 + 436 * time / 30, 670), fill=accent, width=2)
            if frame == fps:
                image.save(ASSETS / f"{STEM}-poster.jpg", quality=93)
            process.stdin.write(image.tobytes())
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("Video encoding failed")
    captions = ["WEBVTT", ""]
    for index, scene in enumerate(SCENES):
        end = starts[index + 1] if index < 5 else 30
        captions += [str(index + 1), f"00:00:{starts[index]:06.3f} --> 00:00:{end:06.3f}", scene[3], ""]
    (ASSETS / f"{STEM}-ru.vtt").write_text("\n".join(captions).rstrip() + "\n")
    print("Created orbital video: 30s, continuous stereo narration, six synchronized chapters", flush=True)


if __name__ == "__main__":
    render()
