from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .assets import Assets
from .models import Project, Shot, StudioError, selected_candidate


def dimensions(resolution: str, aspect: str) -> tuple[int, int]:
    short = int(resolution)
    return (short, round(short*16/9)//2*2) if aspect == "9:16" else (round(short*16/9)//2*2, short) if aspect == "16:9" else (short, short)


class Media:
    def __init__(self, assets: Assets):
        self.assets = assets

    def run(self, args: list[str], work: Path, timeout: int = 600):
        try:
            result = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args], cwd=work, capture_output=True, timeout=timeout)
        except FileNotFoundError:
            raise StudioError("本机未安装 FFmpeg", "ffmpeg_missing", 409)
        if result.returncode:
            # No user script is run. ffmpeg arguments and filter graph are generated here.
            (work/"ffmpeg-error.txt").write_bytes(result.stderr[-16000:])
            raise StudioError("本地媒体处理失败，日志已保存在任务目录", "media_failed", 409)

    def local_clip(self, p: Project, shot: Shot, resolution: str, work: Path, motion: str='none') -> dict:
        work.mkdir(parents=True, exist_ok=True)
        out = work/"clip.mp4"
        width, height = dimensions(resolution, p.aspect)
        filt = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30"
        if shot.source_video_id:
            source = self.assets.path(shot.source_video_id)
            meta = self.assets.db.asset(shot.source_video_id)["metadata"]
            interval=next((r for r in p.source_ranges if r.id==shot.source_range_id),None)
            start=interval.start if interval else 0
            if meta.get("duration", 0)+.001 < start+shot.duration:
                raise StudioError("原始视频短于镜头目标，请调整时长，不自动循环素材")
            args = ["-ss",str(start),"-i", str(source)]
            if self.assets.db.asset(shot.source_video_id)['mime'].startswith('audio/'):
                args=['-f','lavfi','-i',f'color=c=0x20251f:s={width}x{height}:r=30']
            source_id = shot.source_video_id
        else:
            selected = next((selected_candidate(a) for a in shot.anchors if selected_candidate(a)), None)
            if selected is None:
                raise StudioError("没有采用图，不能合成本地镜头")
            source_id = selected.asset_id
            args = ["-loop", "1", "-i", str(self.assets.path(source_id))]
        if not shot.source_video_id and motion=='push_in':
            frames=max(2,round(shot.duration*30))
            filt+=f",zoompan=z='1+0.035*on/{frames-1}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={width}x{height}:fps=30"
        self.run([*args, "-t", str(shot.duration), "-vf", filt, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], work)
        return self.assets.ingest_path(out, shot.title+".mp4", {"production": "local", "source_asset_id": source_id, "output_resolution": resolution})

    def normalize_video(self, source_id: str, p: Project, shot: Shot, resolution: str, work: Path) -> dict:
        meta = self.assets.db.asset(source_id)["metadata"]
        if meta.get("duration", 0)+0.1 < shot.duration:
            raise StudioError("生成视频短于镜头目标，已保留原产物，请调整制作方案")
        original = shot.source_video_id
        original_range = shot.source_range_id
        shot.source_video_id = source_id
        shot.source_range_id = None
        try:
            return self.local_clip(p, shot, resolution, work)
        finally:
            shot.source_video_id = original
            shot.source_range_id = original_range

    def stitch_narration(self, p: Project, cue_assets: list[tuple[str,str]], work: Path) -> dict:
        args, filters, labels = [], [], []
        total = sum(s.duration for s in p.shots)
        for index, (cue_id, asset_id) in enumerate(cue_assets):
            cue = next(c for c in p.audio.narration if c.id == cue_id)
            actual = self.assets.db.asset(asset_id)["metadata"].get("duration", 0)
            if actual > cue.duration + .1:
                raise StudioError(f"旁白片段超过预留时长（{actual:.1f}s / {cue.duration:.1f}s），请调整语速或时间轨；音频原件已保存", "voice_timing", 409)
            args += ["-i", str(self.assets.path(asset_id))]
            label = f"voice{index}"
            filters.append(f"[{index}:a]aresample=48000,adelay={int(cue.start*1000)}:all=1[{label}]")
            labels.append("["+label+"]")
        if not labels:
            raise StudioError("没有旁白音轨")
        filters.append("".join(labels)+f"amix=inputs={len(labels)}:normalize=0,apad,atrim=duration={total}[voice]")
        output = work/"narration.wav"
        self.run([*args, "-filter_complex", ";".join(filters), "-map", "[voice]", "-c:a", "pcm_s16le", str(output)], work)
        return self.assets.ingest_path(output, "旁白时间轨.wav", {"cue_assets": cue_assets})

    def subtitle_image(self, text: str, width: int, height: int, path: Path):
        font_path = next((p for p in [Path("/System/Library/Fonts/PingFang.ttc"), Path("/System/Library/Fonts/Supplemental/Songti.ttc"), Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")] if p.exists()), None)
        if font_path is None:
            raise StudioError("缺少中文字体，请安装 Noto Sans CJK 或配置本机字体", "font_missing", 409)
        font = ImageFont.truetype(str(font_path), max(20, width//24))
        lines, line = [], ""
        for char in text:
            if char == "\n" or (font.getlength(line+char) > width*.84 and char not in "，。！？；：、,.!?;:…）】》」』”’") :
                lines.append(line); line = "" if char == "\n" else char
            else:
                line += char
        if line:
            lines.append(line)
        if len(lines)>4:
            raise StudioError("单条字幕过长，请拆成更短的时间片段", "subtitle_too_long", 409)
        im = Image.new("RGBA", (width, height), (0,0,0,0))
        draw = ImageDraw.Draw(im)
        lh = int(font.size*1.5)
        y = int(height*.87)-len(lines)*lh
        for text_line in lines:
            x = (width-font.getlength(text_line))/2
            draw.text((x,y),text_line,font=font,fill="white",stroke_width=2,stroke_fill=(0,0,0,220))
            y += lh
        im.save(path)

    def render(self, p: Project, work: Path) -> dict:
        work.mkdir(parents=True, exist_ok=True)
        total = sum(s.duration for s in p.shots)
        width, height = dimensions(p.route.resolution, p.aspect)
        entries = []
        for i, shot in enumerate(p.shots):
            dest = work/f"segment-{i}.mp4"
            shutil.copyfile(self.assets.path(shot.clip_asset_id), dest)
            entries.append(f"file '{dest.name}'\nduration {shot.duration:.9f}")
        (work/"segments.txt").write_text("\n".join(entries)+"\n")
        picture = work/"picture.mp4"
        self.run(["-f", "concat", "-safe", "0", "-i", "segments.txt", "-c", "copy", str(picture)], work)
        args, filters = ["-i", str(picture)], []
        video_label = "0:v"
        input_index = 1
        for i, cue in enumerate(p.audio.subtitles):
            if not cue.text.strip():
                continue
            if cue.start+cue.duration > total+.1:
                raise StudioError("字幕超出成片时长，请调整时间轨")
            overlay = work/f"subtitle-{i}.png"
            self.subtitle_image(cue.text, width, height, overlay)
            args += ["-i", str(overlay)]
            new_label = f"sub{i}"
            filters.append(f"[{video_label}][{input_index}:v]overlay=0:0:eof_action=repeat:enable='between(t,{cue.start},{cue.start+cue.duration})'[{new_label}]")
            video_label = new_label; input_index += 1
        audio_labels = []
        voice_label, music_label = None, None
        for field, gain in [("narration_asset_id",1), ("music_asset_id",p.audio.music_gain)]:
            asset_id = getattr(p.audio,field)
            if not asset_id:
                continue
            args += ["-i", str(self.assets.path(asset_id))]
            label = f"a{input_index}"
            filters.append(f"[{input_index}:a]aresample=48000,volume={gain},apad,atrim=duration={total}[{label}]")
            if field=='narration_asset_id':voice_label=label
            else:music_label=label
            audio_labels.append("["+label+"]"); input_index += 1
        if p.audio.duck_music and voice_label and music_label:
            filters.append(f'[{voice_label}]asplit=2[voice_mix][voice_side]')
            filters.append(f'[{music_label}][voice_side]sidechaincompress=threshold=0.02:ratio=6:attack=20:release=250[music_ducked]')
            audio_labels=['[voice_mix]','[music_ducked]']
        for effect in p.audio.effects:
            args += ['-i',str(self.assets.path(effect.asset_id))]
            label=f'effect{input_index}'
            filters.append(f'[{input_index}:a]atrim=duration={effect.duration},asetpts=PTS-STARTPTS,aresample=48000,volume={effect.gain},adelay={int(effect.start*1000)}:all=1[{label}]')
            audio_labels.append('['+label+']');input_index+=1
        if not p.audio.mute_native_audio:
            offset = 0.0
            for shot in p.shots:
                original = shot.source_video_id or shot.source_generated_asset_id
                if original and self.assets.db.asset(original)["metadata"].get("has_audio"):
                    args += ["-i", str(self.assets.path(original))]
                    label = f"native{input_index}"
                    interval=next((r for r in p.source_ranges if r.id==shot.source_range_id),None)
                    start=interval.start if interval else 0
                    filters.append(f"[{input_index}:a]atrim=start={start}:duration={shot.duration},asetpts=PTS-STARTPTS,aresample=48000,adelay={int(offset*1000)}:all=1[{label}]")
                    audio_labels.append("["+label+"]"); input_index += 1
                offset += shot.duration
        if audio_labels:
            filters.append("".join(audio_labels)+f"amix=inputs={len(audio_labels)}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,atrim=duration={total}[audio]")
        if filters:
            args += ["-filter_complex", ";".join(filters)]
        args += ["-map", f"[{video_label}]" if video_label != "0:v" else "0:v"]
        args += ["-map","[audio]","-c:a","aac","-b:a","192k","-ar","48000"] if audio_labels else ["-an"]
        out = work/"final.mp4"
        self.run([*args,"-t",str(total),"-c:v","libx264","-preset","veryfast","-crf","19","-r","30","-pix_fmt","yuv420p","-movflags","+faststart",str(out)],work)
        result = self.assets.ingest_path(out,p.name+".mp4",{"production":"local_assembly","resolution":p.route.resolution,"aspect":p.aspect})
        probe = result["metadata"]
        if abs(probe.get("duration",0)-total)>.25 or probe.get("width") != width or probe.get("height") != height:
            raise StudioError("合成后的时长或尺寸校验未通过", "render_validation", 409)
        return result
