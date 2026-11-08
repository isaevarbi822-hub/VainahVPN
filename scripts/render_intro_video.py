"""Build the 30-second illustrated introduction (optional media tooling).

Requires Pillow, espeakng-loader and FFmpeg. No application secrets or network calls.
Run with the installed media tools: python scripts/render_intro_video.py
"""
from __future__ import annotations

import ctypes as ct
import subprocess
import tempfile
import wave
from pathlib import Path

from espeakng_loader import get_data_path, load_library
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "storefront/assets/video"
SCENES = [
    ("Свобода быть\nна связи.", "VAINAH VPN", "Твоё соединение. Твои правила.",
     "Вайнах Ви Пи Эн. Твоё соединение. Твои правила. Открой своё пространство в сети."),
    ("В своём\nритме.", "ДЛЯ ТЕБЯ", "Личные тарифы — до 3 устройств.",
     "Выбирай подписку под свой ритм. Для короткой поездки или на долгий срок."),
    ("Вместе —\nудобнее.", "ДЛЯ СЕМЬИ", "Семейный доступ — до 6 устройств.",
     "Для семьи есть отдельные тарифы. До шести устройств по одной подписке."),
    ("На твоём\nустройстве.", "ТЕЛЕФОН И КОМПЬЮТЕР", "Через совместимый VPN-клиент.",
     "Телефон, планшет и компьютер. Подключай свои устройства через совместимый Ви Пи Эн клиент."),
    ("Всё\nпод рукой.", "ЛИЧНЫЙ КАБИНЕТ", "Подписка, срок и история заказов.",
     "Управляй доступом в личном кабинете. Смотри срок подписки и историю своих заказов."),
    ("Начни\nсо знакомства.", "ПРОБНЫЙ ДЕНЬ", "24 часа · 10 ГБ · без карты.",
     "Начни с пробного дня. Двадцать четыре часа, десять гигабайт. Без банковской карты."),
]


def narration(directory: Path):
    library = load_library()
    library.espeak_Initialize.argtypes = [ct.c_int, ct.c_int, ct.c_char_p, ct.c_int]
    sample_rate = library.espeak_Initialize(2, 0, get_data_path().encode(), 0)
    if sample_rate <= 0:
        raise RuntimeError("Speech initialization failed")
    callback_type = ct.CFUNCTYPE(ct.c_int, ct.POINTER(ct.c_short), ct.c_int, ct.c_void_p)
    samples = []

    @callback_type
    def collect(pointer, length, _events):
        if pointer and length:
            samples.append(ct.string_at(pointer, length * 2))
        return 0

    library.espeak_SetSynthCallback(collect)
    library.espeak_SetVoiceByName.argtypes = [ct.c_char_p]
    if library.espeak_SetVoiceByName(b"ru") != 0:
        raise RuntimeError("Russian voice is unavailable")
    library.espeak_SetParameter(1, 165, 0)
    library.espeak_Synth.argtypes = [ct.c_void_p, ct.c_size_t, ct.c_uint, ct.c_int,
                                    ct.c_uint, ct.c_uint, ct.c_void_p, ct.c_void_p]
    for index, (_, _, _, voice) in enumerate(SCENES):
        samples.clear()
        buffer = ct.create_string_buffer(voice.encode())
        if library.espeak_Synth(buffer, len(buffer), 0, 1, 0, 1, None, None) != 0:
            raise RuntimeError("Speech synthesis failed")
        library.espeak_Synchronize()
        pcm = b"".join(samples)
        duration = len(pcm) / (sample_rate * 2)
        raw = directory / f"raw-{index}.wav"
        with wave.open(str(raw), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm)
        # Each narration occupies its own five-second scene, with a short tail.
        tempo = max(1, duration / 4.8)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
                        "-af", f"atempo={tempo},apad", "-t", "5", "-ar", "44100",
                        str(directory / f"scene-{index}.wav")], check=True)
    listing = directory / "audio.txt"
    listing.write_text("".join(f"file '{directory / f'scene-{i}.wav'}'\n" for i in range(6)))
    target = directory / "narration.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listing), str(target)], check=True)
    return target


def render():
    width, height, fps = 1280, 720, 24
    accent = (208, 247, 135)
    sheet = Image.open(ASSETS / "vainah-scenes.png").convert("RGB")
    pictures = [sheet.crop((col * sheet.width // 3, row * sheet.height // 2,
                            (col + 1) * sheet.width // 3, (row + 1) * sheet.height // 2))
                for row in range(2) for col in range(3)]
    fonts_dir = Path("/usr/share/fonts/truetype/dejavu")
    regular = lambda size: ImageFont.truetype(str(fonts_dir / "DejaVuSans.ttf"), size)
    heading = ImageFont.truetype(str(fonts_dir / "DejaVuSans-Bold.ttf"), 54)
    brand_font, body_font, small_font = regular(20), regular(20), regular(13)
    # A gradient keeps all text legible independently of the scene's brightness.
    mask = Image.new("L", (width, height))
    for x in range(width):
        opacity = 255 if x < 500 else int(255 * max(0, 1 - (x - 500) / 360))
        ImageDraw.Draw(mask).line((x, 0, x, height), fill=opacity)
    with tempfile.TemporaryDirectory(prefix="vainah-film-") as tmp:
        audio = narration(Path(tmp))
        process = subprocess.Popen([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", "-i", str(audio),
            "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "112k", "-t", "30", "-movflags", "+faststart",
            str(ASSETS / "vainah-intro-30.mp4")], stdin=subprocess.PIPE)

        def background(index, phase):
            scale = 1.03 + phase * .04
            side = round(height * scale)
            picture = ImageOps.fit(pictures[index], (side, side), method=Image.Resampling.LANCZOS)
            layer = Image.new("RGB", (width, height), (16, 22, 18))
            layer.paste(picture, (width - side + round(phase * 12), -(side - height) // 2))
            return Image.composite(Image.new("RGB", (width, height), (16, 22, 18)), layer, mask)

        for frame in range(30 * fps):
            time = frame / fps
            index = min(5, int(time // 5))
            local = time - index * 5
            image = background(index, local / 5)
            if index and local < .45:
                image = Image.blend(background(index - 1, 1), image, local / .45)
            draw = ImageDraw.Draw(image)
            title, label, description, _ = SCENES[index]
            fade = min(1, local * 3)
            offset = round((1 - fade) * 14)
            ink = tuple(round(16 + (value - 16) * fade) for value in (240, 241, 233))
            draw.text((64, 50), "V / VAINAH VPN", font=brand_font, fill=accent)
            draw.text((64, 188 + offset), label, font=small_font, fill=accent)
            draw.multiline_text((60, 238 + offset), title, font=heading, fill=ink, spacing=8)
            draw.text((64, 411 + offset), description, font=body_font, fill=(177, 192, 166))
            if index == 5:
                draw.rounded_rectangle((64, 478, 334, 532), radius=12, fill=accent)
                draw.text((82, 494), "Попробовать бесплатно", font=regular(18), fill=(20, 30, 17))
            draw.text((64, 625), f"0{index + 1} / 06", font=small_font, fill=accent)
            draw.text((160, 625), "ТВОЁ СОЕДИНЕНИЕ. ТВОИ ПРАВИЛА.", font=small_font, fill=(155, 174, 145))
            for dot in range(6):
                x = 64 + dot * 30
                draw.line((x, 670, x + 20, 670), fill=accent if dot <= index else (65, 80, 59), width=3)
            if frame == fps:
                image.save(ASSETS / "vainah-intro-30-poster.jpg", quality=92)
            process.stdin.write(image.tobytes())
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("Video encoding failed")
    captions = ["WEBVTT", ""]
    for index, (_, _, _, voice) in enumerate(SCENES):
        captions += [str(index + 1),
                     f"00:00:{index * 5:02d}.000 --> 00:00:{(index + 1) * 5:02d}.000", voice, ""]
    (ASSETS / "vainah-intro-30-ru.vtt").write_text("\n".join(captions).rstrip() + "\n")
    print("Created 30-second video with six illustrated scenes, narration and captions")


if __name__ == "__main__":
    render()
