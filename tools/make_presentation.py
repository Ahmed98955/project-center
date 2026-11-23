# -*- coding: utf-8 -*-
"""Generate the Arabic RTL project presentation (.pptx)."""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

NAVY = RGBColor(0x0F, 0x1F, 0x3D)
BLUE = RGBColor(0x1D, 0x4E, 0xD8)
LIGHT = RGBColor(0xF1, 0xF5, 0xF9)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GOLD = RGBColor(0xF5, 0xB9, 0x41)
GREEN = RGBColor(0x2E, 0x9E, 0x5B)
RED = RGBColor(0xD9, 0x45, 0x45)
GRAY = RGBColor(0x94, 0xA3, 0xB8)
DARKTXT = RGBColor(0x1E, 0x29, 0x3B)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
SW, SH = prs.slide_width, prs.slide_height


def _rtl(para):
    pPr = para._p.get_or_add_pPr()
    pPr.set('rtl', '1')
    pPr.set('algn', 'r')


def box(slide, x, y, w, h):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    return tf


def para(tf, text, size=18, bold=False, color=DARKTXT, first=False, bullet=False, space_after=6):
    p = tf.paragraphs[0] if first and not tf.paragraphs[0].runs else tf.add_paragraph()
    _rtl(p)
    p.alignment = PP_ALIGN.RIGHT
    p.space_after = Pt(space_after)
    run = p.add_run()
    run.text = ('• ' if bullet else '') + text
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.name = 'Arial'
    f.color.rgb = color
    return p


def slide_base(title, subtitle=None):
    s = prs.slides.add_slide(BLANK)
    bg = s.shapes.add_shape(1, 0, 0, SW, SH)  # rectangle
    bg.fill.solid(); bg.fill.fore_color.rgb = LIGHT; bg.line.fill.background()
    bg.shadow.inherit = False
    tf = box(s, Inches(0.7), Inches(0.45), Inches(11.9), Inches(1.1))
    para(tf, title, size=30, bold=True, color=NAVY, first=True)
    if subtitle:
        para(tf, subtitle, size=14, color=GRAY, space_after=0)
    bar = s.shapes.add_shape(1, Inches(0.7), Inches(1.35), Inches(1.6), Pt(4))
    bar.fill.solid(); bar.fill.fore_color.rgb = GOLD; bar.line.fill.background()
    bar.shadow.inherit = False
    return s


def content_slide(title, bullets, subtitle=None, note=None):
    s = slide_base(title, subtitle)
    tf = box(s, Inches(0.9), Inches(1.7), Inches(11.5), Inches(5.2))
    for b in bullets:
        if isinstance(b, tuple):
            head, sub = b
            para(tf, head, size=19, bold=True, color=BLUE, bullet=True, space_after=2)
            para(tf, sub, size=15, color=DARKTXT, space_after=10)
        else:
            para(tf, b, size=17, color=DARKTXT, bullet=True, space_after=10)
    if note:
        para(tf, note, size=13, color=GRAY, space_after=0)
    return s


def title_slide():
    s = prs.slides.add_slide(BLANK)
    bg = s.shapes.add_shape(1, 0, 0, SW, SH)
    bg.fill.solid(); bg.fill.fore_color.rgb = NAVY; bg.line.fill.background()
    bg.shadow.inherit = False
    band = s.shapes.add_shape(1, 0, Inches(5.9), SW, Inches(1.6))
    band.fill.solid(); band.fill.fore_color.rgb = BLUE; band.line.fill.background()
    band.shadow.inherit = False
    tf = box(s, Inches(0.9), Inches(2.1), Inches(11.5), Inches(3.4))
    para(tf, 'نظام إدارة العمليات والمشروعات', size=40, bold=True, color=WHITE, first=True, space_after=14)
    para(tf, 'محطتا عمل متكاملتان: محطة قسم المشروعات + شاشة القائد', size=22, color=GOLD, space_after=26)
    para(tf, 'سلاح الإشارة — فوج إنشاءات خطية ثقيلة', size=18, color=GRAY, space_after=4)
    para(tf, 'برنامج محلي يعمل بدون إنترنت · مزامنة فورية بين جهازين', size=16, color=GRAY, space_after=0)
    tf2 = box(s, Inches(0.9), Inches(6.15), Inches(11.5), Inches(1.0))
    para(tf2, 'عرض توضيحي شامل للمشروع — للمستخدم النهائي والمشغلين', size=15, color=WHITE, first=True)


def table_slide(title, headers, rows, col_w=None, subtitle=None):
    s = slide_base(title, subtitle)
    n_r, n_c = len(rows) + 1, len(headers)
    top = Inches(1.75); left = Inches(0.8); width = Inches(11.7)
    height = Inches(min(5.0, 0.55 * n_r))
    shape = s.shapes.add_table(n_r, n_c, left, top, width, height)
    tbl = shape.table
    if col_w:
        for i, w in enumerate(col_w):
            tbl.columns[i].width = Inches(w)
    for j, h in enumerate(headers):
        c = tbl.cell(0, j)
        c.fill.solid(); c.fill.fore_color.rgb = NAVY
        p = c.text_frame.paragraphs[0]; _rtl(p); p.alignment = PP_ALIGN.RIGHT
        r = p.add_run(); r.text = h; r.font.size = Pt(15); r.font.bold = True
        r.font.name = 'Arial'; r.font.color.rgb = WHITE
    for i, row in enumerate(rows, start=1):
        for j, val in enumerate(row):
            c = tbl.cell(i, j)
            if i % 2 == 0:
                c.fill.solid(); c.fill.fore_color.rgb = RGBColor(0xF8, 0xFA, 0xFC)
            p = c.text_frame.paragraphs[0]; _rtl(p); p.alignment = PP_ALIGN.RIGHT
            r = p.add_run(); r.text = str(val); r.font.size = Pt(14); r.font.name = 'Arial'; r.font.color.rgb = DARKTXT
    return s


def two_col_slide(title, left_title, left_items, right_title, right_items, subtitle=None):
    s = slide_base(title, subtitle)
    for x, t, items, accent in [(Inches(0.9), left_title, left_items, BLUE), (Inches(6.9), right_title, right_items, GREEN)]:
        head = box(s, x, Inches(1.7), Inches(5.5), Inches(0.6))
        para(head, t, size=20, bold=True, color=accent, first=True)
        tf = box(s, x, Inches(2.3), Inches(5.5), Inches(4.6))
        for it in items:
            para(tf, it, size=15, color=DARKTXT, bullet=True, space_after=8)
    return s


# ---------------------------------------------------------------- slides
title_slide()

content_slide('1) الفكرة العامة — مشكلتان وحل واحد', [
    ('المحطة (جهاز المشغل)', 'استقبال الفاكسات الورقية/الإلكترونية، تحديد موقع العطل أو المشروع على الخريطة، حساب التقدير الفني والاحتياجات، ثم «حفظ وتمرير إلى القيادة».'),
    ('شاشة القائد (جهاز القيادة)', 'ترى فقط ما مُرّر إليها — متابعة فورية، خريطة عملياتية، تنبيهات عاجلة، وتنفيذ أوامر خفيفة تعود للمحطة خلال ثوانٍ.'),
    'المبدأ: كل برنامج مستقل بسيرفر وقاعدة بيانات خاصة، ويتكلمان عبر شبكة محلية بدون إنترنت.',
], subtitle='لماذا برنامجان وليس برنامجًا واحدًا؟')

content_slide('2) البنية التقنية', [
    'برنامجان منفصلان: projects_station (بورت 8765) و command_screen (بورت 8766).',
    'المحطة تدفع «لقطات» الفاكسات الممررة عبر /api/command/feed، وشاشة القائد تسحبها كل ثانيتين وتؤكد الاستلام.',
    'أي تحديث بعد التمرير (حالة، تقدير، احتياجات، موقع، ملف) يصل للقائد فورًا عبر نفس القناة.',
    'أوامر القائد تذهب POST /api/command/inbox إلى المحطة، تُنفذ هناك، وتُسجل في سجل التدقيق باسم «شاشة القائد».',
    'التحديث اللحظي في المتصفح يتم عبر SSE — بلا Refresh وبلا مكتبات خارجية.',
    'البيانات: SQLite محلية على كل جهاز + ملفات الفاكس الأصلية محفوظة عند الطرفين.',
], subtitle='اتصال محلي بسيط وموثوق')

two_col_slide('3) محطة المشروعات — دورة عمل المشغل',
    'الخطوات بالترتيب', [
        'استلام الفاكس وتسجيل بياناته (رقم، نوع، عنوان، ملخص).',
        'تحديد الموقع على الخريطة (نقطة أو مسار متضرر).',
        'النظام يكتشف تلقائيًا: عطل متكرر في نفس الموقع، بلاغ حرج، تنسيق متأخر.',
        'حساب التقدير الفني: أطوال، كابلات، لحامات، ساعات عمل، معدات.',
        'توليد الاحتياجات (بنود بمواصفات وكميات) وتصديقها أو تعديلها.',
        '«حفظ وتمرير إلى القيادة» — لحظة بدء المزامنة.',
    ],
    'ما يعيشه المشغل بعد التمرير', [
        'أي أمر من القائد يظهر كـ Pop-up فوري مع صوت تنبيه.',
        'الفاكس يُوسم «مقروء من القيادة» مع اسم الجهاز والوقت.',
        'كل أمر (تصديق/أولوية/توجيه) يُسجل في سجل التدقيق.',
        'التوجيه المكتوب يُضاف كسطر في التتبع الزمني للعملية.',
        'الواجهة لا تتأثر لو شاشة القائد مغلقة — العمل يستمر عاديًا.',
    ], subtitle='الجزء الأول من النظام')

two_col_slide('4) شاشة القائد — المكونات',
    'الشريط العلوي', [
        'أعطال نشطة · مشروعات جارية · تنسيق متأخر',
        'بلاغات حرجة · مفارز في مأمورية',
        'مؤشر الاتصال بالمحطة (أخضر/أحمر) ووقت آخر تحديث',
        'زر التنبيهات 🔔 بعداد البلاغات غير المقروءة',
        'مؤقت تحديث اختياري: معطل / 5 / 10 / 30 دقيقة',
        'زر تبديل المظهر الفاتح ☀️ / الداكن 🌙',
    ],
    'الشاشات الثلاث', [
        'الخريطة العملياتية: المسارات والأعطال الممررة مضاءة بألوان نوعها.',
        'سجل العمليات: كل الممررات مع فلاتر (نوع/أولوية/حالة/بحث) وتسلسل زمني.',
        'البيانات المرجعية: المسارات والوصلات والأطقم — للعرض فقط.',
        'لوحة «آخر المستجدات»: تغذية موحدة لكل تحديثات العمليات.',
        'النقر على أي مؤشر في الأعلى يفتح السجل مفلترًا مباشرة.',
    ], subtitle='الجزء الثاني من النظام')

content_slide('5) التنبيه العاجل', [
    'يظهر تلقائيًا Pop-up أحمر مع صوت تنبيه عند: بلاغ حرج جديد، أو عطل متكرر في موقع سبق أن أُصلح فيه.',
    'يحتوي على: رقم الفاكس والعنوان، تاريخ آخر إصلاح، سبب العطل، والإجراءات التي اتخذت سابقًا.',
    'للعطل المتكرر يعرض جدولًا بكل الحالات السابقة (فاكس، تاريخ، سبب، حل) لتسهيل القرار.',
    'زر «تم الاطلاع» يسجل التأكيد على شاشة القائد ويُرسله للمحطة عبر سجل التدقيق.',
    'كل التنبيهات تُحفظ في سجل واحد يمكن مراجعته لاحقًا من زر 🔔 في الأعلى.',
], subtitle='لا يفوت القائد بلاغ مهم')

content_slide('6) أوامر القائد الخفيفة — التنفيذ الحقيقي على المحطة', [
    ('تصديق الاحتياجات', 'لكل بند: متاح / يحتاج تصديق / عجز — بثلاثة أزرار بجانب كل بند في صفحة التفاصيل.'),
    ('تغيير درجة الأهمية', 'حرجة / عالية / عادية / منخفضة — تُطبق على المحطة فورًا وتظهر في قوائمها.'),
    ('توجيه مكتوب', 'نص حر يظهر Pop-up فوريًا عند مشغل المحطة مع صوت، ويتسجل في التتبع باسم «شاشة القائد».'),
    ('تأكيد الاطلاع', 'من نافذة التنبيه العاجل — يوثق أن القيادة اطلعت على البلاغ الحرج/المتكرر.'),
    'ملاحظة: «مقروء» يحدث تلقائيًا عند فتح القائد لصفحة العملية — يُوسم الفاكس على المحطة.',
], subtitle='قرار واحد من مكان واحد')

table_slide('7) مصفوفة الأوامر — من يراها وأين تُسجل',
    ['الأمر', 'التنفيذ', 'يظهر لدى المشغل', 'التدقيق'],
    [
        ['تصديق بند حاجة', 'على المحطة', 'تحديث فوري في جدول الاحتياجات', 'logs_audit باسم شاشة القائد'],
        ['تغيير الأولوية', 'على المحطة', 'تحديث في القوائم والتقارير', 'logs_audit باسم شاشة القائد'],
        ['توجيه مكتوب', 'على المحطة', 'Pop-up + صوت + سطر في التتبع', 'command_directives + logs_audit'],
        ['تم الاطلاع', 'على المحطة', 'وسم «مقروء من القيادة» على الفاكس', 'command_alert_acks'],
        ['فتح العملية', 'على المحطة', 'command_seen_at + command_seen_by', 'logs_audit'],
    ], col_w=[2.6, 1.8, 3.4, 3.9], subtitle='كل أمر قابل للتتبع والمراجعة')

content_slide('8) المزامنة — ماذا يحدث كل ثانيتين', [
    'شاشة القائد تطلب /api/command/feed?since_id=… — لا شيء يتكرر، فقط الجديد.',
    'تحفظ نسخة كاملة من بيانات الفاكس محليًا + الملف الأصلي (PDF/صورة) في data/uploads.',
    'تؤكد الاستلام /api/command/ack — فتعرف المحطة أن الرسالة وصلت.',
    'تسحب بيانات مرجعية (مسارات، أطقم، إعدادات) وتخزنها محليًا للعرض السريع.',
    'لو المحطة توقفت: الشاشة تظل تعمل بآخر بيانات محفوظة، والمؤشر يتحول أحمر.',
    'عند عودة الاتصال: المزامنة تلحق تلقائيًا بدون تدخل — التحقق بالعنوان الجديد من الإعدادات فقط.',
], subtitle='اتصال من جهة واحدة = لا تعارض ولا تكرار')

content_slide('9) سيناريو يوم عمل نموذجي', [
    ('الصباح — المشغل', 'يسجل فاكس عطل في حي densely populated، يحدد الموقع على الخريطة، يراجع التقدير والاحتياجات، ويضغط «حفظ وتمرير».'),
    ('خلال ثوانٍ — القائد', 'يظهر الفاكس في الخريطة العملياتية ملونًا على المسار المتضرر، مع ملخص تنفيذي وتقدير فني واحتياجات.'),
    ('قرار سريع', 'القائد يصادق بند الكابل «متاح»، يرفع الأولوية إلى «حرجة»، ويرسل توجيهًا: «تحركوا قبل ساعة الذروة».'),
    ('فورًا — المشغل', 'Pop-up التوجيه يظهر عنده، الفاكس يتعلم «مقروء»، والتصديق يظهر في خانة الاحتياجات — كل ذلك بدون مكالمة هاتفية.'),
    ('المساء — المراجعة', 'سجل العمليات يعرض التسلسل الزمني الكامل لكل عملية، وسجل التدقيق يثبت من اتخذ أي قرار ومتى.'),
], subtitle='من الورقة إلى القرار في أقل من دقيقة')

content_slide('10) التشغيل والنشر', [
    'START_ALL.bat (في جذر المشروع): يشغّل المحطة والقائد معًا ويفتح تبويبين في المتصفح.',
    'START_COMMAND.bat (داخل command_screen): يشغّل شاشة القائد وحدها — وهذا ما يُستخدم على جهاز القيادة.',
    'لا حاجة لتثبيت Python — السكربتات تنشئ بيئة محلية وتنزل المكتبات من مجلد wheels المرفق أو تعيد استخدام بيئة البرنامج الآخر.',
    'نقل الشاشة لجهاز ثانٍ: انسخ مجلد command_screen + شغّل START_COMMAND.bat + غيّر عنوان المحطة من ⚙️ الإعدادات (مثل http://192.168.1.10:8765).',
    'للإبقاء على البيانات: انسخ مجلد data كاملًا من النسخة القديمة إلى الجديدة قبل التشغيل.',
], subtitle='جاهز للعمل على جهاز واحد أو جهازين')

content_slide('11) البيانات والأمان والاختبارات', [
    'كل البيانات محلية على كل جهاز: SQLite + ملفات — لا خوادم سحابية ولا إنترنت مطلوب.',
    'قاعدة بيانات القائد نسخة محلية — حذفها لا يؤثر على المحطة والعكس.',
    'سجل تدقيق مزدوج: المحطة تسجل كل أمر باسم «شاشة القائد (جهاز القيادة)»، والقائد يسجل كل ما نفذه في command_log.',
    'اختبارات آلية: 17 اختبارًا للمحطة + 5 اختبارات شاملة للمزامنة والأوامر — كلها ناجحة.',
    'تم التحقق end-to-end: تمرير فاكس → ظهوره عند القائد → تصديق/أولوية/توجيه → رجوعها للمحطة → تنبيه عطل متكرر → التعامل مع انقطاع الاتصال.',
    'البيانات التجريبية كلها وهمية، والأسماء أجهزة/رتب خيالية لا تعود لأشخاص حقيقيين.',
], subtitle='موثوقية قبل التسليم')

content_slide('12) ملاحظات للاستخدام الفعال', [
    'اجعل مؤشر الاتصال أخضر قبل بدء الدوام — أحمر يعني القائد يرى آخر موقف فقط.',
    'فعّل «تحديث كل 5 دقائق» لو أردت إعادة تحميل يدوية للبيانات بجانب التحديث الفوري (SSE).',
    'استخدم زر 🔔 صباحًا لمراجعة التنبيهات غير المقروءة بدل انتظار الـ Pop-up.',
    'الوضع الفاتح أنسب للشاشات الكبيرة/الطباعة، والداكن للغرف المنخفضة الإضاءة — الاختيار محفوظ تلقائيًا.',
    'لو أُرسلت بيانات قديمة/تجريبية بالخطأ: النسخة الاحتياطية الكاملة محفوظة وتُستعاد بنسخ مجلد data.',
], subtitle='نصائح تشغيلية')

prs.save('/mnt/f/aaaaa/شرح_المشروع.pptx')
print('saved:', '/mnt/f/aaaaa/شرح_المشروع.pptx', 'slides:', len(prs.slides.__iter__.__self__._sldIdLst))
