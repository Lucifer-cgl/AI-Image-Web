"""Local-only DreamShaper web application with persistent image history."""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import secrets
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
WEB_FILE = ROOT / "web" / "index.html"
MAX_BODY = 30 * 1024 * 1024
HISTORY_NAME = re.compile(r"^[A-Za-z0-9._-]+\.png$")


def contains_chinese(value: object) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(value or "")))


def split_translation_text(value: object, limit: int = 220) -> list[str]:
    text = str(value or "").strip()
    if len(text) <= limit:
        return [text] if text else []
    chunks: list[str] = []
    current = ""
    for piece in re.split(r"(?<=[。！？；，、\n])", text):
        while len(piece) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(piece[:limit])
            piece = piece[limit:]
        if current and len(current) + len(piece) > limit:
            chunks.append(current)
            current = piece
        else:
            current += piece
    if current:
        chunks.append(current)
    return chunks


def parse_output_size(value: object) -> tuple[int, int]:
    match = re.match(r"^(\d+)\s*[x*]\s*(\d+)$", str(value or ""))
    if not match:
        return 512, 512
    width, height = int(match.group(1)), int(match.group(2))
    if width < 256 or height < 256 or width > 1920 or height > 1920:
        raise ValueError("输出尺寸必须在 256 到 1920 像素之间")
    return width, height


def safe_generation_size(value: object) -> tuple[int, int]:
    width, height = parse_output_size(value)
    scale = min(1.0, 768 / max(width, height))
    return max(256, int(width * scale) // 8 * 8), max(256, int(height * scale) // 8 * 8)


def decode_image(value: object):
    from PIL import Image
    if not isinstance(value, str) or not value.startswith("data:image/"):
        return None
    raw = base64.b64decode(value.split(",", 1)[-1], validate=True)
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("原图不能超过 20MB")
    image = Image.open(io.BytesIO(raw))
    if image.width > 8192 or image.height > 8192 or image.width * image.height > 40_000_000:
        raise ValueError("原图尺寸过大")
    return image.convert("RGB")


def valid_history_name(value: str) -> str:
    name = unquote(value)
    if not HISTORY_NAME.fullmatch(name) or Path(name).name != name:
        raise ValueError("非法历史文件名")
    return name


def list_history(history_dir: Path) -> list[dict]:
    items = []
    if not history_dir.is_dir():
        return items
    for image in sorted(history_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True):
        meta_path = image.with_suffix(".json")
        meta = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
        items.append({
            "name": image.name,
            "url": "/history/" + quote(image.name),
            "created_at": meta.get("created_at") or datetime.fromtimestamp(image.stat().st_mtime).astimezone().isoformat(),
            "prompt": meta.get("prompt", ""),
            "translated_prompt": meta.get("translated_prompt", ""),
            "width": meta.get("width"),
            "height": meta.get("height"),
            "bytes": image.stat().st_size,
        })
    return items


class Runtime:
    def __init__(self, model: Path, translator: Path | None, history: Path):
        self.model_path = model
        self.translator_path = translator
        self.history_dir = history
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.image_pipe = None
        self.image_to_image_pipe = None
        self.translation_model = None
        self.translation_tokenizer = None
        self.image_lock = threading.Lock()
        self.translation_lock = threading.Lock()

    def health(self) -> dict:
        return {
            "ok": True,
            "mode": "image",
            "model": str(self.model_path.resolve()),
            "model_loaded": self.image_pipe is not None,
            "translation_available": bool(self.translator_path and (self.translator_path / "config.json").is_file()),
            "translation_model": str(self.translator_path.resolve()) if self.translator_path else None,
            "history_count": len(list_history(self.history_dir)),
        }

    def translate(self, value: object) -> str:
        text = str(value or "").strip()
        if not text or not contains_chinese(text):
            return text
        with self.translation_lock:
            if not self.translator_path or not self.translator_path.is_dir():
                raise RuntimeError("未安装中文提示词翻译模型")
            import torch
            from transformers import MarianMTModel, MarianTokenizer
            if self.translation_model is None:
                self.translation_tokenizer = MarianTokenizer.from_pretrained(self.translator_path, local_files_only=True)
                self.translation_model = MarianMTModel.from_pretrained(self.translator_path, local_files_only=True).to("cpu").eval()
            chunks = split_translation_text(text)
            encoded = self.translation_tokenizer(chunks, return_tensors="pt", padding=True, truncation=True, max_length=512)
            with torch.inference_mode():
                outputs = self.translation_model.generate(**encoded, max_length=512, num_beams=3)
            translated = self.translation_tokenizer.batch_decode(outputs, skip_special_tokens=True)
            result = " ".join(part.strip() for part in translated if part.strip())
            glossary = (
                (r"日漫|日本动漫|日系动漫|日式动漫", "Japanese anime style"),
                (r"动漫|二次元", "anime illustration"),
                (r"四宫格|四格图", "four-panel storyboard grid"),
                (r"角色设定图|人物设定图", "character design sheet"),
                (r"全身", "full body"),
                (r"中年男性|中年男人", "middle-aged man, masculine face"),
                (r"中年女性|中年女人", "middle-aged woman, feminine face"),
                (r"无人|没有人物|无人物", "no people"),
                (r"水墨|国画", "Chinese ink wash painting"),
            )
            tags = [tag for pattern, tag in glossary if re.search(pattern, text)]
            return ", ".join([result, *tags]) if tags else result

    def get_pipe(self, image_to_image: bool = False):
        import torch
        from diffusers import AutoPipelineForImage2Image, DiffusionPipeline
        if self.image_pipe is None:
            dtype = torch.float16 if torch.cuda.is_available() else torch.float32
            options = {
                "dtype": dtype,
                "local_files_only": True,
                "safety_checker": None,
                "feature_extractor": None,
                "requires_safety_checker": False,
            }
            if (self.model_path / "unet" / "diffusion_pytorch_model.fp16.safetensors").is_file():
                options["variant"] = "fp16"
            self.image_pipe = DiffusionPipeline.from_pretrained(self.model_path, **options)
            self.image_pipe = self.image_pipe.to("cuda" if torch.cuda.is_available() else "cpu")
            if torch.cuda.is_available():
                torch.backends.cuda.matmul.allow_tf32 = True
        if image_to_image:
            if self.image_to_image_pipe is None:
                self.image_to_image_pipe = AutoPipelineForImage2Image.from_pipe(self.image_pipe)
            return self.image_to_image_pipe
        return self.image_pipe

    def generate(self, body: dict) -> dict:
        with self.image_lock:
            return self._generate_locked(body)

    def _generate_locked(self, body: dict) -> dict:
        from PIL import ImageOps, Image
        import torch
        source_prompt = str(body.get("prompt") or "").strip()
        if not source_prompt:
            raise ValueError("画面描述不能为空")
        source_negative = str(body.get("negative_prompt") if "negative_prompt" in body else "")
        auto_translate = body.get("auto_translate", True) is not False
        translated_prompt = self.translate(source_prompt) if auto_translate and contains_chinese(source_prompt) else source_prompt
        translated_negative = self.translate(source_negative) if auto_translate and contains_chinese(source_negative) else source_negative
        output_width, output_height = parse_output_size(body.get("size"))
        width, height = safe_generation_size(body.get("size"))
        init_image = decode_image(body.get("init_image")) if body.get("init_image") else None
        pipe = self.get_pipe(init_image is not None)
        seed = int(body.get("seed") or secrets.randbelow(2**31 - 1))
        device = "cuda" if torch.cuda.is_available() else "cpu"
        options = {
            "prompt": translated_prompt,
            "negative_prompt": translated_negative,
            "num_inference_steps": max(4, min(30, int(body.get("steps") or 20))),
            "guidance_scale": max(1.0, min(20.0, float(body.get("guidance_scale") or 7.0))),
            "generator": torch.Generator(device=device).manual_seed(seed),
        }
        if init_image is None:
            options.update(width=width, height=height)
        else:
            strength = float(body.get("strength") if body.get("strength") is not None else 0.45)
            if strength < 0.10 or strength > 0.90:
                raise ValueError("修改强度必须在 0.10 到 0.90 之间")
            options.update(image=ImageOps.fit(init_image, (width, height)), strength=strength)
        started = time.monotonic()
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        result = pipe(**options).images[0]
        inference_seconds = round(time.monotonic() - started, 2)
        if result.size != (output_width, output_height):
            result = result.resize((output_width, output_height), Image.Resampling.LANCZOS)
        record = self.save_history(result, {
            "prompt": source_prompt,
            "translated_prompt": translated_prompt if translated_prompt != source_prompt else "",
            "negative_prompt": source_negative,
            "width": output_width,
            "height": output_height,
            "steps": options["num_inference_steps"],
            "seed": seed,
            "inference_seconds": inference_seconds,
        })
        output = io.BytesIO()
        result.save(output, format="PNG")
        print(json.dumps({"event": "image_completed", "seconds": inference_seconds, "seed": seed,
                          "peak_allocated_mb": round(torch.cuda.max_memory_allocated() / 1024**2) if torch.cuda.is_available() else 0}), flush=True)
        return {"created": int(time.time()), "data": [{
            "b64_json": base64.b64encode(output.getvalue()).decode("ascii"),
            "revised_prompt": translated_prompt if translated_prompt != source_prompt else None,
            "history": record,
            "seed": seed,
            "inference_seconds": inference_seconds,
        }]}

    def save_history(self, image, metadata: dict) -> dict:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{stamp}_{secrets.token_hex(4)}.png"
        path = self.history_dir / name
        image.save(path, format="PNG")
        metadata = {**metadata, "created_at": datetime.now().astimezone().isoformat()}
        path.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return next(item for item in list_history(self.history_dir) if item["name"] == name)

    def delete_history(self, raw_name: str) -> bool:
        name = valid_history_name(raw_name)
        image = self.history_dir / name
        metadata = image.with_suffix(".json")
        existed = image.is_file()
        if image.is_file():
            image.unlink()
        if metadata.is_file():
            metadata.unlink()
        return existed


class Handler(BaseHTTPRequestHandler):
    runtime: Runtime

    def log_message(self, fmt: str, *values):
        print(fmt % values, flush=True)

    def send_bytes(self, status: int, payload: bytes, content_type: str, extra_headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, status: int, value: object):
        self.send_bytes(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path in ("/", "/v1", "/v1/"):
                self.send_bytes(200, WEB_FILE.read_bytes(), "text/html; charset=utf-8")
            elif parsed.path == "/favicon.ico":
                self.send_bytes(204, b"", "image/x-icon")
            elif parsed.path == "/health":
                self.send_json(200, self.runtime.health())
            elif parsed.path == "/api/history":
                self.send_json(200, {"items": list_history(self.runtime.history_dir)})
            elif parsed.path.startswith("/history/"):
                name = valid_history_name(parsed.path.removeprefix("/history/"))
                path = self.runtime.history_dir / name
                if not path.is_file():
                    self.send_json(404, {"error": "历史图片不存在"})
                else:
                    headers = {"Content-Disposition": f'attachment; filename="{name}"'} if parsed.query == "download=1" else None
                    self.send_bytes(200, path.read_bytes(), "image/png", headers)
            else:
                self.send_json(404, {"error": "not found"})
        except Exception as exc:
            self.send_json(400, {"error": str(exc)})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        try:
            if not parsed.path.startswith("/api/history/"):
                self.send_json(404, {"error": "not found"})
                return
            deleted = self.runtime.delete_history(parsed.path.removeprefix("/api/history/"))
            self.send_json(200 if deleted else 404, {"ok": deleted})
        except Exception as exc:
            self.send_json(400, {"error": str(exc)})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0 or length > MAX_BODY:
                raise ValueError("请求内容过大")
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/v1/translations":
                source = str(body.get("input") or body.get("prompt") or "")
                self.send_json(200, {"source": source, "translation": self.runtime.translate(source)})
            elif self.path == "/v1/images/generations":
                self.send_json(200, self.runtime.generate(body))
            else:
                self.send_json(404, {"error": "not found"})
        except Exception as exc:
            traceback.print_exc()
            self.send_json(500, {"error": {"message": str(exc)}})


def parse_args():
    parser = argparse.ArgumentParser(description="Local DreamShaper web app")
    parser.add_argument("--model", required=True)
    parser.add_argument("--translator", default="")
    parser.add_argument("--history", default=str(ROOT / "data" / "history"))
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--open-browser", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    model = Path(args.model).resolve()
    if not (model / "model_index.json").is_file():
        raise SystemExit(f"模型目录无效：{model}")
    translator = Path(args.translator).resolve() if args.translator else None
    Handler.runtime = Runtime(model, translator, Path(args.history).resolve())
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Web page: {url}", flush=True)
    print(f"Model: {model}", flush=True)
    if args.open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()

