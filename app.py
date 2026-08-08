import os, json, time, shutil
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, abort, send_from_directory
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
        ('ما المكون المسؤول عن معالجة البيانات؟', 'mcq', 'المعالج', 'الذاكرة', 'القرص الصلب', 'الشاشة', 'a'),
        ('أي مما يلي وحدة إدخال؟', 'mcq', 'الشاشة', 'الطابعة', 'الفأرة', 'السماعات', 'c'),
        ('لإعادة تسمية ملف نضغط', 'mcq', 'F2', 'F3', 'F4', 'F5', 'a'),
        ('Windows+E يفتح', 'mcq', 'المستندات', 'مستكشف الملفات', 'الإعدادات', 'الطابعة', 'b'),
        ('لتحديد الكل نضغط', 'mcq', 'Ctrl+A', 'Ctrl+C', 'Ctrl+V', 'Ctrl+X', 'a'),
        ('RAM تعني ذاكرة الوصول العشوائي', 'tf', None, None, None, None, 't'),
        ('Ctrl+Z للتراجع', 'tf', None, None, None, None, 't'),
        ('لحفظ ملف نضغط Ctrl+S', 'tf', None, None, None, None, 't'),
        ('امتداد العروض التقديمية هو .docx', 'tf', None, None, None, None, 'f'),
        ('وورد من برامج النظام', 'tf', None, None, None, None, 'f'),
        ('لنسخ ملف نستخدم قص', 'tf', None, None, None, None, 'f'),
        ('الأيقونة هي صورة تمثل برنامج', 'tf', None, None, None, None, 't'),
        ('القرص الصلب SSD أسرع من HDD', 'tf', None, None, None, None, 't'),
        ('الطابعة وحدة إدخال', 'tf', None, None, None, None, 'f'),
        ('السماعات وحدة إخراج', 'tf', None, None, None, None, 't'),
        ('القرص الصلب وحدة تخزين', 'tf', None, None, None, None, 't'),
        ('Ctrl+V لصق', 'tf', None, None, None, None, 't'),
        ('Ctrl+X قص', 'tf', None, None, None, None, 't'),
        ('امتداد الوورد .pptx', 'tf', None, None, None, None, 'f'),
        ('امتداد الإكسل .xlsx', 'tf', None, None, None, None, 't'),
        ('يمكن إدراج صورة في وورد', 'tf', None, None, None, None, 't'),
        ('يستخدم باوربوينت للعروض', 'tf', None, None, None, None, 't'),
        ('SUM دالة جمع في إكسل', 'tf', None, None, None, None, 't'),
        ('F5 بدء عرض باوربوينت', 'tf', None, None, None, None, 't'),
        ('الحاسوب المحمول يسمى لابتوب', 'tf', None, None, None, None, 't'),
        ('الخادم حاسوب عملاق', 'tf', None, None, None, None, 'f'),
        ('الماوس وحدة إخراج', 'tf', None, None, None, None, 'f'),
        ('الميكروفون وحدة إدخال', 'tf', None, None, None, None, 't'),
        ('الشاشة وحدة إخراج', 'tf', None, None, None, None, 't'),
        ('الفلاش ميموري وحدة تخزين', 'tf', None, None, None, None, 't'),
    ]

    for q in questions:
        if len(q) == 7:
            text, qtype, a, b, c, d, ans = q
            if not Question.query.filter_by(question_text=text).first():
                db.session.add(Question(question_text=text, question_type=qtype, option_a=a, option_b=b, option_c=c, option_d=d, correct_answer=ans))

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

@app.route('/test')
@login_required
def test_start():
    questions = Question.query.order_by(db.func.random()).limit(30).all()
    if len(questions) < 30:
        questions = Question.query.order_by(db.func.random()).all()
    session['test_questions'] = [{'id': q.id, 'type': q.question_type} for q in questions[:30]]
    session['current_q_index'] = 0
    session['score'] = 0
    session['answers'] = []
    session['test_start_time'] = time.time()
    return redirect(url_for('test_question'))

@app.route('/test/question')
@login_required
def test_question():
    ids = session.get('test_questions')
    if not ids: return redirect(url_for('test_start'))
    idx = session.get('current_q_index', 0)
    if idx >= len(ids): return redirect(url_for('test_result'))
    qdata = ids[idx]
    question = Question.query.get(qdata['id'])
    elapsed = time.time() - session.get('test_start_time', time.time())
    remaining = max(0, 30*60 - int(elapsed))
    return render_template('test.html', question=question, index=idx+1, total=len(ids), remaining=remaining)

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
    result = TestResult(user_id=current_user.id, score=percentage, total_questions=total, answers=json.dumps(answers))
    db.session.add(result)
    current_user.level = get_arabic_rank(percentage)
    db.session.commit()
    session.pop('test_questions', None)
    session.pop('current_q_index', None)
    session.pop('score', None)
    session.pop('answers', None)
    session.pop('test_start_time', None)
    return render_template('test_result.html', score=score, total=total, percentage=percentage, answers=answers, result_id=result.id)

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
    """إعادة إنشاء جميع الجداول والبيانات الافتراضية"""
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
        correct_answer=request.form['correct_answer']))
    db.session.commit()
    return redirect(url_for('admin_questions'))

@app.route('/admin/question/edit/<int:id>', methods=['POST'])
@admin_required
def edit_question(id):
    q = Question.query.get_or_404(id)
    for f in ['question_text','question_type','option_a','option_b','option_c','option_d','correct_answer']:
        if f in request.form: setattr(q, f, request.form[f])
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
    emit('new_message', {
        'id': msg.id,
        'sender_id': current_user.id,
        'sender_name': sender_name,
        'text': msg.text,
        'timestamp': msg.timestamp.strftime('%H:%M'),
        'file_path': None,
        'recipient_id': msg.recipient_id
    }, broadcast=True)

if __name__ == '__main__':
    with app.app_context():
        seed_database()
    port = int(os.environ.get("PORT", 5000))
    print(f"✅ الموقع يعمل على المنفذ: {port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=False)