# -*- coding: utf-8 -*-
"""Build the project video: real screenshots + Arabic narration + branded overlays."""
import asyncio, os, re, subprocess, textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

ASSETS = Path('/mnt/f/aaaaa/video_assets')
AUD = Path('/tmp/vidaudio'); AUD.mkdir(exist_ok=True)
OUT_DIR = Path('/tmp/vidseg'); OUT_DIR.mkdir(exist_ok=True)

import imageio_ffmpeg
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

W, H = 1280, 720
NAVY = (15, 31, 61)
NAVY2 = (22, 43, 82)
GOLD = (245, 185, 65)
SKY = (219, 234, 254)
WHITE = (255, 255, 255)
MUTED = (148, 163, 184)

FONT_B = '/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf'
FONT_R = '/usr/share/fonts/truetype/noto/NotoKufiArabic-Regular.ttf'


def ar(text):
    return get_display(arabic_reshaper.reshape(text))


def fit_text(draw, text, font_path, max_w, start=40):
    size = start
    while size > 14:
        f = ImageFont.truetype(font_path, size)
        if draw.textlength(ar(text), font=f) <= max_w:
            return f
        size -= 2
    return ImageFont.truetype(font_path, 14)


def overlay(img_path, title, sub):
    """Return composited PIL image with bottom title bar."""
    im = Image.open(img_path).convert('RGB').resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(im, 'RGBA')
    # bottom gradient-ish bar
    bar_h = 120
    for i in range(bar_h):
        a = int(215 * (1 - i / bar_h))
        d.rectangle([0, H - bar_h + i, W, H - bar_h + i + 1], fill=(10, 20, 40, a))
    # accent line
    d.rectangle([0, H - bar_h - 3, W, H - bar_h], fill=GOLD + (255,))
    tf = fit_text(d, title, FONT_B, W - 120, 42)
    sf = ImageFont.truetype(FONT_R, 24)
    d.text((W - 50, H - bar_h + 26), ar(title), font=tf, fill=GOLD + (255,), anchor='ra')
    d.text((W - 50, H - bar_h + 78), ar(sub), font=sf, fill=SKY + (255,), anchor='ra')
    # small logo chip top-right
    d.rounded_rectangle([W - 250, 18, W - 30, 62], radius=10, fill=(10, 20, 40, 160))
    lf = ImageFont.truetype(FONT_B, 22)
    d.text((W - 42, 40), ar('نظام العمليات والمشروعات'), font=lf, fill=WHITE + (255,), anchor='ra')
    return im


def card(title, sub, big=None):
    im = Image.new('RGB', (W, H), NAVY)
    d = ImageDraw.Draw(im)
    # subtle grid-ish decoration
    for i in range(0, W, 80):
        d.line([(i, 0), (i, H)], fill=NAVY2 + (60,), width=1)
    d.rectangle([0, H - 140, W, H], fill=(10, 20, 40))
    d.rectangle([0, H - 143, W, H - 140], fill=GOLD)
    if big:
        bf = ImageFont.truetype(FONT_B, 110)
        d.text((W / 2, H / 2 - 90), ar(big), font=bf, fill=GOLD, anchor='mm')
    tf = fit_text(d, title, FONT_B, W - 300, 52)
    d.text((W / 2, H / 2 + (60 if big else -10)), ar(title), font=tf, fill=WHITE, anchor='mm')
    sf = ImageFont.truetype(FONT_R, 26)
    d.text((W / 2, H / 2 + (140 if big else 60)), ar(sub), font=sf, fill=SKY, anchor='mm')
    d.text((W / 2, H - 80), ar('محطة المشروعات + شاشة القائد'), font=ImageFont.truetype(FONT_R, 20),
           fill=MUTED, anchor='mm')
    return im


# ---------------- narration script ----------------
SCENES = [
    dict(img=None, card=('نظام إدارة', 'العمليات والمشروعات', '⚡'),
         title='البداية', sub='قصة نظام واحد — برنامجان',
         say='فيه كابل اتقطع الساعة اتنين الفجر، والإشارة وقعت، والتقرير وصل ورقة. إزاي النظام يعرف في ثانيتين؟ ده نظام إدارة العمليات والمشروعات — برنامجين شغالين مع بعض، من غير إنترنت.'),
    dict(img='01_station_dash.png', title='محطة المشروعات', sub='الشاشة الأولى — للمشغّل',
         say='دي محطة قسم المشروعات — أول شاشة للمشغّل. هنا بيرد على الفاكسات، ويتابع المؤشرات: وارد جديد، انتظار تنسيق، تنفيذ ميداني، وبلاغات حرجة.'),
    dict(img='02_station_faxes.png', title='الفاكسات الواردة', sub='بحث وفلاتر لكل العمليات',
         say='كل الفاكسات في قائمة واحدة — تقدر تبحث وتفلتر بالحالة والنوع والأولوية. دوس على أي سطر وتفتح شاشة العمل الخاصة بيه.'),
    dict(img='03_station_newfax.png', title='تسجيل فاكس جديد', sub='ملف مرفق + استخراج نص تلقائي',
         say='تسجيل فاكس جديد بسيط: رقم، نوع، عنوان، وملخص. وتقدر ترفق ملف الفاكس الأصلي — والنظام بيستخرج نصه تلقائيًا عشان تنسخه.'),
    dict(img='04_station_workbench.png', title='شاشة العمل', sub='خريطة الموقع + كل التفاصيل',
         say='شاشة العمل مقسومة: خريطة على الشمال لتحديد موقع العطل بالظبط، وتفاصيل على اليمين — الملخص التنفيذي، التقدير الفني، والاحتياجات.'),
    dict(img='05_station_estimate.png', title='التقدير الفني', sub='حساب تلقائي قابل للتعديل',
         say='محرك التقدير بيحسب لوحده: أطوال الكابلات، عدد اللحامات، ساعات العمل الميداني — وتقدر تعدّل أي رقم يدويًا قبل الحفظ.'),
    dict(img='06_station_original.png', title='الفاكس الأصلي', sub='محفوظ وآمن مع كل عملية',
         say='والفاكس الأصلي محفوظ مع كل عملية — تقدر تعاينه في أي وقت، وتستخرج نصه لو احتجت ترجعه للملخص.'),
    dict(img='07_command_map.png', title='شاشة القائد', sub='الخريطة العملياتية — القرار في عين واحدة',
         say='دي شاشة القائد — بتشوف بس اللي اتمرّر من المحطة. الخريطة بتنور المسارات والأعطال، والشريط العلوي بيلخص الموقف كله في لمحة.'),
    dict(img='10_command_detail.png', title='أوامر القيادة', sub='تصديق · أولوية · توجيه · اطلاع',
         say='افتح أي عملية — التفاصيل كاملة، وتقدر تصدّق كل بند احتياجات، أو تغيّر الأولوية، أو تبعت توجيه مكتوب يوصل للمشغّل فورًا.'),
    dict(img='08_command_ops.png', title='سجل العمليات', sub='كل الممررات بالتسلسل الزمني',
         say='سجل العمليات فيه كل الفاكسات اللي اتمررت — بالتسلسل الزمني والفلاتر. والبيانات المرجعية للمسارات والأطقم للعرض دايمًا.'),
    dict(img='09_command_ref.png', title='المزامنة', sub='كل ثانيتين — بلا إنترنت',
         say='المزامنة بتتم كل ثانيتين تلقائيًا — المحطة بتدفع التحديثات، والقائد بيسحبها ويأكد استلامها. ولو المحطة وقفت، القائد يفضل يعرض آخر موقف والمؤشر يحمر.'),
    dict(img=None, card=('جاهز', 'للتجربة', '▶'), title='الختام', sub='شغالين على أي جهازين',
         say='محطة المشروعات وشاشة القائد — شغالين محليًا على أي جهازين، بدون إنترنت، وبدون أي تثبيت complicated. دوس ستارت ولاين، وافتح البرنامج — وخلّي القرار يوصل في ثانيتين.'),
]


async def tts(text, path):
    import edge_tts
    c = edge_tts.Communicate(text, 'ar-EG-SalmaNeural', rate='+0%')
    await c.save(str(path))


def probe_dur(mp3):
    r = subprocess.run([FFMPEG, '-i', str(mp3)],
                       capture_output=True, text=True)
    m = re.search(r'Duration: (\d+):(\d+):([\d.]+)', r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 10.0


async def main():
    segs = []
    for i, sc in enumerate(SCENES, 1):
        tag = f'{i:02d}'
        mp3 = AUD / f'{tag}.mp3'
        if not mp3.exists():
            await tts(sc['say'], mp3)
        dur = probe_dur(mp3) + 0.6
        # composite frame
        if sc.get('img'):
            im = overlay(ASSETS / sc['img'], sc['title'], sc['sub'])
        else:
            t, b, g = sc['card']
            im = card(f'{t} {b}', sc['sub'], big=g)
        png = OUT_DIR / f'{tag}.png'
        im.save(png)
        # video segment with slow zoom
        frames = int(dur * 25) + 25
        vf = (f"scale=1600:900,zoompan=z='min(1+0.0009*on,1.14)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={W}x{H}:fps=25,format=yuv420p")
        seg = OUT_DIR / f'{tag}.mp4'
        cmd = [FFMPEG, '-y', '-loop', '1', '-i', str(png), '-i', str(mp3),
               '-vf', vf, '-t', f'{dur:.2f}', '-r', '25',
               '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21',
               '-c:a', 'aac', '-ar', '44100', '-ac', '2', '-b:a', '128k', '-shortest', str(seg)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print('FFMPEG FAIL', tag, r.stderr[-500:])
            # fallback: static
            cmd = [FFMPEG, '-y', '-loop', '1', '-i', str(png), '-i', str(mp3),
                   '-vf', f'scale={W}:{H},format=yuv420p', '-t', f'{dur:.2f}', '-r', '25',
                   '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21',
                   '-c:a', 'aac', '-ar', '44100', '-ac', '2', '-b:a', '128k', '-shortest', str(seg)]
            subprocess.run(cmd, check=True)
        segs.append(seg)
        print('seg', tag, f'{dur:.1f}s')

    lst = OUT_DIR / 'list.txt'
    lst.write_text(''.join(f"file '{s}'\n" for s in segs))
    final = '/mnt/f/aaaaa/عرض_المشروع.mp4'
    r = subprocess.run([FFMPEG, '-y', '-f', 'concat', '-safe', '0', '-i', str(lst),
                        '-c', 'copy', final], capture_output=True, text=True)
    if r.returncode != 0:
        subprocess.run([FFMPEG, '-y', '-f', 'concat', '-safe', '0', '-i', str(lst),
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21',
                        '-c:a', 'aac', '-ar', '44100', '-ac', '2', final], check=True)
    print('FINAL:', final)


asyncio.run(main())
