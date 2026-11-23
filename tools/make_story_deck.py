# -*- coding: utf-8 -*-
"""Story-driven Arabic RTL presentation for the Operations & Projects system."""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

# ---------- palette ----------
NAVY   = RGBColor(0x0F, 0x1F, 0x3D)
NAVY2  = RGBColor(0x16, 0x2B, 0x52)
BLUE   = RGBColor(0x1D, 0x4E, 0xD8)
SKY    = RGBColor(0xDB, 0xEA, 0xFE)
GOLD   = RGBColor(0xF5, 0xB9, 0x41)
GOLDL  = RGBColor(0xFE, 0xF3, 0xC7)
GREEN  = RGBColor(0x2E, 0x9E, 0x5B)
GREENL = RGBColor(0xD1, 0xFA, 0xE5)
RED    = RGBColor(0xD9, 0x45, 0x45)
REDL   = RGBColor(0xFE, 0xE2, 0xE2)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT  = RGBColor(0xF6, 0xF8, 0xFC)
CARD   = RGBColor(0xFF, 0xFF, 0xFF)
TXT    = RGBColor(0x1E, 0x29, 0x3B)
MUTED  = RGBColor(0x64, 0x74, 0x8B)
LINE   = RGBColor(0xE2, 0xE8, 0xF0)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
SW, SH = prs.slide_width, prs.slide_height


def rtl(para):
    pPr = para._p.get_or_add_pPr()
    pPr.set('rtl', '1')
    pPr.set('algn', 'r')


def txt(slide, x, y, w, h, lines, anchor=MSO_ANCHOR.TOP):
    """lines: list of (text, size, bold, color) or plain str."""
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    first = True
    for ln in lines:
        if isinstance(ln, str):
            ln = (ln, 18, False, TXT)
        text, size, bold, color = ln
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        rtl(p)
        p.alignment = PP_ALIGN.RIGHT
        p.space_after = Pt(6)
        r = p.add_run(); r.text = text
        r.font.size = Pt(size); r.font.bold = bold; r.font.name = 'Arial'; r.font.color.rgb = color
    return tb


def rect(slide, x, y, w, h, fill, line=None, round_=True, shadow=False):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if round_ else MSO_SHAPE.RECTANGLE,
                                 x, y, w, h)
    shp.fill.solid(); shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line; shp.line.width = Pt(1)
    shp.shadow.inherit = False
    if round_:
        try: shp.adjustments[0] = 0.08
        except Exception: pass
    return shp


def circle(slide, x, y, d, fill, line=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.OVAL, x, y, d, d)
    shp.fill.solid(); shp.fill.fore_color.rgb = fill
    if line is None: shp.line.fill.background()
    else: shp.line.color.rgb = line; shp.line.width = Pt(1.5)
    shp.shadow.inherit = False
    return shp


def bg(slide, color):
    return rect(slide, 0, 0, SW, SH, color, round_=False)


def fade(slide):
    """Add a subtle fade transition."""
    try:
        sld = slide.element
        trans = sld.makeelement(qn('p:transition'), {'spd': 'med'})
        fade_el = trans.makeelement(qn('p:fade'), {})
        trans.append(fade_el)
        clr = sld.find(qn('p:clrMapOvr'))
        if clr is not None:
            clr.addnext(trans)
        else:
            sld.append(trans)
    except Exception:
        pass


def card(slide, x, y, w, h, fill=CARD, line=LINE):
    return rect(slide, x, y, w, h, fill, line=line)


def chip(slide, x, y, w, text, fill, color=WHITE, size=15, h=Inches(0.5)):
    r = rect(slide, x, y, w, h, fill)
    tf = r.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]; rtl(p); p.alignment = PP_ALIGN.CENTER
    r_ = p.add_run(); r_.text = text
    r_.font.size = Pt(size); r_.font.bold = True; r_.font.name = 'Arial'; r_.font.color.rgb = color
    tf.margin_top = Inches(0.03); tf.margin_bottom = Inches(0.03)
    return r


# ================================================================ SLIDES
def s_hook():
    s = prs.slides.add_slide(BLANK)
    bg(s, NAVY)
    # gold accent bar
    rect(s, 0, Inches(5.6), SW, Inches(0.06), GOLD, round_=False)
    txt(s, Inches(1), Inches(1.3), Inches(11.3), Inches(4.4), [
        ('الساعة ٢ الفجر…', 22, True, GOLD),
        ('كابل اتقطع.', 54, True, WHITE),
        ('الإشارة وقعت.', 54, True, WHITE),
        ('والتقرير وصل… ورقة.', 40, True, SKY),
        ('', 14, False, WHITE),
        ('إزاي النظام يعرف في ثانيتين — ويأمرك إنت؟', 24, False, GOLD),
    ])
    txt(s, Inches(1), Inches(6.1), Inches(11), Inches(0.8), [
        ('نظام إدارة العمليات والمشروعات — محطة المشروعات + شاشة القائد', 15, False, MUTED if False else RGBColor(0x9F,0xB3,0xD1)),
    ])
    fade(s)


def s_problem():
    s = prs.slides.add_slide(BLANK)
    bg(s, LIGHT)
    txt(s, Inches(0.9), Inches(0.5), Inches(11.5), Inches(1.0), [
        ('المشكلة', 34, True, NAVY),
        ('كل دقيقة تأخير = خدمة وقعت أكتر', 17, False, MUTED),
    ])
    pains = [
        ('📄', 'القرار على ورق', 'فاكسات بتتكتب وتتخبى — مفيش ذاكرة'),
        ('⏳', 'ساعات ضايعة', 'تحديد الموقع والتقدير والاحتياجات يدوي'),
        ('🙈', 'القائد في الضلمة', 'مبيعرفش فين العطل ولا إيه محتاج'),
    ]
    x = Inches(0.9)
    for icon, head, sub in pains:
        card(s, x, Inches(2.1), Inches(3.6), Inches(3.4))
        txt(s, x + Inches(0.3), Inches(2.4), Inches(3), Inches(2.6), [
            (icon, 54, False, NAVY),
            (head, 24, True, NAVY),
            (sub, 15, False, MUTED),
        ])
        x += Inches(3.85)
    txt(s, Inches(0.9), Inches(6.0), Inches(11.5), Inches(0.8), [
        ('والأخطر: نفس المكان ممكن يتعطل تاني — ومحدش يفتكر', 18, True, RED),
    ])
    fade(s)


def s_solution():
    s = prs.slides.add_slide(BLANK)
    bg(s, LIGHT)
    txt(s, Inches(0.9), Inches(0.5), Inches(11.5), Inches(1.0), [
        ('الحل', 34, True, NAVY),
        ('برنامجان مستقلان — بيتكلموا في ثانيتين', 17, False, MUTED),
    ])
    # station card
    card(s, Inches(1.0), Inches(2.0), Inches(4.6), Inches(3.6), fill=NAVY)
    txt(s, Inches(1.3), Inches(2.3), Inches(4), Inches(3), [
        ('⚡ محطة قسم المشروعات', 26, True, GOLD),
        ('', 8, False, WHITE),
        ('📠 تسجيل الفاكس', 17, False, WHITE),
        ('📍 تحديد الموقع على الخريطة', 17, False, WHITE),
        ('🧮 التقدير الفني + الاحتياجات', 17, False, WHITE),
        ('📤 «حفظ وتمرير إلى القيادة»', 17, False, WHITE),
    ])
    # commander card
    card(s, Inches(7.7), Inches(2.0), Inches(4.6), Inches(3.6), fill=BLUE)
    txt(s, Inches(8.0), Inches(2.3), Inches(4), Inches(3), [
        ('🎖️ شاشة القائد', 26, True, GOLD),
        ('', 8, False, WHITE),
        ('🗺️ الخريطة العملياتية', 17, False, WHITE),
        ('🚨 تنبيه فوري للأعطال المتكررة', 17, False, WHITE),
        ('✅ أوامر خفيفة ترجع للمحطة', 17, False, WHITE),
        ('📋 سجل عمليات كامل', 17, False, WHITE),
    ])
    # sync arrows
    for yy in (Inches(3.2), Inches(3.8)):
        a = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(5.75), yy, Inches(1.85), Inches(0.42))
        a.fill.solid(); a.fill.fore_color.rgb = GOLD; a.line.fill.background(); a.shadow.inherit = False
        a.rotation = 180  # point left (RTL flow)
    txt(s, Inches(5.2), Inches(4.45), Inches(2.9), Inches(0.6), [
        ('مزامنة كل ثانيتين', 14, True, NAVY),
        ('أوامر فورية', 14, True, BLUE),
    ])
    chip(s, Inches(4.9), Inches(1.35), Inches(3.5), 'بدون إنترنت — شبكة محلية فقط', NAVY2, WHITE, 14)
    fade(s)


def s_numbers():
    s = prs.slides.add_slide(BLANK)
    bg(s, NAVY)
    txt(s, Inches(0.9), Inches(0.5), Inches(11.5), Inches(0.9), [
        ('بالأرقام', 34, True, GOLD),
    ])
    nums = [
        ('٢', 'ثانية', 'زمن وصول أي تحديث من المحطة للقائد'),
        ('٠', 'إنترنت', 'كل حاجة محلية — قاعدة بيانات على كل جهاز'),
        ('٢٢', 'اختبار', 'آلي ناجح — مزامنة وأوامر وتنبيهات'),
        ('٤', 'أوامر قائد', 'تصديق · أولوية · توجيه · اطلاع'),
    ]
    x = Inches(0.9)
    for big, lab, sub in nums:
        card(s, x, Inches(1.9), Inches(2.75), Inches(4.2), fill=NAVY2, line=RGBColor(0x2A,0x3D,0x66))
        txt(s, x, Inches(2.3), Inches(2.75), Inches(3.4), [
            (big, 88, True, GOLD),
            (lab, 24, True, WHITE),
            (sub, 14, False, RGBColor(0xBF,0xD0,0xEC)),
        ], anchor=MSO_ANCHOR.MIDDLE)
        x += Inches(3.0)
    txt(s, Inches(0.9), Inches(6.4), Inches(11.5), Inches(0.7), [
        ('والنتيجة: القرار بيتخذ في ثوانٍ مش ساعات', 20, True, WHITE),
    ])
    fade(s)


def s_journey():
    s = prs.slides.add_slide(BLANK)
    bg(s, LIGHT)
    txt(s, Inches(0.9), Inches(0.5), Inches(11.5), Inches(1.0), [
        ('قصة يوم واحد', 34, True, NAVY),
        ('من الفاكس للقرار — من غير مكالمة هاتفية', 17, False, MUTED),
    ])
    steps = [
        ('📠', 'الفاكس يوصل', 'رقم وعنوان وملخص'),
        ('📍', 'الموقع على الخريطة', 'نقرة أو خط مرسوم'),
        ('🧮', 'التقدير جاهز', 'ساعات وكابلات واحتياجات'),
        ('📤', 'تمرير للقيادة', 'بضغطة واحدة'),
        ('🎖️', 'القرار يتخذ', 'تصديق + توجيه فوري'),
    ]
    x = Inches(0.55)
    for i, (ic, head, sub) in enumerate(steps):
        circle(s, x, Inches(2.5), Inches(1.15), NAVY if i < 4 else GOLD)
        txt(s, x - Inches(0.15), Inches(2.75), Inches(1.45), Inches(0.7), [
            (ic, 30, False, WHITE),
        ], anchor=MSO_ANCHOR.MIDDLE)
        txt(s, x - Inches(0.35), Inches(3.85), Inches(1.85), Inches(1.6), [
            (head, 15, True, NAVY),
            (sub, 12, False, MUTED),
        ], anchor=MSO_ANCHOR.TOP)
        if i < 4:
            ar = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, x + Inches(1.35), Inches(2.95), Inches(0.55), Inches(0.28))
            ar.fill.solid(); ar.fill.fore_color.rgb = GOLD; ar.line.fill.background(); ar.shadow.inherit = False
            ar.rotation = 180
        x += Inches(2.55)
    card(s, Inches(0.9), Inches(5.7), Inches(11.5), Inches(1.1), fill=GOLDL, line=GOLD)
    txt(s, Inches(1.2), Inches(5.85), Inches(11), Inches(0.8), [
        ('⏱️ المدة: دقائق بدل ساعات — والمشغل مبيقطعش شغله', 18, True, NAVY),
    ])
    fade(s)


def s_alert():
    s = prs.slides.add_slide(BLANK)
    bg(s, LIGHT)
    txt(s, Inches(0.9), Inches(0.5), Inches(11.5), Inches(1.0), [
        ('لحظة «آه!»', 34, True, RED),
        ('نفس المكان اتعطل ٣ مرات — النظام فاكر', 17, False, MUTED),
    ])
    # big alert card
    card(s, Inches(1.0), Inches(1.9), Inches(7.2), Inches(4.6), fill=REDL, line=RED)
    txt(s, Inches(1.4), Inches(2.2), Inches(6.4), Inches(4), [
        ('🚨 تنبيه عاجل', 30, True, RED),
        ('عطل متكرر — ف/2026/0412', 20, True, NAVY),
        ('', 8, False, TXT),
        ('📅 آخر إصلاح: قبل ٤٥ يوم', 16, False, TXT),
        ('🔍 السبب: حفر جهة خارجية دون تنسيق', 16, False, TXT),
        ('🛠️ الإجراءات: إحلال وصلة + إنذار للمقاول', 16, False, TXT),
        ('', 8, False, TXT),
        ('▶ قرارك إنت: توجيه فوري للموقع', 16, True, BLUE),
    ])
    # side mini cards
    card(s, Inches(8.6), Inches(1.9), Inches(3.9), Inches(2.1), fill=CARD)
    txt(s, Inches(8.9), Inches(2.15), Inches(3.3), Inches(1.7), [
        ('🔊', 30, False, NAVY),
        ('صوت تنبيه فوري', 16, True, NAVY),
        ('Pop-up أحمر لا يُتجاهل', 13, False, MUTED),
    ])
    card(s, Inches(8.6), Inches(4.3), Inches(3.9), Inches(2.1), fill=CARD)
    txt(s, Inches(8.9), Inches(4.55), Inches(3.3), Inches(1.7), [
        ('🗂️', 30, False, NAVY),
        ('سجل كامل', 16, True, NAVY),
        ('كل الأعطال السابقة بالأسباب', 13, False, MUTED),
    ])
    fade(s)


def s_commands():
    s = prs.slides.add_slide(BLANK)
    bg(s, LIGHT)
    txt(s, Inches(0.9), Inches(0.5), Inches(11.5), Inches(1.0), [
        ('يد القائد — ٤ أوامر', 34, True, NAVY),
        ('بتتنفذ على المحطة — وبتتسجل باسم «شاشة القائد»', 17, False, MUTED),
    ])
    cmds = [
        ('✅', 'تصديق الاحتياجات', 'متاح / يحتاج تصديق / عجز — بند ببند'),
        ('🎯', 'تغيير الأولوية', 'حرجة · عالية · عادية · منخفضة'),
        ('✍️', 'توجيه مكتوب', 'Pop-up فوري عند المشغل + صوت تنبيه'),
        ('👁️', 'تأكيد الاطلاع', 'يوثّق إن القيادة شافت البلاغ'),
    ]
    pos = [(Inches(0.9), Inches(1.9)), (Inches(6.9), Inches(1.9)),
           (Inches(0.9), Inches(4.15)), (Inches(6.9), Inches(4.15))]
    for (ic, head, sub), (x, y) in zip(cmds, pos):
        card(s, x, y, Inches(5.6), Inches(1.95))
        txt(s, x + Inches(0.3), y + Inches(0.25), Inches(5), Inches(1.5), [
            (ic, 34, False, BLUE),
            (head, 20, True, NAVY),
            (sub, 14, False, MUTED),
        ])
    txt(s, Inches(0.9), Inches(6.5), Inches(11.5), Inches(0.7), [
        ('كل أمر → سجل تدقيق على المحطة + تحديث فوري للقائد', 16, True, GREEN),
    ])
    fade(s)


def s_live():
    s = prs.slides.add_slide(BLANK)
    bg(s, NAVY)
    txt(s, Inches(0.9), Inches(0.5), Inches(11.5), Inches(1.0), [
        ('المزامنة الحية', 34, True, GOLD),
        ('كل ثانيتين — من غير إنترنت', 17, False, RGBColor(0xBF,0xD0,0xEC)),
    ])
    # timeline
    steps = [
        ('📤', 'المحطة تدفع', 'لقطة الفاكس + كل تحديث'),
        ('📥', 'القائد يسحب', 'feed since_id — الجديد بس'),
        ('💾', 'نسخة محلية', 'بيانات + الملف الأصلي'),
        ('✅', 'تأكيد استلام', 'المحطة تعرف إنه وصل'),
        ('🔔', 'الشاشة تتحدث', 'SSE — بلا Refresh'),
    ]
    x = Inches(0.7)
    for i, (ic, head, sub) in enumerate(steps):
        circle(s, x, Inches(2.6), Inches(1.1), BLUE)
        txt(s, x - Inches(0.1), Inches(2.85), Inches(1.3), Inches(0.6), [(ic, 28, False, WHITE)], anchor=MSO_ANCHOR.MIDDLE)
        txt(s, x - Inches(0.45), Inches(3.9), Inches(2.0), Inches(1.4), [
            (head, 15, True, WHITE), (sub, 12, False, RGBColor(0xBF,0xD0,0xEC)),
        ], anchor=MSO_ANCHOR.TOP)
        if i < 4:
            ar = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, x + Inches(1.35), Inches(3.0), Inches(0.6), Inches(0.3))
            ar.fill.solid(); ar.fill.fore_color.rgb = GOLD; ar.line.fill.background(); ar.shadow.inherit = False
            ar.rotation = 180
        x += Inches(2.55)
    card(s, Inches(0.9), Inches(5.6), Inches(11.5), Inches(1.3), fill=NAVY2, line=RGBColor(0x2A,0x3D,0x66))
    txt(s, Inches(1.2), Inches(5.85), Inches(11), Inches(0.9), [
        ('🛡️ المحطة وقفت؟ القائد يفضل يعرض آخر موقف — والمؤشر يحمر فورًا', 17, True, WHITE),
        ('🔁 رجعت؟ المزامنة تلحق تلقائيًا — مفيش تدخل يدوي', 15, False, RGBColor(0xBF,0xD0,0xEC)),
    ])
    fade(s)


def s_deploy():
    s = prs.slides.add_slide(BLANK)
    bg(s, LIGHT)
    txt(s, Inches(0.9), Inches(0.5), Inches(11.5), Inches(1.0), [
        ('التشغيل — دبل كليك وخلص', 34, True, NAVY),
    ])
    steps = [
        ('🖥️', 'نفس الجهاز دلوقتي', 'START_ALL.bat → برنامجين + تبويبين'),
        ('💻', 'جهاز تاني بعدين', 'START_COMMAND.bat + غيّر عنوان المحطة من ⚙️'),
        ('📦', 'بياناتك في أمان', 'انسخ فولدر data — كل حاجة محلية'),
        ('🔌', 'من غير إنترنت', 'كل المكتبات في مجلد wheels المرفق'),
    ]
    pos = [(Inches(0.9), Inches(1.8)), (Inches(6.9), Inches(1.8)),
           (Inches(0.9), Inches(4.0)), (Inches(6.9), Inches(4.0))]
    for (ic, head, sub), (x, y) in zip(steps, pos):
        card(s, x, y, Inches(5.6), Inches(1.9))
        txt(s, x + Inches(0.3), y + Inches(0.22), Inches(5), Inches(1.5), [
            (ic, 32, False, BLUE),
            (head, 19, True, NAVY),
            (sub, 14, False, MUTED),
        ])
    fade(s)


def s_close():
    s = prs.slides.add_slide(BLANK)
    bg(s, NAVY)
    txt(s, Inches(1), Inches(2.3), Inches(11.3), Inches(3), [
        ('الفاكس مبقاش ورقة.', 44, True, GOLD),
        ('بقى قرار في ثانيتين.', 44, True, WHITE),
        ('', 16, False, WHITE),
        ('❓ أسئلة؟', 30, True, SKY),
        ('محطة قسم المشروعات + شاشة القائد — جاهزان للتجربة', 18, False, RGBColor(0xBF,0xD0,0xEC)),
    ])
    rect(s, Inches(4.4), Inches(5.7), Inches(4.5), Inches(0.05), GOLD, round_=False)
    fade(s)


s_hook()
s_problem()
s_solution()
s_numbers()
s_journey()
s_alert()
s_commands()
s_live()
s_deploy()
s_close()

out = '/mnt/f/aaaaa/عرض_المشروع.pptx'
prs.save(out)
print('saved', out, 'slides:', len(prs.slides._sldIdLst))
