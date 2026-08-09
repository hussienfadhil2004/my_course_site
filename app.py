import os, json, time, shutil
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, abort, send_from_directory, render_template_string
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
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024

    basedir = os.path.abspath(os.path.dirname(__file__))
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        SQLALCHEMY_DATABASE_URI = database_url
    else:
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'database.db')

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.remember_cookie_duration = timedelta(days=365)
socketio = SocketIO(app, cors_allowed_origins="*")

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
online_users = {}

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
    badges = db.Column(db.String(500), default='')
    status = db.Column(db.String(50), default='متصل')
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    banned = db.Column(db.Boolean, default=False)
    lessons_completed = db.relationship('LessonProgress', backref='user', lazy=True)
    test_results = db.relationship('TestResult', backref='user', lazy=True)
    achievements = db.relationship('UserAchievement', backref='user', lazy=True)

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
    question_type = db.Column(db.String(10), default='mcq')
    option_a = db.Column(db.String(200))
    option_b = db.Column(db.String(200))
    option_c = db.Column(db.String(200))
    option_d = db.Column(db.String(200))
    correct_answer = db.Column(db.String(1))
    lesson_id = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=True)

class TestResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    score = db.Column(db.Float, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    answers = db.Column(db.Text, default='')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    test_type = db.Column(db.String(20), default='random')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    text = db.Column(db.Text, nullable=False)
    file_path = db.Column(db.String(300))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    edited = db.Column(db.Boolean, default=False)
    edited_at = db.Column(db.DateTime, nullable=True)
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

class Achievement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    icon = db.Column(db.String(50))
    condition_type = db.Column(db.String(50))
    condition_value = db.Column(db.Integer)

class UserAchievement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    achievement_id = db.Column(db.Integer, db.ForeignKey('achievement.id'), nullable=False)
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    type = db.Column(db.String(20))
    url = db.Column(db.String(300))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------- بذور البيانات ----------
def seed_database():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        db.session.add(User(student_id='STU0000', full_name='مدير النظام', username='admin',
                            email_or_phone='admin@example.com',
                            password=generate_password_hash('admin123'), role='admin', level='محترف', status='متصل'))
    lessons_data = [
        (1, 'السلامة المهنية', 'السلامة المهنية هي مجموعة من القواعد...'),
        (2, 'تعريف الحاسوب', 'الحاسوب هو جهاز إلكتروني...'),
        (3, 'مكونات الحاسوب', 'وحدات الإدخال والإخراج...'),
        (4, 'استخدام الماوس ولوحة المفاتيح', 'الاختصارات الأساسية...'),
        (5, 'سطح المكتب وشريط المهام', 'أيقونات سطح المكتب...'),
        (6, 'إدارة الملفات', 'نسخ، قص، لصق...'),
        (7, 'برامج النظام', 'المفكرة، الرسام...'),
        (8, 'تنزيل التطبيقات', 'تثبيت البرامج...'),
        (9, 'مايكروسوفت وورد', 'التنسيق والجداول...'),
        (10, 'مايكروسوفت باوربوينت', 'الشرائح والحركات...'),
        (11, 'مايكروسوفت إكسل', 'الدوال والمعادلات...'),
        (12, 'استعداد للاختبارات', 'مراجعة شاملة...')
    ]
    for order, title, content in lessons_data:
        if not Lesson.query.filter_by(order=order).first():
            db.session.add(Lesson(title=title, content=content, order=order))

    questions = [
        ('ما هو الهدف من السلامة المهنية؟', 'mcq', 'حماية العاملين', 'زيادة الإنتاج', 'خفض التكاليف', 'كل ما سبق', 'a', 1),
        ('كم مرة يجب أخذ استراحة عند استخدام الحاسوب؟', 'mcq', 'كل ساعة', 'كل 30 دقيقة', 'كل 10 دقائق', 'عند الحاجة', 'b', 1),
        ('السلامة المهنية مهمة للحفاظ على صحة المستخدم.', 'tf', None, None, None, None, 't', 1),
        ('أي من هذه يعتبر حاسوباً شخصياً؟', 'mcq', 'Server', 'Tablet', 'Desktop', 'Supercomputer', 'c', 2),
        ('الكمبيوتر المحمول يسمى Laptop.', 'tf', None, None, None, None, 't', 2),
        ('الخادم هو حاسوب عملاق.', 'tf', None, None, None, None, 'f', 2),
        ('أي مما يلي وحدة إدخال؟', 'mcq', 'الشاشة', 'الطابعة', 'الفأرة', 'السماعات', 'c', 3),
        ('وحدة المعالجة المركزية تسمى CPU.', 'tf', None, None, None, None, 't', 3),
        ('الذاكرة RAM تفقد بياناتها عند إطفاء الجهاز.', 'tf', None, None, None, None, 't', 3),
        ('لإعادة تسمية ملف نضغط:', 'mcq', 'F2', 'F3', 'F4', 'F5', 'a', 4),
        ('Ctrl+Z للتراجع.', 'tf', None, None, None, None, 't', 4),
        ('لحفظ ملف نضغط Ctrl+S.', 'tf', None, None, None, None, 't', 4),
        ('Windows+E يفتح:', 'mcq', 'المستندات', 'مستكشف الملفات', 'الإعدادات', 'الطابعة', 'b', 5),
        ('لتحديد الكل نضغط Ctrl+A.', 'tf', None, None, None, None, 't', 5),
        ('سطح المكتب هو الشاشة الرئيسية.', 'tf', None, None, None, None, 't', 5),
        ('لنسخ ملف نستخدم:', 'mcq', 'قص', 'نسخ', 'حذف', 'إعادة تسمية', 'b', 6),
        ('سلة المحذوفات تحذف الملفات نهائياً.', 'tf', None, None, None, None, 'f', 6),
        ('يمكن استعادة ملف من سلة المحذوفات.', 'tf', None, None, None, None, 't', 6),
        ('برنامج الرسام يستخدم للرسم.', 'tf', None, None, None, None, 't', 7),
        ('المفكرة تدعم التنسيق.', 'tf', None, None, None, None, 'f', 7),
        ('أداة القصاصة تلتقط صور الشاشة.', 'tf', None, None, None, None, 't', 7),
        ('لتثبيت برنامج، نفتح ملف .exe.', 'tf', None, None, None, None, 't', 8),
        ('لإزالة برنامج نذهب إلى لوحة التحكم.', 'tf', None, None, None, None, 't', 8),
        ('يجب تحميل البرامج من مواقع غير رسمية.', 'tf', None, None, None, None, 'f', 8),
        ('في وورد، Ctrl+B يجعل الخط غامقاً.', 'tf', None, None, None, None, 't', 9),
        ('يمكن إدراج صورة في وورد.', 'tf', None, None, None, None, 't', 9),
        ('امتداد الوورد هو .pptx.', 'tf', None, None, None, None, 'f', 9),
        ('يستخدم باوربوينت للعروض التقديمية.', 'tf', None, None, None, None, 't', 10),
        ('F5 يبدأ عرض الشرائح.', 'tf', None, None, None, None, 't', 10),
        ('الحركات في باوربوينت تكون بين الشرائح فقط.', 'tf', None, None, None, None, 'f', 10),
        ('SUM دالة جمع في إكسل.', 'tf', None, None, None, None, 't', 11),
        ('امتداد الإكسل هو .xlsx.', 'tf', None, None, None, None, 't', 11),
        ('الخلية A1 هي تقاطع العمود A والصف 1.', 'tf', None, None, None, None, 't', 11),
        ('يجب مراجعة جميع الدروس قبل الاختبار.', 'tf', None, None, None, None, 't', 12),
        ('يمكن إعادة الاختبار أكثر من مرة.', 'tf', None, None, None, None, 't', 12),
        ('النجاح من 50%.', 'tf', None, None, None, None, 'f', 12),
    ]
    for q in questions:
        text, qtype, a, b, c, d, ans, lid = q
        if not Question.query.filter_by(question_text=text).first():
            db.session.add(Question(question_text=text, question_type=qtype, option_a=a, option_b=b, option_c=c, option_d=d, correct_answer=ans, lesson_id=lid))

    achievements = [
        ('بداية الرحلة', 'سجل في الموقع', '🎉', 'account_created', 1),
        ('متعلم جاد', 'أكمل 3 دروس', '📚', 'lessons_completed', 3),
        ('متميز', 'أكمل جميع الدروس', '🌟', 'lessons_completed', 12),
    ]
    for name, desc, icon, ctype, cval in achievements:
        if not Achievement.query.filter_by(name=name).first():
            db.session.add(Achievement(name=name, description=desc, icon=icon, condition_type=ctype, condition_value=cval))
    db.session.commit()

# ---------- تسجيل ----------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def generate_student_id():
    last = User.query.order_by(User.id.desc()).first()
    num = int(last.student_id[3:]) + 1 if last and last.student_id.startswith('STU') else 1
    return f'STU{num:04d}'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png','jpg','jpeg','gif','pdf','doc','docx','mp4','webm','mp3','wav'}

def get_arabic_rank(score):
    if score >= 90: return 'محترف'
    elif score >= 70: return 'متوسط'
    return 'مبتدئ'

# ---------- المسارات الأساسية ----------
@app.route('/')
def index():
    return render_template('index.html')

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
            if user.banned:
                flash('تم حظر حسابك. تواصل مع المشرف.', 'danger')
                return redirect(url_for('login'))
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
    achievements = UserAchievement.query.filter_by(user_id=current_user.id).all()
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
    return render_template('profile.html', user=current_user, achievements=achievements)

@app.route('/student/<int:user_id>')
def public_profile(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('لا يمكن عرض ملف المشرف', 'warning')
        return redirect(url_for('students'))
    achievements = UserAchievement.query.filter_by(user_id=user.id).all()
    return render_template('public_profile.html', user=user, achievements=achievements)

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

@app.route('/students')
@login_required
def students():
    users = User.query.filter(User.role != 'admin', User.banned == False).all()
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
    prev_lesson = Lesson.query.filter(Lesson.order < lesson.order).order_by(Lesson.order.desc()).first()
    next_lesson = Lesson.query.filter(Lesson.order > lesson.order).order_by(Lesson.order.asc()).first()
    return render_template('lesson_detail.html', lesson=lesson, prev=prev_lesson, next=next_lesson)

# ---------- صفحة أنواع الاختبارات (مضمنة مباشرة) ----------
@app.route('/tests')
@login_required
def tests():
    lessons = Lesson.query.order_by(Lesson.order).all()
    html = '''
    {% extends "base.html" %}
    {% block content %}
    <h2>📝 الاختبارات</h2>
    <div class="row mt-4">
        <div class="col-md-4">
            <div class="card text-center">
                <div class="card-body">
                    <h5>🎲 اختبار عشوائي شامل</h5>
                    <p>30 سؤالاً من جميع الدروس<br>الوقت: 30 دقيقة</p>
                    <a href="/test" class="btn btn-primary">ابدأ</a>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card text-center">
                <div class="card-body">
                    <h5>⚡ اختبار سرعة</h5>
                    <p>30 سؤالاً عشوائياً<br>الوقت: 10 دقائق فقط</p>
                    <a href="/test/speed" class="btn btn-warning">ابدأ</a>
                </div>
            </div>
        </div>
    </div>
    <h4 class="mt-5">📚 اختبارات حسب الموضوع</h4>
    <div class="row">
    '''
    for lesson in lessons:
        html += f'''
        <div class="col-md-4 mb-3">
            <div class="card h-100">
                <div class="card-body">
                    <h6>{lesson.order}. {lesson.title}</h6>
                    <a href="/test/subject/{lesson.id}" class="btn btn-outline-success btn-sm">اختبار هذا الدرس</a>
                </div>
            </div>
        </div>
        '''
    html += '</div>{% endblock %}'
    return render_template_string(html, lessons=lessons)

# ---------- الاختبار حسب الموضوع ----------
@app.route('/test/subject/<int:lesson_id>')
@login_required
def test_subject_start(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    questions = Question.query.filter_by(lesson_id=lesson_id).order_by(db.func.random()).all()
    if len(questions) == 0:
        flash('لا توجد أسئلة لهذا الدرس بعد.', 'warning')
        return redirect(url_for('tests'))
    session['test_questions'] = [{'id': q.id, 'type': q.question_type} for q in questions]
    session['current_q_index'] = 0
    session['score'] = 0
    session['answers'] = []
    session['test_type'] = 'subject'
    session['test_start_time'] = time.time()
    session['test_total_time'] = len(questions) * 60
    return redirect(url_for('test_question'))

# ---------- اختبار السرعة ----------
@app.route('/test/speed')
@login_required
def test_speed_start():
    questions = Question.query.order_by(db.func.random()).limit(30).all()
    if len(questions) == 0:
        flash('لا توجد أسئلة.', 'warning')
        return redirect(url_for('tests'))
    session['test_questions'] = [{'id': q.id, 'type': q.question_type} for q in questions]
    session['current_q_index'] = 0
    session['score'] = 0
    session['answers'] = []
    session['test_type'] = 'speed'
    session['test_start_time'] = time.time()
    session['test_total_time'] = 600
    return redirect(url_for('test_question'))

# ---------- الاختبار العشوائي الشامل ----------
@app.route('/test')
@login_required
def test_start():
    questions = Question.query.order_by(db.func.random()).limit(30).all()
    if len(questions) == 0:
        flash('لا توجد أسئلة.', 'warning')
        return redirect(url_for('tests'))
    session['test_questions'] = [{'id': q.id, 'type': q.question_type} for q in questions]
    session['current_q_index'] = 0
    session['score'] = 0
    session['answers'] = []
    session['test_type'] = 'random'
    session['test_start_time'] = time.time()
    session['test_total_time'] = 30 * 60
    return redirect(url_for('test_question'))

# ---------- دوال الاختبار المشتركة ----------
@app.route('/test/question')
@login_required
def test_question():
    ids = session.get('test_questions')
    if not ids: return redirect(url_for('tests'))
    idx = session.get('current_q_index', 0)
    if idx >= len(ids): return redirect(url_for('test_result'))
    qdata = ids[idx]
    question = Question.query.get(qdata['id'])
    elapsed = time.time() - session.get('test_start_time', time.time())
    total_time = session.get('test_total_time', 30*60)
    remaining = max(0, total_time - int(elapsed))
    test_type = session.get('test_type', 'random')
    lesson = Lesson.query.get(question.lesson_id) if question.lesson_id else None
    return render_template('test.html', question=question, index=idx+1, total=len(ids),
                           remaining=remaining, test_type=test_type, lesson=lesson)

@app.route('/test/answer', methods=['POST'])
@login_required
def test_answer():
    answer = request.form.get('answer')
    ids = session.get('test_questions')
    idx = session.get('current_q_index', 0)
    if ids and idx < len(ids):
        question = Question.query.get(ids[idx]['id'])
        correct = (answer and answer == question.correct_answer)
        if correct:
            session['score'] = session.get('score', 0) + 1
        ans = session.get('answers', [])
        ans.append({'question_id': ids[idx]['id'], 'user_answer': answer, 'correct': correct})
        session['answers'] = ans
    session['current_q_index'] = idx + 1
    return redirect(url_for('test_question'))

@app.route('/test/result')
@login_required
def test_result():
    score = session.get('score', 0)
    ids = session.get('test_questions', [])
    total = len(ids)
    percentage = (score / total * 100) if total > 0 else 0
    answers = session.get('answers', [])
    test_type = session.get('test_type', 'random')
    result = TestResult(user_id=current_user.id, score=percentage, total_questions=total,
                        answers=json.dumps(answers), test_type=test_type)
    db.session.add(result)
    current_user.level = get_arabic_rank(percentage)
    db.session.commit()
    session.pop('test_questions', None)
    session.pop('current_q_index', None)
    session.pop('score', None)
    session.pop('answers', None)
    session.pop('test_start_time', None)
    session.pop('test_total_time', None)
    session.pop('test_type', None)
    return render_template('test_result.html', score=score, total=total, percentage=percentage,
                           answers=answers, result_id=result.id, test_type=test_type)

@app.route('/statistics')
@login_required
def statistics():
    total_lessons = Lesson.query.count()
    completed = LessonProgress.query.filter_by(user_id=current_user.id).count()
    progress = (completed/total_lessons*100) if total_lessons else 0
    avg_score = db.session.query(db.func.avg(TestResult.score)).filter_by(user_id=current_user.id).scalar() or 0
    return render_template('statistics.html', completed=completed, total_lessons=total_lessons,
                           progress_percent=round(progress,1), avg_score=round(avg_score,1))

@app.route('/chat')
@login_required
def chat():
    return render_template('chat.html')

# ---------- لوحة التحكم ----------
def admin_required(f):
    from functools import wraps
    @wraps(f)
    @login_required
    def dec(*a,**k):
        if current_user.role != 'admin': abort(403)
        return f(*a,**k)
    return dec

@app.route('/admin')
@admin_required
def admin_dashboard():
    user_count = User.query.count()
    lesson_count = Lesson.query.count()
    test_count = TestResult.query.count()
    avg_score = db.session.query(db.func.avg(TestResult.score)).scalar() or 0
    return render_template('admin/dashboard.html', user_count=user_count, lesson_count=lesson_count, test_count=test_count, avg_score=avg_score)

@app.route('/admin/reset_db')
@admin_required
def admin_reset_db():
    try:
        db.drop_all()
        db.create_all()
        seed_database()
        flash('✅ تم إعادة تعيين قاعدة البيانات بنجاح. تم إنشاء حساب المشرف الافتراضي.', 'success')
    except Exception as e:
        flash(f'❌ حدث خطأ أثناء إعادة التعيين: {str(e)}', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.order_by(User.last_seen.desc()).all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/ban/<int:user_id>')
@admin_required
def ban_user(user_id):
    user = User.query.get_or_404(user_id)
    user.banned = not user.banned
    db.session.commit()
    flash(f'تم تغيير حالة الحظر لـ {user.full_name}', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/recovery-requests')
@admin_required
def admin_recovery():
    requests = RecoveryRequest.query.filter_by(resolved=False).order_by(RecoveryRequest.timestamp.desc()).all()
    return render_template('admin/recovery_requests.html', requests=requests)

@app.route('/admin/recovery/resolve/<int:req_id>', methods=['POST'])
@admin_required
def resolve_recovery(req_id):
    req = RecoveryRequest.query.get_or_404(req_id)
    user = User.query.get(req.user_id)
    if req.type == 'username':
        flash(f'اسم المستخدم: {user.username} | البريد: {user.email_or_phone}', 'info')
    else:
        new_pass = ''.join(random.choices(string.ascii_letters+string.digits, k=8))
        user.password = generate_password_hash(new_pass)
        db.session.commit()
        flash(f'كلمة المرور الجديدة: {new_pass} | تواصل مع {user.email_or_phone}', 'success')
    req.resolved = True
    db.session.commit()
    return redirect(url_for('admin_recovery'))

@app.route('/admin/lessons')
@admin_required
def admin_lessons():
    lessons = Lesson.query.order_by(Lesson.order).all()
    return render_template('admin/content_lessons.html', lessons=lessons)

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
    questions = Question.query.all()
    return render_template('admin/content_questions.html', questions=questions)

@app.route('/admin/question/add', methods=['POST'])
@admin_required
def add_question():
    db.session.add(Question(
        question_text=request.form['question_text'], question_type=request.form.get('question_type','mcq'),
        option_a=request.form.get('option_a'), option_b=request.form.get('option_b'),
        option_c=request.form.get('option_c'), option_d=request.form.get('option_d'),
        correct_answer=request.form['correct_answer'],
        lesson_id=request.form.get('lesson_id', type=int)))
    db.session.commit()
    return redirect(url_for('admin_questions'))

@app.route('/admin/question/edit/<int:id>', methods=['POST'])
@admin_required
def edit_question(id):
    q = Question.query.get_or_404(id)
    for f in ['question_text','question_type','option_a','option_b','option_c','option_d','correct_answer','lesson_id']:
        if f in request.form:
            val = request.form[f]
            if f == 'lesson_id':
                val = int(val) if val else None
            setattr(q, f, val)
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
    resources = Resource.query.all()
    return render_template('admin/resource_library.html', resources=resources)

@app.route('/admin/resource/add', methods=['POST'])
@admin_required
def add_resource():
    title = request.form['title']
    rtype = request.form['type']
    url = ''
    if rtype in ('pdf','video'):
        file = request.files.get('file')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            url = url_for('static', filename='uploads/'+filename)
        else:
            url = request.form.get('url','')
    else:
        url = request.form.get('url','')
    db.session.add(Resource(title=title, type=rtype, url=url))
    db.session.commit()
    return redirect(url_for('admin_resources'))

@app.route('/admin/resource/delete/<int:id>')
@admin_required
def delete_resource(id):
    Resource.query.filter_by(id=id).delete()
    db.session.commit()
    return redirect(url_for('admin_resources'))

@app.route('/admin/notifications', methods=['GET','POST'])
@admin_required
def admin_notifications():
    if request.method == 'POST':
        msg = request.form['message']
        for u in User.query.filter_by(role='student').all():
            db.session.add(Notification(user_id=u.id, content=msg))
        db.session.commit()
        flash('تم الإرسال', 'success')
    return render_template('admin/notifications.html')

@app.route('/admin/audit-log')
@admin_required
def admin_audit():
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(200).all()
    return render_template('admin/audit_log.html', logs=logs)

@app.route('/admin/announcements', methods=['GET','POST'])
@admin_required
def admin_announcements():
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        db.session.add(Announcement(title=title, content=content))
        db.session.commit()
        flash('تم إضافة الإعلان', 'success')
    anns = Announcement.query.order_by(Announcement.created_at.desc()).all()
    return render_template('admin/announcements.html', announcements=anns)

# ---------- WebSocket ----------
@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated and not current_user.banned:
        current_user.status = 'متصل'
        current_user.last_seen = datetime.utcnow()
        db.session.commit()
        online_users.setdefault(current_user.id, set()).add(request.sid)
        emit('update_online', get_online_users_with_status(), broadcast=True)

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
                emit('update_online', get_online_users_with_status(), broadcast=True)

def get_online_users_with_status():
    result = []
    for uid in online_users:
        u = User.query.get(uid)
        if u:
            result.append({
                'id': uid,
                'name': u.full_name if u.show_real_name else u.username,
                'status': u.status,
                'last_seen': u.last_seen.strftime('%H:%M') if u.last_seen else ''
            })
    return result

@socketio.on('send_message')
def handle_message(data):
    if not current_user.is_authenticated or current_user.banned: return
    text = data.get('text','').strip()
    recipient_id = data.get('recipient_id')
    reply_to = data.get('reply_to')
    if not text and not data.get('file'): return
    msg = Message(sender_id=current_user.id, text=text)
    if recipient_id: msg.recipient_id = int(recipient_id)
    if reply_to: msg.reply_to_id = int(reply_to)
    db.session.add(msg)
    db.session.commit()
    sender_name = current_user.full_name if current_user.show_real_name else current_user.username
    sender_pic = current_user.profile_pic if current_user.profile_pic != 'default.png' else ''
    msg_data = {
        'id': msg.id, 'sender_id': current_user.id, 'sender_name': sender_name,
        'sender_pic': sender_pic, 'text': msg.text, 'timestamp': msg.timestamp.strftime('%H:%M'),
        'reply_to': msg.reply_to_id, 'edited': False, 'file_path': None,
        'recipient_id': msg.recipient_id
    }
    if recipient_id:
        emit('new_private_message', msg_data, room=f'user_{recipient_id}')
        emit('new_private_message', msg_data, room=request.sid)
    else:
        emit('new_message', msg_data, broadcast=True)

@socketio.on('edit_message')
def handle_edit(data):
    if not current_user.is_authenticated: return
    msg_id = data.get('message_id')
    new_text = data.get('text','').strip()
    msg = Message.query.get(msg_id)
    if not msg: return
    if current_user.role == 'admin' or (msg.sender_id == current_user.id and (datetime.utcnow() - msg.timestamp).seconds < 300):
        msg.text = new_text
        msg.edited = True
        msg.edited_at = datetime.utcnow()
        db.session.commit()
        emit('message_edited', {'message_id': msg_id, 'text': new_text}, broadcast=True)

@socketio.on('delete_message')
def handle_delete(data):
    if not current_user.is_authenticated: return
    msg_id = data.get('message_id')
    msg = Message.query.get(msg_id)
    if not msg: return
    if current_user.role == 'admin' or (msg.sender_id == current_user.id and (datetime.utcnow() - msg.timestamp).seconds < 300):
        db.session.delete(msg)
        db.session.commit()
        emit('message_deleted', {'message_id': msg_id}, broadcast=True)

@app.route('/upload_chat_file', methods=['POST'])
@login_required
def upload_chat_file():
    file = request.files.get('file')
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{current_user.id}_{int(time.time())}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        msg = Message(sender_id=current_user.id, text='', file_path=filename)
        recipient_id = request.form.get('recipient_id')
        if recipient_id:
            msg.recipient_id = int(recipient_id)
        db.session.add(msg)
        db.session.commit()
        file_url = url_for('static', filename='uploads/'+filename)
        sender_name = current_user.full_name if current_user.show_real_name else current_user.username
        msg_data = {
            'id': msg.id, 'sender_id': current_user.id, 'sender_name': sender_name,
            'text': '', 'timestamp': msg.timestamp.strftime('%H:%M'),
            'file_path': file_url, 'edited': False, 'recipient_id': msg.recipient_id
        }
        socketio.emit('new_message', msg_data, broadcast=True)
        return jsonify({'success': True, 'file_url': file_url})
    return jsonify({'success': False})

@app.route('/api/messages')
@login_required
def api_messages():
    msgs = Message.query.filter((Message.recipient_id.is_(None)) | (Message.recipient_id == current_user.id) | (Message.sender_id == current_user.id)).order_by(Message.timestamp.asc()).all()
    res = []
    for m in msgs:
        s = m.sender
        sname = s.full_name if s.show_real_name else s.username
        spic = s.profile_pic if s.profile_pic != 'default.png' else ''
        res.append({
            'id': m.id, 'sender_id': m.sender_id, 'sender_name': sname,
            'sender_pic': spic,
            'text': m.text, 'timestamp': m.timestamp.strftime('%H:%M'),
            'reply_to': m.reply_to_id, 'edited': m.edited,
            'file_path': url_for('static', filename='uploads/'+m.file_path) if m.file_path else None,
            'recipient_id': m.recipient_id
        })
    return jsonify(res)

@app.route('/api/users')
@login_required
def api_users():
    users = User.query.filter(User.id != current_user.id, User.banned == False).all()
    return jsonify([{'id': u.id, 'name': u.full_name if u.show_real_name else u.username, 'status': u.status, 'last_seen': u.last_seen.strftime('%H:%M') if u.last_seen else ''} for u in users])

if __name__ == '__main__':
    with app.app_context():
        seed_database()
    port = int(os.environ.get("PORT", 5000))
    print(f"✅ الموقع يعمل على المنفذ: {port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=False)