import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from fpdf import FPDF
import random, string

class Config:
    SECRET_KEY = 'super-secret-key-change-me'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///database.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.remember_cookie_duration = timedelta(days=365)
socketio = SocketIO(app, cors_allowed_origins="*")

# ========== النماذج ==========
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(10), unique=True, nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email_or_phone = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    bio = db.Column(db.Text, default='')
    telegram_link = db.Column(db.String(100), default='')
    whatsapp_link = db.Column(db.String(100), default='')
    show_real_name = db.Column(db.Boolean, default=True)
    profile_pic = db.Column(db.String(200), default='default.png')
    role = db.Column(db.String(20), default='student')
    level = db.Column(db.String(20), default='مبتدئ')
    badges = db.Column(db.String(200), default='')
    status = db.Column(db.String(50), default='متصل')
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    lessons_completed = db.relationship('LessonProgress', backref='user', lazy=True)
    test_results = db.relationship('TestResult', backref='user', lazy=True)

class Lesson(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    order = db.Column(db.Integer, unique=True)

class LessonProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    completed = db.Column(db.Boolean, default=True)
    completed_at = db.Column(db.DateTime, default=datetime.utcnow)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(200))
    option_b = db.Column(db.String(200))
    option_c = db.Column(db.String(200))
    option_d = db.Column(db.String(200))
    correct_answer = db.Column(db.String(1))

class TestResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    score = db.Column(db.Float, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='sent')
    reply_to_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=True)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.String(300))
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class RecoveryRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20))
    contact = db.Column(db.String(100))
    resolved = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    type = db.Column(db.String(20))
    url = db.Column(db.String(300))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
online_users = {}

def seed_database():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        db.session.add(User(
            student_id='STU0000', full_name='مدير النظام', username='admin',
            email_or_phone='admin@example.com',
            password=generate_password_hash('admin123'), role='admin', level='محترف', status='متصل'
        ))
    lessons_data = [
        (1, 'السلامة المهنية', 
         '🔹 مفهوم السلامة المهنية:\n'
         '• هي مجموعة من الإجراءات والقواعد التي تهدف إلى حماية العاملين من المخاطر.\n'
         '• تهدف إلى توفير بيئة عمل آمنة وخالية من الإصابات.\n\n'
         '🔹 قواعد السلامة عند استخدام الحاسوب:\n'
         '1. الجلوس بطريقة صحيحة (الظهر مستقيم، القدمان على الأرض).\n'
         '2. أن تكون الشاشة في مستوى العين.\n'
         '3. أخذ استراحة كل 30 دقيقة.\n'
         '4. استخدام كرسي مريح وقابل للتعديل.\n'
         '5. إبعاد السوائل عن الأجهزة الكهربائية.\n\n'
         '🔹 مخاطر العمل على الحاسوب:\n'
         '• إجهاد العين – الصداع – آلام الظهر والرقبة – متلازمة النفق الرسغي.'
        ),
        (2, 'تعريف الحاسوب',
         '🖥 ما هو الحاسوب؟\n'
         '• الحاسوب (Computer) هو جهاز إلكتروني يقوم باستقبال البيانات ومعالجتها وتحويلها إلى معلومات.\n'
         '• كلمة حاسوب مشتقة من "الحساب"، لأنه كان يستخدم قديماً في العمليات الحسابية.\n\n'
         '🔹 أنواع الحواسيب:\n'
         '1. الحاسوب الشخصي (Desktop).\n'
         '2. الحاسوب المحمول (Laptop).\n'
         '3. الحاسوب اللوحي (Tablet).\n'
         '4. الخادم (Server).\n'
         '5. الحاسوب العملاق (Supercomputer).\n\n'
         '🔹 أهمية الحاسوب في حياتنا:\n'
         '• التعليم – العمل – التواصل – الترفيه – البحث العلمي – الطب.'
        ),
        (3, 'مكونات الحاسوب',
         '🔹 المكونات المادية (Hardware):\n\n'
         '1️⃣ وحدات الإدخال (Input Units):\n'
         '• الفأرة (Mouse) – لوحة المفاتيح (Keyboard) – الماسح الضوئي – الميكروفون – الكاميرا.\n\n'
         '2️⃣ وحدات الإخراج (Output Units):\n'
         '• الشاشة (Monitor) – الطابعة (Printer) – السماعات – جهاز العرض (Projector).\n\n'
         '3️⃣ وحدة المعالجة المركزية (CPU):\n'
         '• عقل الحاسوب، تقوم بمعالجة البيانات وتنفيذ الأوامر.\n'
         '• تقاس سرعتها بالـ GHz.\n\n'
         '4️⃣ الذاكرة (Memory):\n'
         '• RAM: ذاكرة مؤقتة، تفقد بياناتها عند إطفاء الجهاز.\n'
         '• ROM: ذاكرة دائمة، تحتفظ بالبيانات.\n\n'
         '5️⃣ وحدات التخزين:\n'
         '• القرص الصلب (HDD) – القرص الصلب السريع (SSD) – الفلاش ميموري.'
        ),
        (4, 'استخدام الماوس ولوحة المفاتيح',
         '🖱 الفأرة (Mouse):\n'
         '• النقر الأيسر: تحديد العناصر.\n'
         '• النقر الأيمن: فتح قائمة الخيارات.\n'
         '• النقر المزدوج: فتح الملفات/المجلدات.\n'
         '• السحب والإفلات (Drag & Drop): نقل العناصر.\n'
         '• عجلة التمرير: التنقل لأعلى وأسفل.\n\n'
         '⌨ لوحة المفاتيح (Keyboard):\n'
         '🔹 أهم الاختصارات:\n'
         '• Ctrl + C: نسخ\n'
         '• Ctrl + V: لصق\n'
         '• Ctrl + X: قص\n'
         '• Ctrl + Z: تراجع\n'
         '• Ctrl + Y: إعادة\n'
         '• Ctrl + A: تحديد الكل\n'
         '• Ctrl + S: حفظ\n'
         '• Ctrl + P: طباعة\n'
         '• Alt + Tab: التنقل بين النوافذ\n'
         '• Windows + D: إظهار سطح المكتب'
        ),
        (5, 'سطح المكتب وشريط المهام',
         '🖥 سطح المكتب (Desktop):\n'
         '• هو الشاشة الرئيسية التي تظهر بعد تشغيل الجهاز.\n'
         '• يحتوي على أيقونات (Icons) تمثل البرامج والملفات والمجلدات.\n\n'
         '📌 شريط المهام (Taskbar):\n'
         '• يوجد أسفل الشاشة (يمكن نقله).\n'
         '• يحتوي على:\n'
         '  1. زر ابدأ (Start).\n'
         '  2. البرامج المثبتة.\n'
         '  3. البرامج المفتوحة حالياً.\n'
         '  4. منطقة الإشعارات (الساعة، الصوت، الشبكة).\n\n'
         '🔹 قائمة ابدأ (Start Menu):\n'
         '• للوصول إلى جميع البرامج المثبتة.\n'
         '• إيقاف التشغيل أو إعادة التشغيل.\n'
         '• الإعدادات (Settings).\n\n'
         '🔹 تخصيص سطح المكتب:\n'
         '• تغيير الخلفية – تغيير حجم الأيقونات – ترتيب الأيقونات.'
        ),
        (6, 'إدارة الملفات',
         '📁 المفاهيم الأساسية:\n'
         '• الملف (File): مجموعة بيانات لها اسم وامتداد.\n'
         '• المجلد (Folder): حاوية لتجميع الملفات.\n\n'
         '🔹 العمليات الأساسية:\n'
         '1. النسخ (Copy): Ctrl+C ثم Ctrl+V – ينشئ نسخة مطابقة.\n'
         '2. القص (Cut): Ctrl+X ثم Ctrl+V – ينقل الملف لمكان آخر.\n'
         '3. الحذف (Delete): ينقل الملف إلى سلة المحذوفات.\n'
         '4. إعادة التسمية (Rename): F2 أو كليك يمين > إعادة تسمية.\n'
         '5. إنشاء مجلد جديد: كليك يمين > New > Folder.\n'
         '6. تحديد ملفات متعددة: Ctrl + النقر.\n\n'
         '🗑 سلة المحذوفات (Recycle Bin):\n'
         '• مكان مؤقت للملفات المحذوفة.\n'
         '• يمكن استعادة الملفات منها.\n'
         '• تفريغها يحذف الملفات نهائياً.'
        ),
        (7, 'برامج النظام',
         '📝 المفكرة (Notepad):\n'
         '• برنامج بسيط لتحرير النصوص.\n'
         '• الامتداد: .txt\n'
         '• لا يدعم التنسيق (خط واحد فقط).\n\n'
         '🎨 الرسام (Paint):\n'
         '• برنامج للرسم والتلوين.\n'
         '• قص الصور وتغيير حجمها.\n'
         '• الحفظ بصيغ: PNG, JPEG, BMP.\n\n'
         '✂ أداة القصاصة (Snipping Tool):\n'
         '• لالتقاط صور للشاشة (Screenshot).\n'
         '• أنواع القص: مستطيل – حر – نافذة – شاشة كاملة.\n\n'
         '📋 الملاحظات (Sticky Notes):\n'
         '• تدوين ملاحظات سريعة على سطح المكتب.\n\n'
         '🎤 مسجل الصوت (Voice Recorder):\n'
         '• تسجيل الصوت عبر الميكروفون.'
        ),
        (8, 'تنزيل التطبيقات وتثبيتها وإزالتها',
         '📥 تنزيل التطبيقات:\n'
         '1. استخدم متصفح الإنترنت (Edge, Chrome, Firefox).\n'
         '2. اذهب إلى الموقع الرسمي للبرنامج.\n'
         '3. حمل النسخة المناسبة لنظامك (Windows/Mac).\n\n'
         '⚙ تثبيت البرامج:\n'
         '1. افتح الملف المحمل (عادة بصيغة .exe).\n'
         '2. اتبع تعليمات معالج التثبيت.\n'
         '3. وافق على الشروط، اختر مكان التثبيت.\n'
         '4. اضغط Next ثم Install ثم Finish.\n\n'
         '🗑 إزالة البرامج:\n'
         '1. اذهب إلى لوحة التحكم (Control Panel).\n'
         '2. اختر "Programs and Features".\n'
         '3. اختر البرنامج واضغط Uninstall.\n'
         'أو: الإعدادات > Apps > Apps & features > اختر البرنامج > Uninstall.'
        ),
        (9, 'مايكروسوفت وورد',
         '📄 واجهة البرنامج:\n'
         '• شريط العنوان – شريط القوائم – شريط الأدوات – منطقة العمل.\n\n'
         '🔹 العمليات الأساسية:\n'
         '1. إنشاء مستند جديد: Ctrl+N.\n'
         '2. فتح مستند: Ctrl+O.\n'
         '3. حفظ: Ctrl+S.\n'
         '4. طباعة: Ctrl+P.\n\n'
         '🎨 التنسيق:\n'
         '• نوع الخط – حجم الخط – لون الخط.\n'
         '• غامق (Bold): Ctrl+B – مائل (Italic): Ctrl+I – تسطير: Ctrl+U.\n'
         '• محاذاة: يمين، يسار، وسط، ضبط.\n'
         '• تباعد الأسطر – تعداد نقطي ورقمي.\n\n'
         '📊 الجداول:\n'
         '• إدراج > جدول > اختر عدد الصفوف والأعمدة.\n'
         '• دمج الخلايا – تقسيم الخلايا – تنسيق الحدود.\n\n'
         '🖼 الصور:\n'
         '• إدراج > صور > اختر الصورة من الجهاز.\n'
         '• تغيير حجم الصورة – التفاف النص حول الصورة.'
        ),
        (10, 'مايكروسوفت باوربوينت',
         '📊 مفهوم العروض التقديمية:\n'
         '• مجموعة من الشرائح (Slides) لعرض المعلومات.\n'
         '• تستخدم في المحاضرات والاجتماعات.\n\n'
         '🔹 إنشاء عرض تقديمي:\n'
         '1. شريحة العنوان (Title Slide).\n'
         '2. إضافة شريحة جديدة: Ctrl+M.\n'
         '3. اختيار تخطيط الشريحة (Layout).\n\n'
         '🎨 التصميم (Design):\n'
         '• اختيار قالب جاهز (Theme).\n'
         '• تغيير الألوان والخطوط.\n'
         '• إضافة خلفية.\n\n'
         '✨ الحركات (Animations):\n'
         '1. حركات الدخول (Entrance).\n'
         '2. حركات الخروج (Exit).\n'
         '3. حركات التأكيد (Emphasis).\n\n'
         '🔄 الانتقالات بين الشرائح (Transitions):\n'
         '• fade – push – wipe – zoom.\n'
         '• تحديد المدة وإضافة صوت.'
        ),
        (11, 'مايكروسوفت إكسل',
         '📊 واجهة البرنامج:\n'
         '• ورقة العمل (Worksheet): شبكة من الصفوف والأعمدة.\n'
         '• الصفوف: مرقمة (1,2,3...).\n'
         '• الأعمدة: معنونة بحروف (A,B,C...).\n'
         '• الخلية (Cell): تقاطع الصف والعمود (مثال: A1, B4).\n\n'
         '🔹 إدخال البيانات:\n'
         '• نصوص – أرقام – تواريخ – عملات.\n'
         '• التنسيق: حدود، ألوان، حجم الخط.\n\n'
         '🧮 الصيغ والدوال:\n'
         '• كل صيغة تبدأ بعلامة =.\n'
         '• أمثلة: =A1+B1، =A1*2.\n\n'
         '🔹 أهم الدوال:\n'
         '• SUM: الجمع =SUM(A1:A10).\n'
         '• AVERAGE: المتوسط =AVERAGE(B1:B10).\n'
         '• MAX: أكبر قيمة =MAX(C1:C10).\n'
         '• MIN: أصغر قيمة =MIN(D1:D10).\n'
         '• COUNT: عد الخلايا =COUNT(E1:E10).\n\n'
         '📈 المخططات البيانية:\n'
         '• إدراج > Charts > اختر نوع المخطط (عمودي، دائري، خطي).'
        ),
        (12, 'استعداد للاختبارات',
         '📝 نصائح وإرشادات:\n\n'
         '1. راجع جميع الدروس السابقة بتركيز.\n'
         '2. مارس العمليات عملياً على جهازك.\n'
         '3. احفظ أهم الاختصارات.\n'
         '4. افهم الفرق بين RAM و ROM.\n'
         '5. تعرف على وحدات الإدخال والإخراج.\n'
         '6. مارس التنسيق في وورد وباوربوينت وإكسل.\n'
         '7. جرب إنشاء مجلدات ونسخ ولصق الملفات.\n'
         '8. تعرف على برامج النظام ووظائفها.\n\n'
         '✅ معايير النجاح:\n'
         '• الحصول على 70% فأكثر في الاختبار.\n'
         '• يمكنك إعادة الاختبار أكثر من مرة.\n'
         '• بعد النجاح يمكنك تحميل شهادتك.'
        )
    ]
    for order, title, content in lessons_data:
        if not Lesson.query.filter_by(order=order).first():
            db.session.add(Lesson(title=title, content=content, order=order))
    questions = [
        ('ما المكون المسؤول عن معالجة البيانات؟', 'المعالج', 'الذاكرة', 'القرص الصلب', 'الشاشة', 'a'),
        ('أي مما يلي وحدة إدخال؟', 'الشاشة', 'الطابعة', 'الفأرة', 'السماعات', 'c'),
        ('RAM تعني:', 'ذاكرة القراءة فقط', 'ذاكرة الوصول العشوائي', 'المعالج', 'القرص الصلب', 'b'),
        ('للتراجع نضغط:', 'Ctrl+Z', 'Ctrl+Y', 'Ctrl+C', 'Ctrl+V', 'a'),
        ('مرجع الخلية A1 في الإكسل:', 'خلية نشطة', 'مرجع خلية', 'دالة', 'ورقة عمل', 'b'),
        ('لحفظ ملف:', 'Ctrl+S', 'Ctrl+P', 'Ctrl+O', 'Ctrl+N', 'a'),
        ('امتداد العروض التقديمية:', '.docx', '.xlsx', '.pptx', '.txt', 'c'),
        ('ليس من برامج النظام:', 'المفكرة', 'الرسام', 'وورد', 'مسجل الصوت', 'c'),
        ('لنسخ ملف:', 'قص', 'نسخ', 'حذف', 'إعادة تسمية', 'b'),
        ('الأيقونة هي:', 'صورة برنامج', 'نافذة', 'شريط', 'زر', 'a')
    ]
    while len(questions) < 30:
        questions.extend(questions)
    for q_text, a, b, c, d, correct in questions[:30]:
        if not Question.query.filter_by(question_text=q_text).first():
            db.session.add(Question(question_text=q_text, option_a=a, option_b=b, option_c=c, option_d=d, correct_answer=correct))
    db.session.commit()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def generate_student_id():
    last = User.query.order_by(User.id.desc()).first()
    num = int(last.student_id[3:]) + 1 if last and last.student_id.startswith('STU') else 1
    return f'STU{num:04d}'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png','jpg','jpeg','gif','pdf','doc','docx','mp4'}

def get_arabic_rank(score):
    if score >= 90: return 'محترف'
    elif score >= 70: return 'متوسط'
    return 'مبتدئ'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/guest')
def guest_home():
    lessons = Lesson.query.order_by(Lesson.order).limit(3).all()
    return render_template('guest.html', lessons=lessons)

@app.route('/guest/lesson/<int:lesson_id>')
def guest_lesson(lesson_id):
    if lesson_id > 3:
        flash('يجب التسجيل لمشاهدة جميع الدروس', 'warning')
        return redirect(url_for('guest_home'))
    lesson = Lesson.query.get_or_404(lesson_id)
    return render_template('lesson_detail.html', lesson=lesson)

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        full_name = request.form['full_name'].strip()
        username = request.form['username'].strip()
        email_or_phone = request.form['email_or_phone'].strip()
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('اسم المستخدم موجود مسبقاً', 'danger')
            return redirect(url_for('register'))
        if User.query.filter_by(email_or_phone=email_or_phone).first():
            flash('البريد/الهاتف مستخدم مسبقاً', 'danger')
            return redirect(url_for('register'))
        user = User(full_name=full_name, username=username, email_or_phone=email_or_phone,
                    password=generate_password_hash(password), student_id=generate_student_id(), status='متصل')
        db.session.add(user)
        db.session.commit()
        login_user(user, remember=True)
        flash(f'تم التسجيل! المعرف الدراسي: {user.student_id}', 'success')
        return redirect(url_for('profile'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        remember = True if request.form.get('remember') else False
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user, remember=remember)
            user.last_seen = datetime.utcnow()
            user.status = 'متصل'
            db.session.commit()
            flash('تم تسجيل الدخول بنجاح', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    current_user.status = 'غير متصل'
    current_user.last_seen = datetime.utcnow()
    db.session.commit()
    logout_user()
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    if request.method == 'POST':
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{current_user.username}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                current_user.profile_pic = filename
        current_user.bio = request.form.get('bio','').strip()
        current_user.telegram_link = request.form.get('telegram','').strip()
        current_user.whatsapp_link = request.form.get('whatsapp','').strip()
        current_user.show_real_name = 'show_real_name' in request.form
        current_user.status = request.form.get('status','متصل')
        db.session.commit()
        flash('تم تحديث الملف الشخصي', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', user=current_user)

@app.route('/student/<int:user_id>')
def public_profile(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('لا يمكن عرض ملف المشرف', 'warning')
        return redirect(url_for('students'))
    return render_template('public_profile.html', user=user)

@app.route('/students')
@login_required
def students():
    users = User.query.filter(User.role != 'admin').all()
    return render_template('students.html', users=users)

@app.route('/lessons')
@login_required
def lessons():
    lessons = Lesson.query.order_by(Lesson.order).all()
    completed_ids = [lp.lesson_id for lp in current_user.lessons_completed]
    return render_template('lessons.html', lessons=lessons, completed=completed_ids)

@app.route('/lesson/<int:lesson_id>')
@login_required
def lesson_detail(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    if not LessonProgress.query.filter_by(user_id=current_user.id, lesson_id=lesson_id).first():
        db.session.add(LessonProgress(user_id=current_user.id, lesson_id=lesson_id))
        db.session.commit()
    return render_template('lesson_detail.html', lesson=lesson)

@app.route('/test')
@login_required
def test_start():
    questions = Question.query.order_by(db.func.random()).limit(30).all()
    if len(questions) < 30:
        questions = Question.query.order_by(db.func.random()).all()[:30]
    session['test_questions'] = [q.id for q in questions]
    session['current_question_index'] = 0
    session['score'] = 0
    return redirect(url_for('test_question'))

@app.route('/test/question')
@login_required
def test_question():
    ids = session.get('test_questions')
    if not ids: return redirect(url_for('test_start'))
    idx = session.get('current_question_index', 0)
    if idx >= len(ids): return redirect(url_for('test_result'))
    return render_template('test.html', question=Question.query.get(ids[idx]), index=idx+1, total=len(ids))

@app.route('/test/answer', methods=['POST'])
@login_required
def test_answer():
    answer = request.form.get('answer')
    ids = session.get('test_questions')
    idx = session.get('current_question_index', 0)
    if ids and idx < len(ids) and answer == Question.query.get(ids[idx]).correct_answer:
        session['score'] = session.get('score', 0) + 1
    session['current_question_index'] = idx + 1
    return redirect(url_for('test_question'))

@app.route('/test/result')
@login_required
def test_result():
    score = session.get('score', 0)
    total = len(session.get('test_questions', []))
    percentage = (score / total * 100) if total > 0 else 0
    db.session.add(TestResult(user_id=current_user.id, score=percentage, total_questions=total))
    current_user.level = get_arabic_rank(percentage)
    db.session.commit()
    session.pop('test_questions', None); session.pop('current_question_index', None); session.pop('score', None)
    return render_template('test_result.html', score=score, total=total, percentage=percentage)

@app.route('/statistics')
@login_required
def statistics():
    total = Lesson.query.count()
    completed = LessonProgress.query.filter_by(user_id=current_user.id).count()
    progress = (completed/total*100) if total else 0
    avg = db.session.query(db.func.avg(TestResult.score)).filter_by(user_id=current_user.id).scalar() or 0
    ranks = db.session.query(TestResult.user_id, db.func.avg(TestResult.score).label('a')).group_by(TestResult.user_id).order_by(db.desc('a')).all()
    rank = next((i for i,(uid,_) in enumerate(ranks,1) if uid==current_user.id), None)
    results = TestResult.query.filter_by(user_id=current_user.id).order_by(TestResult.timestamp.desc()).limit(5).all()
    return render_template('statistics.html', completed=completed, total_lessons=total, progress_percent=round(progress,1), avg_score=round(avg,1), rank=rank, last_results=results)

@app.route('/chat')
@login_required
def chat():
    return render_template('chat.html')

@app.route('/forgot-username', methods=['GET','POST'])
def forgot_username():
    if request.method == 'POST':
        user = User.query.filter_by(email_or_phone=request.form['contact'].strip()).first()
        if user:
            if not RecoveryRequest.query.filter_by(user_id=user.id, type='username', resolved=False).first():
                db.session.add(RecoveryRequest(user_id=user.id, type='username', contact=user.email_or_phone))
                db.session.commit()
            flash('تم إرسال طلب استعادة اسم المستخدم إلى المشرف', 'info')
        else: flash('لا يوجد حساب', 'danger')
    return render_template('forgot_username.html')

@app.route('/forgot-password', methods=['GET','POST'])
def forgot_password():
    if request.method == 'POST':
        user = User.query.filter_by(email_or_phone=request.form['contact'].strip()).first()
        if user:
            if not RecoveryRequest.query.filter_by(user_id=user.id, type='password', resolved=False).first():
                db.session.add(RecoveryRequest(user_id=user.id, type='password', contact=user.email_or_phone))
                db.session.commit()
            flash('تم إرسال طلب استعادة كلمة المرور إلى المشرف', 'info')
        else: flash('لا يوجد حساب', 'danger')
    return render_template('forgot_password.html')

@app.route('/certificate')
@login_required
def certificate():
    if LessonProgress.query.filter_by(user_id=current_user.id).count() < Lesson.query.count() or not TestResult.query.filter_by(user_id=current_user.id).first():
        flash('يجب إنهاء جميع الدروس وإجراء اختبار', 'warning')
        return redirect(url_for('statistics'))
    pdf = FPDF('L','mm','A4')
    pdf.add_page()
    pdf.set_font('Arial','B',24)
    pdf.cell(0,20,'Certificate of Completion',ln=True,align='C')
    pdf.ln(10)
    pdf.set_font('Arial','',18)
    pdf.cell(0,15,'This certifies that',ln=True,align='C')
    pdf.set_font('Arial','B',22)
    pdf.cell(0,20,current_user.full_name,ln=True,align='C')
    pdf.set_font('Arial','',16)
    pdf.cell(0,15,f'Student ID: {current_user.student_id}',ln=True,align='C')
    pdf.cell(0,15,'has completed all lessons and tests.',ln=True,align='C')
    pdf.ln(10)
    pdf.set_font('Arial','I',12)
    pdf.cell(0,10,f'Issued: {datetime.utcnow().strftime("%Y-%m-%d")}',ln=True,align='C')
    resp = app.response_class(pdf.output(dest='S').encode('latin-1'), mimetype='application/pdf')
    resp.headers['Content-Disposition'] = f'attachment; filename=Certificate_{current_user.student_id}.pdf'
    return resp

def admin_required(f):
    from functools import wraps
    @wraps(f)
    @login_required
    def dec(*a,**k):
        if current_user.role!='admin': abort(403)
        return f(*a,**k)
    return dec

@app.route('/admin')
@admin_required
def admin_dashboard():
    return render_template('admin/dashboard.html', user_count=User.query.count(),
                           active_today=User.query.filter(User.last_seen>=datetime.utcnow()-timedelta(days=1)).count(),
                           pending=RecoveryRequest.query.filter_by(resolved=False).count())

@app.route('/admin/users')
@admin_required
def admin_users():
    return render_template('admin/users.html', users=User.query.order_by(User.last_seen.desc()).all())

@app.route('/admin/recovery-requests')
@admin_required
def admin_recovery():
    return render_template('admin/recovery_requests.html', requests=RecoveryRequest.query.filter_by(resolved=False).all())

@app.route('/admin/recovery/resolve/<int:req_id>', methods=['POST'])
@admin_required
def resolve_recovery(req_id):
    req = RecoveryRequest.query.get_or_404(req_id)
    user = User.query.get(req.user_id)
    if req.type == 'username':
        flash(f'اسم المستخدم: {user.username}', 'info')
    else:
        new_pass = ''.join(random.choices(string.ascii_letters+string.digits, k=8))
        user.password = generate_password_hash(new_pass)
        db.session.commit()
        flash(f'كلمة المرور الجديدة: {new_pass}', 'success')
    req.resolved = True
    db.session.commit()
    return redirect(url_for('admin_recovery'))

@app.route('/admin/lessons')
@admin_required
def admin_lessons():
    return render_template('admin/content_lessons.html', lessons=Lesson.query.order_by(Lesson.order).all())

@app.route('/admin/lesson/add', methods=['POST'])
@admin_required
def add_lesson():
    db.session.add(Lesson(title=request.form['title'], content=request.form['content'], order=int(request.form['order'])))
    db.session.commit()
    return redirect(url_for('admin_lessons'))

@app.route('/admin/lesson/edit/<int:id>', methods=['POST'])
@admin_required
def edit_lesson(id):
    l = Lesson.query.get_or_404(id)
    l.title = request.form['title']; l.content = request.form['content']; l.order = int(request.form['order'])
    db.session.commit()
    return redirect(url_for('admin_lessons'))

@app.route('/admin/lesson/delete/<int:id>')
@admin_required
def delete_lesson(id):
    Lesson.query.filter_by(id=id).delete()
    db.session.commit()
    return redirect(url_for('admin_lessons'))

@app.route('/admin/questions')
@admin_required
def admin_questions():
    return render_template('admin/content_questions.html', questions=Question.query.all())

@app.route('/admin/question/add', methods=['POST'])
@admin_required
def add_question():
    db.session.add(Question(question_text=request.form['question_text'], option_a=request.form['option_a'], option_b=request.form['option_b'], option_c=request.form['option_c'], option_d=request.form['option_d'], correct_answer=request.form['correct_answer']))
    db.session.commit()
    return redirect(url_for('admin_questions'))

@app.route('/admin/question/edit/<int:id>', methods=['POST'])
@admin_required
def edit_question(id):
    q = Question.query.get_or_404(id)
    for f in ['question_text','option_a','option_b','option_c','option_d','correct_answer']:
        setattr(q, f, request.form[f])
    db.session.commit()
    return redirect(url_for('admin_questions'))

@app.route('/admin/question/delete/<int:id>')
@admin_required
def delete_question(id):
    Question.query.filter_by(id=id).delete()
    db.session.commit()
    return redirect(url_for('admin_questions'))

@app.route('/admin/resources')
@admin_required
def admin_resources():
    return render_template('admin/resource_library.html', resources=Resource.query.all())

@app.route('/admin/notifications', methods=['GET','POST'])
@admin_required
def admin_notifications():
    if request.method == 'POST':
        for u in User.query.filter_by(role='student').all():
            db.session.add(Notification(user_id=u.id, content=request.form['message']))
        db.session.commit()
        flash('تم الإرسال', 'success')
    return render_template('admin/notifications.html')

@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        current_user.status = 'متصل'
        current_user.last_seen = datetime.utcnow()
        db.session.commit()
        online_users.setdefault(current_user.id, set()).add(request.sid)

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        if current_user.id in online_users:
            online_users[current_user.id].discard(request.sid)
            if not online_users[current_user.id]:
                del online_users[current_user.id]
                current_user.status = 'غير متصل'
                current_user.last_seen = datetime.utcnow()
                db.session.commit()

@socketio.on('send_message')
def handle_message(data):
    if not current_user.is_authenticated: return
    text = data.get('text','').strip()
    if not text: return
    msg = Message(sender_id=current_user.id, text=text)
    db.session.add(msg)
    db.session.commit()
    sender_name = current_user.full_name if current_user.show_real_name else current_user.username
    sender_pic = current_user.profile_pic if current_user.profile_pic and current_user.profile_pic != 'default.png' else ''
    emit('new_message', {
        'id': msg.id,
        'sender_id': current_user.id,
        'sender_name': sender_name,
        'sender_pic': sender_pic,
        'text': msg.text,
        'timestamp': msg.timestamp.strftime('%H:%M')
    }, broadcast=True)

@app.route('/api/messages')
@login_required
def api_messages():
    msgs = Message.query.order_by(Message.timestamp.asc()).all()
    result = []
    for m in msgs:
        sender_name = m.sender.full_name if m.sender.show_real_name else m.sender.username
        sender_pic = m.sender.profile_pic if m.sender.profile_pic and m.sender.profile_pic != 'default.png' else ''
        result.append({
            'id': m.id,
            'sender_id': m.sender_id,
            'sender_name': sender_name,
            'sender_pic': sender_pic,
            'text': m.text,
            'timestamp': m.timestamp.strftime('%H:%M')
        })
    return jsonify(result)

if __name__ == '__main__':
    with app.app_context():
        seed_database()
    port = int(os.environ.get("PORT", 5000))
    print(f"✅ الموقع يعمل على المنفذ: {port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)