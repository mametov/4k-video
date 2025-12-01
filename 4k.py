import os
import subprocess
import sys
import shlex
import re
import shutil

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.join(BASE_DIR, "app")
TMP_IN = os.path.join(APP_DIR, "tmp", "in")
TMP_OUT = os.path.join(APP_DIR, "tmp", "out")
SOUND_FILE = os.path.join(APP_DIR, "sound.mp3")
FINAL_VIDEO = os.path.join(APP_DIR, "final.mp4")
FINAL_VIDEO_2PASS = os.path.join(APP_DIR, "final_target.mp4")

def check_ffmpeg():
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("ffmpeg/ffprobe не найдены. Установите ffmpeg перед запуском.")
        sys.exit(1)

def ensure_dirs():
    for path in [TMP_IN, TMP_OUT]:
        os.makedirs(path, exist_ok=True)

def run_cmd_stream(cmd):
    process = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        yield line
    process.wait()
    return process.returncode

def ffprobe_value(cmd):
    res = subprocess.run(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return res.stdout.strip()

def extract_audio(video_file):
    print("Extracting audio...", end=" ")
    cmd = f'ffmpeg -hide_banner -loglevel error -y -i "{video_file}" -q:a 0 -map a "{SOUND_FILE}"'
    for _ in run_cmd_stream(cmd):
        pass
    print("\033[92mDone\033[0m")

def get_video_info(video_file):
    width = ffprobe_value(f'ffprobe -v error -select_streams v:0 -show_entries stream=width -of default=noprint_wrappers=1:nokey=1 "{video_file}"')
    height = ffprobe_value(f'ffprobe -v error -select_streams v:0 -show_entries stream=height -of default=noprint_wrappers=1:nokey=1 "{video_file}"')
    fps_str = ffprobe_value(f'ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 "{video_file}"')
    duration_str = ffprobe_value(f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{video_file}"')

    try:
        w = int(width)
        h = int(height)
    except:
        w, h = None, None

    try:
        num, den = fps_str.split('/')
        fps = float(num) / float(den) if float(den) != 0 else float(num)
    except:
        fps = 30.0

    try:
        duration = float(duration_str)
    except:
        duration = None

    return w, h, fps, duration

def get_total_frames(video_file):
    out = ffprobe_value(f'ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of default=nokey=1:noprint_wrappers=1 "{video_file}"')
    try:
        return int(out)
    except:
        w, h, fps, duration = get_video_info(video_file)
        if fps and duration:
            return int(fps * duration)
        return None

def extract_frames(video_file):
    total_frames = get_total_frames(video_file)
    w, h, _, _ = get_video_info(video_file)

    frame_pattern = os.path.join(TMP_IN, "%d.jpg")
    cmd = f'ffmpeg -hide_banner -loglevel warning -stats -y -i "{video_file}" -q:v 1 "{frame_pattern}"'
    proc = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    last_frame = 0
    for line in proc.stdout:
        m = re.search(r'frame=\s*(\d+)', line)
        if m:
            last_frame = int(m.group(1))
            if total_frames:
                print(f"Extracting frames ({last_frame} from {total_frames})", end="\r")

    proc.wait()
    print(f"\033[92mDone\033[0m (Total frames: {last_frame}, Resolution: {w}x{h})")
    return w, h, last_frame

def target_4k_dims(src_w, src_h):
    if src_w is None or src_h is None:
        return 3840, 2160
    if src_w >= src_h:
        return 3840, 2160
    else:
        return 2160, 3840

def upscale_to_4k(frame_count, src_w, src_h):
    tgt_w, tgt_h = target_4k_dims(src_w, src_h)
    print(f"Upscaling frames to {tgt_w}x{tgt_h}...")

    frame_in = os.path.join(TMP_IN, "%d.jpg")
    frame_out = os.path.join(TMP_OUT, "%d.jpg")
    vf = f'scale={tgt_w}:{tgt_h}:force_original_aspect_ratio=decrease,pad={tgt_w}:{tgt_h}:(ow-iw)/2:(oh-ih)/2:black'
    cmd = f'ffmpeg -hide_banner -loglevel warning -stats -y -i "{frame_in}" -vf "{vf}" -q:v 1 "{frame_out}"'
    proc = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    current = 0
    for line in proc.stdout:
        m = re.search(r'frame=\s*(\d+)', line)
        if m:
            current = int(m.group(1))
            print(f"Upscaling frames ({current} from {frame_count})", end="\r")

    proc.wait()
    print(f"\033[92mDone\033[0m (Frames upscaled to {tgt_w}x{tgt_h})")
    return tgt_w, tgt_h

def cleanup_tmp_in():
    print("Cleaning tmp/in...", end=" ")
    for f in os.listdir(TMP_IN):
        try:
            os.remove(os.path.join(TMP_IN, f))
        except:
            pass
    print("\033[92mDone\033[0m")

def cleanup_tmp_out_and_sound():
    print("Cleaning tmp/out and sound...", end=" ")
    for f in os.listdir(TMP_OUT):
        try:
            os.remove(os.path.join(TMP_OUT, f))
        except:
            pass
    if os.path.exists(SOUND_FILE):
        try:
            os.remove(SOUND_FILE)
        except:
            pass
    print("\033[92mDone\033[0m")

def assemble_video_with_progress(fps):
    print("Assembling final video...")
    cmd = f'ffmpeg -hide_banner -loglevel warning -stats -y -framerate {fps} -i "{TMP_OUT}/%d.jpg" -i "{SOUND_FILE}" -c:v libx264 -pix_fmt yuv420p -c:a aac "{FINAL_VIDEO}"'
    proc = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    last_frame = 0
    for line in proc.stdout:
        m = re.search(r'frame=\s*(\d+)', line)
        if m:
            last_frame = int(m.group(1))
            print(f"Assembling video (frame {last_frame})", end="\r")

    proc.wait()
    print("\033[92mDone\033[0m (Video assembled)")

def two_pass_size_target(target_size_bytes, fps, duration):
    if duration is None or duration <= 0:
        print("Duration unknown; skipping size targeting.")
        return False

    audio_br_kbps = 128
    target_bitrate_bps = max(1, int((target_size_bytes * 8) / duration))
    video_bitrate_bps = max(1, target_bitrate_bps - audio_br_kbps * 1000)
    video_bitrate_k = max(1, video_bitrate_bps // 1000)

    print(f"Targeting size: ~{target_size_bytes/1024/1024:.2f} MB, video bitrate ~{video_bitrate_k}k")

    # Pass 1
    cmd1 = f'ffmpeg -hide_banner -loglevel error -y -i "{FINAL_VIDEO}" -c:v libx264 -b:v {video_bitrate_k}k -maxrate {video_bitrate_k}k -bufsize {2*video_bitrate_k}k -pass 1 -an -f mp4 NUL' if os.name == "nt" else \
           f'ffmpeg -hide_banner -loglevel error -y -i "{FINAL_VIDEO}" -c:v libx264 -b:v {video_bitrate_k}k -maxrate {video_bitrate_k}k -bufsize {2*video_bitrate_k}k -pass 1 -an -f mp4 /dev/null'
    subprocess.run(shlex.split(cmd1), check=False)

    # Pass 2
    cmd2 = f'ffmpeg -hide_banner -loglevel error -y -i "{FINAL_VIDEO}" -c:v libx264 -b:v {video_bitrate_k}k -maxrate {video_bitrate_k}k -bufsize {2*video_bitrate_k}k -pass 2 -c:a copy "{FINAL_VIDEO_2PASS}"'
    subprocess.run(shlex.split(cmd2), check=False)

    # очистка статистики двух проходов
    for f in ["ffmpeg2pass-0.log", "ffmpeg2pass-0.log.mbtree"]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except:
                pass

    return os.path.exists(FINAL_VIDEO_2PASS)

def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py input.mp4")
        sys.exit(1)

    video_file = sys.argv[1]

    check_ffmpeg()
    ensure_dirs()

    # 1) Аудио
    extract_audio(video_file)

    # 2) Кадры
    src_w, src_h, frame_count = extract_frames(video_file)

    # 3) Апскейл до 4K
    tgt_w, tgt_h = upscale_to_4k(frame_count, src_w, src_h)

    # 4) Удаление tmp/in
    cleanup_tmp_in()

    # 5) Сборка финального видео
    _, _, fps, duration = get_video_info(video_file)
    assemble_video_with_progress(fps)

    # 6) Подгонка размера файла
    in_size = os.path.getsize(video_file)
    out_size = os.path.getsize(FINAL_VIDEO)
    scale_factor_area = (tgt_w * tgt_h) / (src_w * src_h)
    target_size = int(in_size * scale_factor_area)

    if abs(out_size - target_size) / target_size > 0.10:
        print(f"Retargeting file size (current ~{out_size/1024/1024:.2f} MB, target ~{target_size/1024/1024:.2f} MB)...")
        ok = two_pass_size_target(target_size, fps, duration)
        if ok:
            print("\033[92mDone\033[0m (Size targeted)")
        else:
            print("Size targeting failed; keeping original assembled video.")
    else:
        print("\033[92mDone\033[0m (Size already near target)")

    # 7) Очистка tmp/out и sound.mp3
    cleanup_tmp_out_and_sound()

    print(f"Process finished. Target resolution: {tgt_w}x{tgt_h}. Source: {src_w}x{src_h}, Frames: {frame_count}.")

if __name__ == "__main__":
    main()
