"""Dev tool: render sample fax originals (PNG) for the prototype data."""
import random
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent.parent / "app" / "seed_data" / "faxes"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
W, H = 1240, 1754


from PIL import features

RAQM = features.check("raqm")


def ar(t):
    return t if RAQM else get_display(arabic_reshaper.reshape(t))


KW = {"direction": "rtl"} if RAQM else {}


def fax(name, no, date, sender, to, subject, lines, prio):
    img = Image.new("L", (W, H), 250)
    d = ImageDraw.Draw(img)
    f, fb, fh, fs = (ImageFont.truetype(FONT, 30), ImageFont.truetype(FONT_B, 32), ImageFont.truetype(FONT_B, 42), ImageFont.truetype(FONT, 22))
    d.text((40, 20), f"FAX  {date}   P.1/1", font=fs, fill=60)

    def r(y, text, font=f, x=W - 90):
        t = ar(text)
        d.text((x - d.textlength(t, font=font, **KW), y), t, font=font, fill=20, **KW)

    r(90, "سلاح الإشارة", fh)
    r(150, "فوج إنشاءات خطية ثقيلة — قسم المشروعات والعمليات", fb)
    d.line((80, 215, W - 80, 215), fill=30, width=3)
    r(250, f"رقم الفاكس: {no}", fb)
    r(300, f"التاريخ: {date}")
    r(350, f"من: {sender}")
    r(400, f"إلى: {to}")
    r(450, f"درجة الأهمية: {prio}", fb)
    d.line((80, 510, W - 80, 510), fill=120, width=1)
    r(540, f"الموضوع: {subject}", fb)
    y = 620
    for ln in lines:
        r(y, ln)
        y += 58
    r(y + 80, "والأمر معروض للتفضل بالإحاطة واتخاذ اللازم")
    r(y + 200, "التوقيع: ............................", fb)
    d.rectangle((90, y + 170, 330, y + 300), outline=90, width=3)
    d.text((120, y + 215), "STAMP", font=fb, fill=110)
    for _ in range(9000):
        img.putpixel((random.randrange(W), random.randrange(H)), random.randrange(80, 200))
    img = img.filter(ImageFilter.GaussianBlur(0.6)).point(lambda p: 0 if p < 140 else 255).convert("1")
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / name, optimize=True)


fax("fax_0412.png", "ف/2026/0412", "2026/11/22", "غرفة عمليات الاتصالات", "قسم المشروعات", "قطع كابل ألياف — الأوتوستراد أمام محطة المياه",
    ["نحيط سيادتكم علمًا بحدوث انقطاع كامل للخدمة على مسار الأوتوستراد", "نتيجة أعمال حفر لجهة خارجية أمام محطة مياه المعادي.",
     "المطلوب: إصلاح فوري وإعادة الخدمة خلال 6 ساعات.", "مع موافاتنا بسبب العطل والإجراءات المتخذة."], "حرجة")
fax("fax_0413.png", "ف/2026/0413", "2026/11/22", "قيادة قطاع الاتصالات", "قسم المشروعات", "قطع كابل — صلاح سالم بسبب أعمال شركة الغاز",
    ["تلف كابل ألياف 24 شعرة أثناء أعمال حفر شركة الغاز", "بشارع صلاح سالم بجوار نفق العباسية.", "المطلوب: إصلاح العطل ومخاطبة شركة الغاز رسميًا."], "عالية")
fax("fax_0414.png", "ف/2026/0414", "2026/11/21", "قيادة المنطقة المركزية", "قسم المشروعات", "إنشاء خط ألياف جديد",
    ["مطلوب مد خط ألياف 24 شعرة من عقدة مدينة نصر", "إلى مبنى القيادة الجديد بالتجمع الخامس.",
     "المطلوب: حصر الاحتياجات من الخامات والمعدات", "والزمن التقديري للتنفيذ خلال 48 ساعة."], "عادية")
fax("fax_0398.png", "ف/2026/0398", "2026/11/19", "شركة مياه الشرب بالقاهرة", "قسم المشروعات", "طلب تنسيق قبل أعمال حفر",
    ["تعتزم الشركة تنفيذ خط مياه رئيسي بطول 400 م", "بطريق الأوتوستراد — قطاع البساتين.", "نرجو تحديد مسار كوابل الاتصالات القائمة",
     "وإرسال مندوب قبل بدء الحفر والرد كتابيًا."], "عالية")
print("ok")
