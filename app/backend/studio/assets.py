from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
import os
import shutil
import subprocess
import time
import math
from contextlib import nullcontext
from pathlib import Path

from PIL import Image, ImageOps

from .database import Database, dumps
from .models import StudioError, uid


class Assets:
    MAX_BYTES = 512 * 1024 * 1024

    def __init__(self, db: Database):
        self.db = db

    def path(self, asset_id: str) -> Path:
        asset = self.db.asset(asset_id)
        p = (self.db.root / asset["path"]).resolve()
        if not p.is_relative_to(self.db.root / "assets") or not p.is_file():
            raise StudioError("素材文件不存在或超出资产目录", "asset_missing", 404)
        return p

    def probe(self, path: Path) -> dict:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, timeout=30)
        if result.returncode:
            raise StudioError("素材无法解码，请检查文件格式", "invalid_media")
        data = json.loads(result.stdout)
        video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
        return {"duration": float(data.get("format", {}).get("duration", 0)), "width": video.get("width") if video else None,
                "height": video.get("height") if video else None, "has_audio": bool(audio), "has_video": bool(video)}

    def ingest(self, data: bytes, name: str, mime: str = "", metadata: dict | None = None, connection=None) -> dict:
        if not data or len(data) > self.MAX_BYTES:
            raise StudioError("文件为空或超过 512 MB", "asset_size")
        name = Path(name).name[:200] or "asset"
        content_hash = hashlib.sha256(data).hexdigest()
        meta = dict(metadata or {})
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > 60_000_000:
                    raise StudioError("图片像素过大", "asset_size")
                mime = Image.MIME.get(image.format, "image/png")
                ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime)
                if ext is None:
                    raise StudioError("请使用 PNG、JPG 或 WebP 图片")
                meta.update(width=image.width, height=image.height)
        except StudioError:
            raise
        except Exception:
            if not (mime.startswith("video/") or mime.startswith("audio/")):
                mime = mimetypes.guess_type(name)[0] or mime
            if not mime.startswith(("video/", "audio/")):
                raise StudioError("仅支持图片、音频和视频素材", "invalid_media")
            ext = ".mp4" if mime.startswith("video/") else ".wav" if "wav" in mime else ".mp3"
        with (nullcontext(connection) if connection is not None else self.db.transaction()) as c:
            existing = c.execute("SELECT id FROM assets WHERE hash=? LIMIT 1", (content_hash,)).fetchone()
            if existing:
                return self.db.asset(existing[0], c)
        directory = self.db.root / "assets" / content_hash[:2]
        directory.mkdir(exist_ok=True)
        dest = directory / (content_hash + ext)
        temp = directory / (uid() + ".part")
        try:
            temp.write_bytes(data)
            if not mime.startswith("image/"):
                meta.update(self.probe(temp))
            os.replace(temp, dest)
        finally:
            temp.unlink(missing_ok=True)
        with (nullcontext(connection) if connection is not None else self.db.transaction()) as c:
            existing = c.execute("SELECT id FROM assets WHERE hash=? LIMIT 1", (content_hash,)).fetchone()
            if existing:
                return self.db.asset(existing[0], c)
            asset_id = uid()
            c.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?)", (asset_id, content_hash, str(dest.relative_to(self.db.root)), mime, name, len(data), dumps(meta), time.time()))
            return self.db.asset(asset_id, c)

    def crop(self, asset_id, box, connection=None):
        values=[box.get(k) for k in ('x','y','width','height')]
        if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in values):raise StudioError('裁剪区域需要有效比例数值')
        x,y,w,h=values
        if x<0 or y<0 or w<=0 or h<=0 or x+w>1.000001 or y+h>1.000001:raise StudioError('裁剪区域超出图片边界')
        source=self.db.asset(asset_id,connection)
        if not source['mime'].startswith('image/'):raise StudioError('只能裁剪图片')
        with Image.open(self.path(asset_id)) as im:
            im=ImageOps.exif_transpose(im)
            rectangle=(round(x*im.width),round(y*im.height),round((x+w)*im.width),round((y+h)*im.height))
            if rectangle[2]-rectangle[0]<16 or rectangle[3]-rectangle[1]<16:raise StudioError('裁剪区域过小')
            out=io.BytesIO();im.crop(rectangle).save(out,'PNG')
        return self.ingest(out.getvalue(),'原图局部_'+source['name'],'image/png',{'production':'local_crop','source_asset_id':asset_id,'crop_box':box,'pixel_box':rectangle},connection=connection)

    def ingest_path(self, path: Path, name: str | None = None, metadata: dict | None = None) -> dict:
        return self.ingest(path.read_bytes(), name or path.name, mimetypes.guess_type(path.name)[0] or "", metadata)

    def image_data_url(self, asset_id: str, *, thumbnail: bool = False) -> str:
        asset = self.db.asset(asset_id)
        if not asset["mime"].startswith("image/"):
            raise StudioError("所选参考不是图片")
        path = self.path(asset_id)
        if thumbnail:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((1024, 1024))
                buf = io.BytesIO(); im.save(buf, "JPEG", quality=85)
                data, mime = buf.getvalue(), "image/jpeg"
        else:
            data, mime = path.read_bytes(), asset["mime"]
        return "data:" + mime + ";base64," + base64.b64encode(data).decode()

    def list(self) -> list[dict]:
        with self.db.connect() as c:
            rows = c.execute("SELECT id FROM assets ORDER BY created DESC").fetchall()
            return [self.db.asset(r[0], c) for r in rows]

    def frame(self, asset_id: str, seconds: float, work: Path) -> str:
        output = work / (uid()+".jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(seconds), "-i", str(self.path(asset_id)), "-frames:v", "1", "-vf", "scale=640:-2", str(output)], check=True, capture_output=True, timeout=60)
        return self.ingest_path(output, "审片抽帧.jpg", {"source_asset": asset_id, "seconds": seconds})["id"]


def media_environment() -> dict:
    return {"ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe")}
