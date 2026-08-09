import os
import json
import random
import math
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from PIL import Image
from fpdf import FPDF
from sqlalchemy import inspect, text
import io

load_dotenv()

# ==================== الإعدادات الأساسية ====================
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-please-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///mycourse.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_CONTENT_LENGTH = 5 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs('static/css', exist_ok=True)
os.makedirs('static/js', exist_ok=True)

# ==================== قاعدة البيانات ====================
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'يرجى تسجيل الدخول أولاً.'
login_manager.login_message_category = 'warning'

# ==================== ديكور صلاحيات المسؤول ====================
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# ==================== دالة ترقية قاعدة البيانات ====================
def upgrade_database():
    with app.app_context():
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        is_postgres = 'postgres' in db.engine.url.drivername

        if 'lesson_progress' in tables:
            columns = [c['name'] for c in inspector.get_columns('lesson_progress')]
            missing = []
            required_columns = ['is_completed', 'last_watched', 'completed_at']
            for col in required_columns:
                if col not in columns:
                    missing.append(col)

            if missing:
                print(f"⚠️ الأعمدة المفقودة في lesson_progress: {missing}")
                for col in missing:
                    try:
                        if col == 'is_completed':
                            sql_type = 'BOOLEAN DEFAULT FALSE' if is_postgres else 'BOOLEAN DEFAULT 0'
                        elif col == 'last_watched':
                            sql_type = 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP' if is_postgres else 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'
                        elif col == 'completed_at':
                            sql_type = 'TIMESTAMP' if is_postgres else 'TIMESTAMP'
                        else:
                            sql_type = 'TEXT'
                        db.session.execute(text(f'ALTER TABLE lesson_progress ADD COLUMN {col} {sql_type};'))
                        print(f"✅ تم إضافة العمود {col}.")
                    except Exception as e:
                        print(f"⚠️ فشل إضافة العمود {col}: {e}")
                db.session.commit()
            else:
                print("✅ جميع الأعمدة المطلوبة موجودة في lesson_progress.")
        else:
            print("⚠️ جدول lesson_progress غير موجود، سيتم إنشاؤه لاحقاً.")

        if 'categories' not in tables:
            print("⚠️ جاري إنشاء جدول categories...")
            db.create_all()
            print("✅ تم إنشاء الجداول المفقودة.")

        if 'lessons' in tables:
            columns = [c['name'] for c in inspector.get_columns('lessons')]
            if 'category_id' not in columns:
                print("⚠️ جاري إضافة عمود category_id إلى lessons...")
                try:
                    if 'categories' not in tables:
                        db.create_all()
                    db.session.execute(text('ALTER TABLE lessons ADD COLUMN category_id INTEGER REFERENCES categories(id);'))
                    db.session.commit()
                    print("✅ تم إضافة العمود category_id.")
                except Exception as e:
                    print(f"⚠️ فشل إضافة العمود category_id: {e}")
            else:
                print("✅ العمود category_id موجود مسبقاً.")

# ==================== نماذج قاعدة البيانات ====================
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), unique=True, nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    profile_pic = db.Column(db.String(255), nullable=False, default='default.png')
    bio = db.Column(db.Text, nullable=True)
    social_links = db.Column(db.Text, nullable=True, default='{}')
    is_admin = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    xp_points = db.Column(db.Integer, default=0)
    level = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_password_change = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)

    quiz_attempts = db.relationship('QuizAttempt', backref='user', lazy=True, cascade='all, delete-orphan')
    badges = db.relationship('UserBadge', backref='user', lazy=True, cascade='all, delete-orphan')
    lesson_progress = db.relationship('LessonProgress', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        self.last_password_change = datetime.utcnow()

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_social_links(self):
        try:
            return json.loads(self.social_links) if self.social_links else {}
        except:
            return {}

    def set_social_links(self, links_dict):
        self.social_links = json.dumps(links_dict)

class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(50), nullable=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    lessons = db.relationship('Lesson', backref='category', lazy=True, cascade='all, delete-orphan')

class Lesson(db.Model):
    __tablename__ = 'lessons'
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    content = db.Column(db.Text, nullable=True)
    youtube_url = db.Column(db.String(255), nullable=True)
    order = db.Column(db.Integer, default=0)
    is_published = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    questions = db.relationship('Question', backref='lesson', lazy=True, cascade='all, delete-orphan')
    progress = db.relationship('LessonProgress', backref='lesson', lazy=True, cascade='all, delete-orphan')

class LessonProgress(db.Model):
    __tablename__ = 'lesson_progress'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lessons.id'), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    last_watched = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lessons.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(255), nullable=True)
    option_b = db.Column(db.String(255), nullable=True)
    option_c = db.Column(db.String(255), nullable=True)
    option_d = db.Column(db.String(255), nullable=True)
    correct_answer = db.Column(db.String(255), nullable=False)
    difficulty = db.Column(db.String(20), default='medium')

class QuizAttempt(db.Model):
    __tablename__ = 'quiz_attempts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    quiz_type = db.Column(db.String(50), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lessons.id'), nullable=True)
    score = db.Column(db.Float, default=0.0)
    total_questions = db.Column(db.Integer, default=0)
    correct_count = db.Column(db.Integer, default=0)
    time_taken = db.Column(db.Integer, default=0)
    completed_at = db.Column(db.DateTime, default=datetime.utcnow)
    answers = db.relationship('UserAnswer', backref='attempt', lazy=True, cascade='all, delete-orphan')

class UserAnswer(db.Model):
    __tablename__ = 'user_answers'
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey('quiz_attempts.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    selected_answer = db.Column(db.String(255), nullable=False)
    is_correct = db.Column(db.Boolean, default=False)

class Badge(db.Model):
    __tablename__ = 'badges'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    icon = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    condition_type = db.Column(db.String(50), nullable=False)

class UserBadge(db.Model):
    __tablename__ = 'user_badges'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    badge_id = db.Column(db.Integer, db.ForeignKey('badges.id'), nullable=False)
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)

class Announcement(db.Model):
    __tablename__ = 'announcements'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_published = db.Column(db.Boolean, default=True)

class PasswordResetRequest(db.Model):
    __tablename__ = 'password_reset_requests'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(255), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(255), nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# ==================== تسجيل مدير الدخول ====================
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==================== دوال مساعدة ====================
def generate_student_id():
    last_user = User.query.order_by(User.id.desc()).first()
    if last_user and last_user.student_id and last_user.student_id.startswith('STU'):
        try:
            num = int(last_user.student_id[3:]) + 1
            return f'STU{num:04d}'
        except:
            return 'STU0001'
    return 'STU0001'

def log_activity(user_id, action, ip=None):
    log = ActivityLog(user_id=user_id, action=action, ip_address=ip or request.remote_addr)
    db.session.add(log)
    db.session.commit()

# ==================== مسارات المصادقة والملف الشخصي ====================
@app.route('/', methods=['GET'])
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if not full_name or not email or not password:
            flash('جميع الحقول المطلوبة يجب تعبئتها.', 'danger')
            return render_template('register.html')
        if password != confirm:
            flash('كلمة المرور غير متطابقة.', 'danger')
            return render_template('register.html')
        if len(password) < 6:
            flash('كلمة المرور 6 أحرف على الأقل.', 'danger')
            return render_template('register.html')
        if User.query.filter((User.email == email) | (User.phone == phone if phone else False)).first():
            flash('البريد الإلكتروني أو رقم الهاتف مستخدم بالفعل.', 'danger')
            return render_template('register.html')
        new_user = User(
            student_id=generate_student_id(),
            full_name=full_name,
            email=email,
            phone=phone if phone else None,
            is_admin=False
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        log_activity(new_user.id, f'تسجيل حساب جديد: {new_user.student_id}')
        flash(f'تم إنشاء حسابك! معرفك: {new_user.student_id}', 'success')
        login_user(new_user, remember=True)
        return redirect(url_for('profile'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email_or_phone = request.form.get('email_or_phone', '').strip().lower()
        password = request.form.get('password', '')
        remember = 'remember' in request.form
        user = User.query.filter((User.email == email_or_phone) | (User.phone == email_or_phone)).first()
        if user and user.check_password(password):
            if user.is_banned:
                flash('هذا الحساب محظور.', 'danger')
                return render_template('login.html')
            login_user(user, remember=remember)
            user.last_seen = datetime.utcnow()
            db.session.commit()
            log_activity(user.id, f'تسجيل دخول: {user.student_id}')
            flash(f'مرحباً بعودتك {user.full_name}!', 'success')
            return redirect(url_for('dashboard'))
        flash('بيانات الدخول غير صحيحة.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    log_activity(current_user.id, f'تسجيل خروج: {current_user.student_id}')
    logout_user()
    flash('تم تسجيل الخروج.', 'info')
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        bio = request.form.get('bio', '').strip()
        social_links_str = request.form.get('social_links', '{}').strip()
        try:
            social_links = json.loads(social_links_str)
            if not isinstance(social_links, dict):
                raise ValueError()
        except:
            flash('الرابط الاجتماعي بصيغة JSON غير صحيحة.', 'danger')
            return render_template('profile.html', user=current_user)
        current_user.bio = bio
        current_user.set_social_links(social_links)
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename != '':
                if '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS:
                    if current_user.profile_pic != 'default.png':
                        old_path = os.path.join(app.config['UPLOAD_FOLDER'], current_user.profile_pic)
                        if os.path.exists(old_path):
                            os.remove(old_path)
                    filename = f"user_{current_user.id}_{datetime.utcnow().timestamp()}.{file.filename.rsplit('.', 1)[1].lower()}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    try:
                        img = Image.open(filepath)
                        img.thumbnail((300, 300))
                        img.save(filepath)
                    except:
                        pass
                    current_user.profile_pic = filename
                    flash('تم تحديث الصورة.', 'success')
                else:
                    flash('امتداد الملف غير مدعوم.', 'danger')
        db.session.commit()
        flash('تم تحديث الملف الشخصي.', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', user=current_user)

# ==================== المسارات العامة ====================
@app.route('/dashboard')
@login_required
def dashboard():
    lessons = Lesson.query.filter_by(is_published=True).order_by(Lesson.order).all()
    completed_count = LessonProgress.query.filter_by(user_id=current_user.id, is_completed=True).count()
    total_lessons = Lesson.query.filter_by(is_published=True).count()
    recent_attempts = QuizAttempt.query.filter_by(user_id=current_user.id).order_by(QuizAttempt.completed_at.desc()).limit(5).all()
    avg_score = sum(a.score for a in recent_attempts) / len(recent_attempts) if recent_attempts else 0
    recent_students = User.query.filter_by(is_admin=False).order_by(User.created_at.desc()).limit(5).all()
    categories = Category.query.order_by(Category.order).all()
    return render_template('index.html', user=current_user, lessons=lessons, completed_count=completed_count,
                         total_lessons=total_lessons, avg_score=round(avg_score, 1), recent_students=recent_students,
                         categories=categories)

@app.route('/lessons')
@login_required
def categories_list():
    categories = Category.query.order_by(Category.order).all()
    return render_template('categories.html', categories=categories)

@app.route('/category/<int:category_id>')
@login_required
def category_lessons(category_id):
    category = Category.query.get_or_404(category_id)
    lessons = Lesson.query.filter_by(category_id=category.id, is_published=True).order_by(Lesson.order).all()
    progress_dict = {}
    for l in lessons:
        prog = LessonProgress.query.filter_by(user_id=current_user.id, lesson_id=l.id).first()
        progress_dict[l.id] = prog.is_completed if prog else False
    return render_template('category_lessons.html', category=category, lessons=lessons, progress_dict=progress_dict)

@app.route('/lesson/<int:lesson_id>')
@login_required
def lesson_detail(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    if not lesson.is_published:
        flash('الدرس غير منشور.', 'warning')
        return redirect(url_for('categories_list'))
    prev_lesson = Lesson.query.filter(
        Lesson.category_id == lesson.category_id,
        Lesson.order < lesson.order,
        Lesson.is_published == True
    ).order_by(Lesson.order.desc()).first()
    next_lesson = Lesson.query.filter(
        Lesson.category_id == lesson.category_id,
        Lesson.order > lesson.order,
        Lesson.is_published == True
    ).order_by(Lesson.order.asc()).first()
    progress = LessonProgress.query.filter_by(user_id=current_user.id, lesson_id=lesson.id).first()
    is_completed = progress.is_completed if progress else False
    questions = Question.query.filter_by(lesson_id=lesson.id).all()
    return render_template('lesson_detail.html', lesson=lesson, prev_lesson=prev_lesson, next_lesson=next_lesson,
                         is_completed=is_completed, questions=questions, category=lesson.category)

@app.route('/complete_lesson/<int:lesson_id>', methods=['POST'])
@login_required
def complete_lesson(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    progress = LessonProgress.query.filter_by(user_id=current_user.id, lesson_id=lesson.id).first()
    if not progress:
        progress = LessonProgress(user_id=current_user.id, lesson_id=lesson.id)
        db.session.add(progress)
    if not progress.is_completed:
        progress.is_completed = True
        progress.completed_at = datetime.utcnow()
        current_user.xp_points += 50
        if current_user.xp_points >= current_user.level * 200:
            current_user.level += 1
            flash(f'🎉 ترقيت إلى المستوى {current_user.level}!', 'success')
        db.session.commit()
        log_activity(current_user.id, f'أكمل الدرس: {lesson.title}')
        flash('✅ تم إكمال الدرس!', 'success')
    else:
        flash('الدرس مكتمل مسبقاً.', 'info')
    return redirect(url_for('lesson_detail', lesson_id=lesson.id))

@app.route('/tests')
@login_required
def tests_home():
    lessons = Lesson.query.filter_by(is_published=True).order_by(Lesson.order).all()
    return render_template('tests.html', lessons=lessons)

@app.route('/start_test', methods=['POST'])
@login_required
def start_test():
    quiz_type = request.form.get('quiz_type')
    lesson_id = request.form.get('lesson_id')
    if quiz_type not in ['random', 'speed', 'subject']:
        flash('نوع غير صحيح.', 'danger')
        return redirect(url_for('tests_home'))
    if quiz_type == 'subject':
        if not lesson_id:
            flash('اختر درساً.', 'danger')
            return redirect(url_for('tests_home'))
        lesson = Lesson.query.get(int(lesson_id))
        if not lesson:
            flash('الدرس غير موجود.', 'danger')
            return redirect(url_for('tests_home'))
        questions = Question.query.filter_by(lesson_id=lesson.id).all()
        if not questions:
            flash('لا توجد أسئلة.', 'danger')
            return redirect(url_for('tests_home'))
        if len(questions) > 10:
            questions = random.sample(questions, 10)
        total_questions = len(questions)
    else:
        all_questions = Question.query.all()
        if not all_questions:
            flash('لا توجد أسئلة.', 'danger')
            return redirect(url_for('tests_home'))
        sample_size = min(10, len(all_questions))
        questions = random.sample(all_questions, sample_size)
        total_questions = sample_size
    random.shuffle(questions)
    session['quiz_data'] = {
        'questions': [q.id for q in questions],
        'total': total_questions,
        'current_index': 0,
        'answers': {},
        'quiz_type': quiz_type,
        'lesson_id': int(lesson_id) if quiz_type == 'subject' else None,
        'start_time': datetime.utcnow().isoformat()
    }
    return redirect(url_for('take_test'))

@app.route('/test')
@login_required
def take_test():
    quiz_data = session.get('quiz_data')
    if not quiz_data:
        flash('لم يبدأ اختبار.', 'warning')
        return redirect(url_for('tests_home'))
    current_index = quiz_data['current_index']
    total = quiz_data['total']
    if current_index >= total:
        return redirect(url_for('submit_test'))
    question_id = quiz_data['questions'][current_index]
    question = Question.query.get(question_id)
    if not question:
        flash('خطأ في السؤال.', 'danger')
        return redirect(url_for('tests_home'))
    options = [q for q in [question.option_a, question.option_b, question.option_c, question.option_d] if q] if question.type == 'MCQ' else ['صحيح', 'خطأ']
    elapsed_time = int((datetime.utcnow() - datetime.fromisoformat(quiz_data['start_time'])).total_seconds()) if quiz_data['quiz_type'] == 'speed' else 0
    return render_template('test.html', question=question, options=options, current_index=current_index+1,
                         total=total, quiz_type=quiz_data['quiz_type'], elapsed_time=elapsed_time)

@app.route('/submit_answer', methods=['POST'])
@login_required
def submit_answer():
    quiz_data = session.get('quiz_data')
    if not quiz_data:
        flash('انتهت الجلسة.', 'danger')
        return redirect(url_for('tests_home'))
    question_id = int(request.form.get('question_id'))
    selected = request.form.get('answer')
    if not selected:
        flash('اختر إجابة.', 'danger')
        return redirect(url_for('take_test'))
    current_index = quiz_data['current_index']
    if current_index >= len(quiz_data['questions']) or quiz_data['questions'][current_index] != question_id:
        flash('خطأ في الترتيب.', 'danger')
        return redirect(url_for('tests_home'))
    quiz_data['answers'][str(question_id)] = selected
    quiz_data['current_index'] = current_index + 1
    session['quiz_data'] = quiz_data
    if quiz_data['current_index'] >= quiz_data['total']:
        return redirect(url_for('submit_test'))
    return redirect(url_for('take_test'))

@app.route('/submit_test')
@login_required
def submit_test():
    quiz_data = session.get('quiz_data')
    if not quiz_data:
        flash('لا توجد بيانات.', 'danger')
        return redirect(url_for('tests_home'))
    answers = quiz_data['answers']
    question_ids = quiz_data['questions']
    total = quiz_data['total']
    correct_count = 0
    user_answers = []
    for q_id in question_ids:
        q = Question.query.get(q_id)
        if not q: continue
        selected = answers.get(str(q.id))
        is_correct = False
        if selected:
            is_correct = selected.strip() == q.correct_answer.strip()
            if is_correct: correct_count += 1
        user_answers.append({'question_id': q.id, 'selected': selected if selected else '(لم يجب)', 'is_correct': is_correct})
    score = (correct_count / total) * 100
    attempt = QuizAttempt(user_id=current_user.id, quiz_type=quiz_data['quiz_type'], lesson_id=quiz_data.get('lesson_id'),
                        score=score, total_questions=total, correct_count=correct_count, time_taken=0)
    db.session.add(attempt)
    db.session.flush()
    for ua in user_answers:
        db.session.add(UserAnswer(attempt_id=attempt.id, question_id=ua['question_id'], selected_answer=ua['selected'], is_correct=ua['is_correct']))
    earned_xp = correct_count * 10
    current_user.xp_points += earned_xp
    if current_user.xp_points >= current_user.level * 200:
        current_user.level += 1
        flash(f'🎉 ترقيت إلى المستوى {current_user.level}!', 'success')
    db.session.commit()
    log_activity(current_user.id, f'أنهى اختبار {quiz_data["quiz_type"]} بنسبة {score:.1f}%')
    session.pop('quiz_data', None)
    flash(f'✅ النتيجة: {score:.1f}%', 'success')
    return redirect(url_for('test_result', attempt_id=attempt.id))

@app.route('/test_result/<int:attempt_id>')
@login_required
def test_result(attempt_id):
    attempt = QuizAttempt.query.get_or_404(attempt_id)
    if attempt.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    questions_data = []
    for ua in attempt.answers:
        q = Question.query.get(ua.question_id)
        if q:
            questions_data.append({'question': q, 'selected': ua.selected_answer, 'is_correct': ua.is_correct, 'correct': q.correct_answer})
    return render_template('test_result.html', attempt=attempt, questions_data=questions_data)

# ========================================================
# ================ الميزات الجديدة =======================
# ========================================================

@app.route('/statistics')
@login_required
def statistics():
    total_lessons = Lesson.query.filter_by(is_published=True).count()
    completed_lessons = LessonProgress.query.filter_by(user_id=current_user.id, is_completed=True).count()
    completion_percentage = (completed_lessons / total_lessons * 100) if total_lessons > 0 else 0
    attempts = QuizAttempt.query.filter_by(user_id=current_user.id).order_by(QuizAttempt.completed_at).all()
    attempt_dates = [a.completed_at.strftime('%Y-%m-%d') for a in attempts]
    attempt_scores = [round(a.score, 1) for a in attempts]
    quiz_types = ['random', 'speed', 'subject']
    type_scores = {}
    for qt in quiz_types:
        qs = QuizAttempt.query.filter_by(user_id=current_user.id, quiz_type=qt).all()
        if qs:
            type_scores[qt] = round(sum(a.score for a in qs) / len(qs), 1)
        else:
            type_scores[qt] = 0
    best_attempt = QuizAttempt.query.filter_by(user_id=current_user.id).order_by(QuizAttempt.score.desc()).first()
    best_score = best_attempt.score if best_attempt else 0
    badge_count = UserBadge.query.filter_by(user_id=current_user.id).count()
    recent_attempts = QuizAttempt.query.filter_by(user_id=current_user.id).order_by(QuizAttempt.completed_at.desc()).limit(10).all()
    return render_template('statistics.html', 
                         user=current_user,
                         completion_percentage=round(completion_percentage, 1),
                         completed_lessons=completed_lessons,
                         total_lessons=total_lessons,
                         attempt_dates=attempt_dates,
                         attempt_scores=attempt_scores,
                         type_scores=type_scores,
                         best_score=round(best_score, 1),
                         badge_count=badge_count,
                         total_attempts=len(attempts),
                         recent_attempts=recent_attempts)

@app.route('/leaderboard')
@login_required
def leaderboard():
    top_students = User.query.filter_by(is_admin=False, is_banned=False).order_by(User.xp_points.desc(), User.level.desc()).limit(20).all()
    ranked_students = []
    for idx, student in enumerate(top_students, 1):
        completed = LessonProgress.query.filter_by(user_id=student.id, is_completed=True).count()
        ranked_students.append({
            'rank': idx,
            'user': student,
            'completed_lessons': completed
        })
    return render_template('leaderboard.html', ranked_students=ranked_students)

@app.route('/student/<int:student_id>')
@login_required
def public_profile(student_id):
    student = User.query.get_or_404(student_id)
    if student.is_banned and not current_user.is_admin:
        flash('هذا المستخدم محظور.', 'danger')
        return redirect(url_for('dashboard'))
    completed_lessons = LessonProgress.query.filter_by(user_id=student.id, is_completed=True).count()
    total_lessons = Lesson.query.filter_by(is_published=True).count()
    recent_attempts = QuizAttempt.query.filter_by(user_id=student.id).order_by(QuizAttempt.completed_at.desc()).limit(5).all()
    user_badges = UserBadge.query.filter_by(user_id=student.id).all()
    return render_template('public_profile.html', 
                         student=student,
                         completed_lessons=completed_lessons,
                         total_lessons=total_lessons,
                         recent_attempts=recent_attempts,
                         badges=user_badges)

@app.route('/generate_certificate')
@login_required
def generate_certificate():
    total_lessons = Lesson.query.filter_by(is_published=True).count()
    completed_lessons = LessonProgress.query.filter_by(user_id=current_user.id, is_completed=True).count()
    has_attempt = QuizAttempt.query.filter_by(user_id=current_user.id).first() is not None
    if completed_lessons < total_lessons or not has_attempt:
        flash('⚠️ لا يمكنك الحصول على الشهادة حتى تكمل جميع الدروس وتخوض اختباراً واحداً على الأقل.', 'warning')
        return redirect(url_for('statistics'))
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_fill_color(245, 247, 250)
    pdf.rect(10, 10, 277, 190, 'F')
    pdf.set_draw_color(212, 175, 55)
    pdf.set_line_width(2)
    pdf.rect(15, 15, 267, 180)
    pdf.set_text_color(0, 51, 102)
    pdf.set_font('Arial', 'B', 36)
    pdf.cell(0, 40, 'شهادة إتمام', ln=True, align='C')
    pdf.set_font('Arial', '', 20)
    pdf.cell(0, 15, 'تُمنح هذه الشهادة إلى:', ln=True, align='C')
    pdf.set_font('Arial', 'B', 32)
    pdf.set_text_color(212, 175, 55)
    pdf.cell(0, 30, current_user.full_name, ln=True, align='C')
    pdf.set_text_color(0, 0, 0)
    pdf.set_font('Arial', '', 18)
    pdf.cell(0, 20, f'بتقدير {current_user.level} ومجموع نقاط {current_user.xp_points} XP', ln=True, align='C')
    pdf.set_font('Arial', 'I', 14)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 30, f'تم الإصدار في: {datetime.utcnow().strftime("%Y-%m-%d")}', ln=True, align='C')
    pdf.set_font('Arial', '', 16)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 20, 'مدير المنصة', ln=True, align='C')
    pdf.line(120, 205, 180, 205)
    pdf_output = io.BytesIO()
    pdf_output.write(pdf.output(dest='S').encode('latin1'))
    pdf_output.seek(0)
    return send_file(pdf_output, as_attachment=True, download_name=f'شهادة_{current_user.student_id}.pdf', mimetype='application/pdf')

# ========================================================
# =================== لوحة تحكم المسؤول ===================
# ========================================================

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    total_users = User.query.count()
    total_lessons = Lesson.query.count()
    total_questions = Question.query.count()
    total_attempts = QuizAttempt.query.count()
    total_categories = Category.query.count()
    recent_logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(10).all()
    return render_template('admin/dashboard.html', 
                         total_users=total_users, 
                         total_lessons=total_lessons,
                         total_questions=total_questions,
                         total_attempts=total_attempts,
                         total_categories=total_categories,
                         recent_logs=recent_logs)

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/user/<int:user_id>/toggle_ban', methods=['POST'])
@login_required
@admin_required
def admin_toggle_ban(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        flash('لا يمكن حظر المسؤول.', 'danger')
        return redirect(url_for('admin_users'))
    user.is_banned = not user.is_banned
    db.session.commit()
    log_activity(current_user.id, f'{"حظر" if user.is_banned else "فك حظر"} المستخدم {user.student_id}')
    flash(f'تم {"حظر" if user.is_banned else "فك حظر"} المستخدم.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/user/<int:user_id>/toggle_admin', methods=['POST'])
@login_required
@admin_required
def admin_toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('لا يمكن تعديل صلاحيتك الذاتية.', 'danger')
        return redirect(url_for('admin_users'))
    user.is_admin = not user.is_admin
    db.session.commit()
    log_activity(current_user.id, f'{"رفع" if user.is_admin else "تنزيل"} صلاحية المستخدم {user.student_id}')
    flash(f'تم تحديث صلاحية المستخدم.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        flash('لا يمكن حذف المسؤول.', 'danger')
        return redirect(url_for('admin_users'))
    db.session.delete(user)
    db.session.commit()
    log_activity(current_user.id, f'حذف المستخدم {user.student_id}')
    flash('تم حذف المستخدم نهائياً.', 'success')
    return redirect(url_for('admin_users'))

# ==================== إدارة التصنيفات ====================
@app.route('/admin/categories', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_categories():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        icon = request.form.get('icon', 'fa-folder')
        order = request.form.get('order', 0)
        if not name:
            flash('اسم التصنيف مطلوب.', 'danger')
        else:
            category = Category(name=name, description=description, icon=icon, order=int(order))
            db.session.add(category)
            db.session.commit()
            log_activity(current_user.id, f'أضاف تصنيفاً: {name}')
            flash('تم إضافة التصنيف.', 'success')
        return redirect(url_for('admin_categories'))
    categories = Category.query.order_by(Category.order).all()
    return render_template('admin/categories.html', categories=categories)

@app.route('/admin/category/<int:category_id>/edit', methods=['POST'])
@login_required
@admin_required
def admin_edit_category(category_id):
    category = Category.query.get_or_404(category_id)
    category.name = request.form.get('name')
    category.description = request.form.get('description')
    category.icon = request.form.get('icon', 'fa-folder')
    category.order = int(request.form.get('order', 0))
    db.session.commit()
    log_activity(current_user.id, f'عدل تصنيفاً: {category.name}')
    flash('تم تحديث التصنيف.', 'success')
    return redirect(url_for('admin_categories'))

@app.route('/admin/category/<int:category_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_category(category_id):
    category = Category.query.get_or_404(category_id)
    if category.lessons:
        flash('لا يمكن حذف تصنيف يحتوي على دروس. قم بنقل الدروس إلى تصنيف آخر أولاً.', 'danger')
        return redirect(url_for('admin_categories'))
    db.session.delete(category)
    db.session.commit()
    log_activity(current_user.id, f'حذف تصنيفاً: {category.name}')
    flash('تم حذف التصنيف.', 'success')
    return redirect(url_for('admin_categories'))

# ==================== إدارة الدروس ====================
@app.route('/admin/lessons', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_lessons():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        content = request.form.get('content')
        youtube_url = request.form.get('youtube_url')
        category_id = request.form.get('category_id')
        order = request.form.get('order', 0)  # إصلاح: تعيين قيمة افتراضية 0
        is_published = 'is_published' in request.form
        if not title:
            flash('عنوان الدرس مطلوب.', 'danger')
        else:
            lesson = Lesson(
                title=title, 
                description=description, 
                content=content,
                youtube_url=youtube_url,
                category_id=int(category_id) if category_id else None,
                order=int(order) if order else 0,  # إصلاح: تحويل آمن
                is_published=is_published
            )
            db.session.add(lesson)
            db.session.commit()
            log_activity(current_user.id, f'أضاف درساً: {title}')
            flash('تم إضافة الدرس.', 'success')
        return redirect(url_for('admin_lessons'))
    lessons = Lesson.query.order_by(Lesson.order).all()
    categories = Category.query.order_by(Category.order).all()
    return render_template('admin/lessons.html', lessons=lessons, categories=categories)

@app.route('/admin/lesson/<int:lesson_id>/edit', methods=['POST'])
@login_required
@admin_required
def admin_edit_lesson(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    lesson.title = request.form.get('title')
    lesson.description = request.form.get('description')
    lesson.content = request.form.get('content')
    lesson.youtube_url = request.form.get('youtube_url')
    lesson.category_id = int(request.form.get('category_id')) if request.form.get('category_id') else None
    order_val = request.form.get('order', 0)
    lesson.order = int(order_val) if order_val else 0
    lesson.is_published = 'is_published' in request.form
    db.session.commit()
    log_activity(current_user.id, f'عدل درساً: {lesson.title}')
    flash('تم تحديث الدرس.', 'success')
    return redirect(url_for('admin_lessons'))

@app.route('/admin/lesson/<int:lesson_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_lesson(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    db.session.delete(lesson)
    db.session.commit()
    log_activity(current_user.id, f'حذف درساً: {lesson.title}')
    flash('تم حذف الدرس.', 'success')
    return redirect(url_for('admin_lessons'))

@app.route('/admin/questions', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_questions():
    if request.method == 'POST':
        lesson_id = request.form.get('lesson_id')
        q_type = request.form.get('type')
        question_text = request.form.get('question_text')
        correct_answer = request.form.get('correct_answer')
        option_a = request.form.get('option_a')
        option_b = request.form.get('option_b')
        option_c = request.form.get('option_c')
        option_d = request.form.get('option_d')
        difficulty = request.form.get('difficulty', 'medium')
        if not lesson_id or not question_text or not correct_answer:
            flash('الحقول المطلوبة: الدرس، نص السؤال، الإجابة الصحيحة.', 'danger')
        else:
            q = Question(lesson_id=int(lesson_id), type=q_type, question_text=question_text, correct_answer=correct_answer,
                       option_a=option_a, option_b=option_b, option_c=option_c, option_d=option_d, difficulty=difficulty)
            db.session.add(q)
            db.session.commit()
            log_activity(current_user.id, f'أضاف سؤالاً للدرس {lesson_id}')
            flash('تم إضافة السؤال.', 'success')
        return redirect(url_for('admin_questions'))
    questions = Question.query.all()
    lessons = Lesson.query.all()
    return render_template('admin/questions.html', questions=questions, lessons=lessons)

@app.route('/admin/question/<int:question_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_question(question_id):
    q = Question.query.get_or_404(question_id)
    db.session.delete(q)
    db.session.commit()
    log_activity(current_user.id, f'حذف سؤالاً رقم {question_id}')
    flash('تم حذف السؤال.', 'success')
    return redirect(url_for('admin_questions'))

@app.route('/admin/announcements', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_announcements():
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        if title and content:
            ann = Announcement(title=title, content=content, created_by=current_user.id)
            db.session.add(ann)
            db.session.commit()
            log_activity(current_user.id, f'أضاف إعلاناً: {title}')
            flash('تم نشر الإعلان.', 'success')
        else:
            flash('العنوان والمحتوى مطلوبان.', 'danger')
        return redirect(url_for('admin_announcements'))
    announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    return render_template('admin/announcements.html', announcements=announcements)

@app.route('/admin/announcement/<int:ann_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_announcement(ann_id):
    ann = Announcement.query.get_or_404(ann_id)
    db.session.delete(ann)
    db.session.commit()
    log_activity(current_user.id, f'حذف إعلاناً')
    flash('تم حذف الإعلان.', 'success')
    return redirect(url_for('admin_announcements'))

@app.route('/admin/audit_log')
@login_required
@admin_required
def admin_audit_log():
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(100).all()
    return render_template('admin/audit_log.html', logs=logs)

@app.route('/admin/recovery_requests')
@login_required
@admin_required
def admin_recovery_requests():
    requests = PasswordResetRequest.query.filter_by(is_used=False).order_by(PasswordResetRequest.created_at.desc()).all()
    return render_template('admin/recovery_requests.html', requests=requests)

@app.route('/admin/recovery_request/<int:req_id>/mark_used', methods=['POST'])
@login_required
@admin_required
def admin_mark_recovery_used(req_id):
    req = PasswordResetRequest.query.get_or_404(req_id)
    req.is_used = True
    db.session.commit()
    log_activity(current_user.id, f'تم استهلاك طلب استعادة للمستخدم {req.user_id}')
    flash('تم تحديث الطلب.', 'success')
    return redirect(url_for('admin_recovery_requests'))

@app.route('/admin/reset_db', methods=['POST'])
@login_required
@admin_required
def admin_reset_db():
    db.drop_all()
    db.create_all()
    
    admin = User(student_id='ADMIN001', full_name='مدير النظام', email='admin@mycourse.com', is_admin=True)
    admin.set_password('admin123')
    db.session.add(admin)
    db.session.commit()
    
    # إنشاء التصنيفات
    categories_data = [
        {'name': 'أساسيات البرمجة', 'description': 'تعلم أساسيات البرمجة والمفاهيم العامة', 'icon': 'fa-code', 'order': 1},
        {'name': 'قواعد البيانات', 'description': 'تعلم قواعد البيانات SQL و NoSQL', 'icon': 'fa-database', 'order': 2},
        {'name': 'الخوارزميات', 'description': 'فهم الخوارزميات وتصميم الحلول', 'icon': 'fa-brain', 'order': 3},
        {'name': 'برامج النظام', 'description': 'تعلم استخدام برامج الكمبيوتر الأساسية', 'icon': 'fa-desktop', 'order': 4},
        {'name': 'شبكات الحاسوب', 'description': 'أساسيات الشبكات والاتصالات', 'icon': 'fa-network-wired', 'order': 5},
    ]
    
    created_categories = {}
    for cat_data in categories_data:
        cat = Category(**cat_data)
        db.session.add(cat)
        db.session.flush()
        created_categories[cat_data['name']] = cat.id
    
    # إنشاء الدروس
    lessons_data = [
        {'category': 'أساسيات البرمجة', 'title': 'مقدمة في البرمجة', 'description': 'تعلم أساسيات البرمجة ومفاهيمها', 
         'content': '<h3>ما هي البرمجة؟</h3><p>البرمجة هي عملية كتابة مجموعة من التعليمات التي ينفذها الحاسوب لحل مشكلة معينة.</p>',
         'youtube': 'https://www.youtube.com/embed/HB4I2C2n7qg?si=ixHZkDQKR0uw5Q7V', 'order': 1},
        {'category': 'برامج النظام', 'title': 'برنامج الدفتر (Notepad)', 'description': 'تعلم استخدام برنامج الدفتر لكتابة النصوص',
         'content': '<h3>برنامج الدفتر (Notepad)</h3><p>برنامج بسيط لكتابة النصوص بدون تنسيق.</p>',
         'youtube': 'https://www.youtube.com/embed/abc123', 'order': 1},
        {'category': 'برامج النظام', 'title': 'برنامج الرسام (Paint)', 'description': 'تعلم استخدام برنامج الرسام للرسم والتصميم',
         'content': '<h3>برنامج الرسام (Paint)</h3><p>برنامج بسيط للرسم الرقمي.</p>',
         'youtube': 'https://www.youtube.com/embed/def456', 'order': 2},
        {'category': 'برامج النظام', 'title': 'برنامج الملاحظات (Sticky Notes)', 'description': 'تعلم استخدام الملاحظات اللاصقة الرقمية',
         'content': '<h3>برنامج الملاحظات (Sticky Notes)</h3><p>برنامج لكتابة الملاحظات السريعة.</p>',
         'youtube': 'https://www.youtube.com/embed/ghi789', 'order': 3},
        {'category': 'برامج النظام', 'title': 'مسجل الصوت (Sound Recorder)', 'description': 'تعلم استخدام مسجل الصوت لتسجيل الأصوات',
         'content': '<h3>مسجل الصوت (Sound Recorder)</h3><p>برنامج لتسجيل الأصوات من الميكروفون.</p>',
         'youtube': 'https://www.youtube.com/embed/jkl012', 'order': 4},
    ]
    
    lesson_ids = {}
    for lesson_data in lessons_data:
        cat_name = lesson_data.pop('category')
        lesson = Lesson(
            category_id=created_categories[cat_name],
            title=lesson_data['title'],
            description=lesson_data['description'],
            content=lesson_data['content'],
            youtube_url=lesson_data['youtube'],
            order=lesson_data['order'],
            is_published=True
        )
        db.session.add(lesson)
        db.session.flush()
        lesson_ids[lesson_data['title']] = lesson.id
    
    # إنشاء الأسئلة
    questions_data = [
        {'lesson': 'مقدمة في البرمجة', 'type': 'MCQ', 'text': 'ما هي لغة البرمجة التي تتميز بسهولة تعلمها؟', 
         'a': 'بايثون', 'b': 'سي++', 'c': 'جافا', 'd': 'راست', 'correct': 'بايثون', 'difficulty': 'easy'},
        {'lesson': 'مقدمة في البرمجة', 'type': 'TRUE_FALSE', 'text': 'المتغير يمكن أن يحمل قيماً مختلفة أثناء تنفيذ البرنامج.',
         'a': 'صحيح', 'b': 'خطأ', 'correct': 'صحيح', 'difficulty': 'easy'},
        {'lesson': 'برنامج الدفتر (Notepad)', 'type': 'MCQ', 'text': 'ما هي اختصار حفظ ملف في الدفتر؟',
         'a': 'Ctrl+S', 'b': 'Ctrl+O', 'c': 'Ctrl+N', 'd': 'Ctrl+P', 'correct': 'Ctrl+S', 'difficulty': 'easy'},
        {'lesson': 'برنامج الدفتر (Notepad)', 'type': 'TRUE_FALSE', 'text': 'الدفتر يدعم تنسيق النصوص مثل الألوان والخطوط.',
         'a': 'صحيح', 'b': 'خطأ', 'correct': 'خطأ', 'difficulty': 'easy'},
        {'lesson': 'برنامج الرسام (Paint)', 'type': 'MCQ', 'text': 'ما هي أداة الرسم التي تستخدم لرسم خطوط مستقيمة؟',
         'a': 'الخط', 'b': 'المنحنى', 'c': 'القلم الرصاص', 'd': 'الفرشاة', 'correct': 'الخط', 'difficulty': 'easy'},
        {'lesson': 'برنامج الرسام (Paint)', 'type': 'TRUE_FALSE', 'text': 'يمكنك تغيير حجم الصورة في برنامج الرسام.',
         'a': 'صحيح', 'b': 'خطأ', 'correct': 'صحيح', 'difficulty': 'easy'},
        {'lesson': 'برنامج الملاحظات (Sticky Notes)', 'type': 'MCQ', 'text': 'ما هي اختصار إنشاء ملاحظة جديدة؟',
         'a': 'Ctrl+N', 'b': 'Ctrl+O', 'c': 'Ctrl+S', 'd': 'Ctrl+P', 'correct': 'Ctrl+N', 'difficulty': 'easy'},
        {'lesson': 'مسجل الصوت (Sound Recorder)', 'type': 'MCQ', 'text': 'ما هو الزر المستخدم لبدء التسجيل؟',
         'a': 'زر التسجيل (Record)', 'b': 'زر الإيقاف (Stop)', 'c': 'زر التشغيل (Play)', 'd': 'زر الإيقاف المؤقت (Pause)',
         'correct': 'زر التسجيل (Record)', 'difficulty': 'easy'},
    ]
    
    for q in questions_data:
        lesson_title = q.pop('lesson')
        question = Question(
            lesson_id=lesson_ids.get(lesson_title),
            type=q['type'],
            question_text=q['text'],
            option_a=q.get('a'),
            option_b=q.get('b'),
            option_c=q.get('c'),
            option_d=q.get('d'),
            correct_answer=q['correct'],
            difficulty=q['difficulty']
        )
        db.session.add(question)
    
    db.session.commit()
    log_activity(current_user.id, 'إعادة تعيين قاعدة البيانات مع تصنيفات ودروس جديدة')
    flash('✅ تم إعادة تعيين قاعدة البيانات مع 5 تصنيفات و 7 دروس وأسئلة!', 'success')
    return redirect(url_for('admin_dashboard'))

# ==================== نقطة التشغيل ====================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        upgrade_database()
        
        if not User.query.filter_by(email='admin@mycourse.com').first():
            admin = User(student_id='ADMIN001', full_name='مدير النظام', email='admin@mycourse.com', is_admin=True)
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("✅ Admin: admin@mycourse.com / admin123")
        
        if Category.query.count() == 0:
            print("⚠️ لا توجد تصنيفات. جاري إنشاء تصنيفات افتراضية...")
            categories = [
                Category(name='أساسيات البرمجة', description='تعلم أساسيات البرمجة', icon='fa-code', order=1),
                Category(name='قواعد البيانات', description='تعلم قواعد البيانات', icon='fa-database', order=2),
                Category(name='برامج النظام', description='برامج الكمبيوتر الأساسية', icon='fa-desktop', order=3),
                Category(name='شبكات الحاسوب', description='أساسيات الشبكات', icon='fa-network-wired', order=4),
            ]
            db.session.add_all(categories)
            db.session.commit()
            print("✅ تم إنشاء تصنيفات افتراضية.")
            
            if Lesson.query.count() == 0:
                cat = Category.query.filter_by(name='برامج النظام').first()
                if cat:
                    lessons = [
                        Lesson(category_id=cat.id, title='برنامج الدفتر (Notepad)', description='تعلم استخدام الدفتر', order=1, is_published=True),
                        Lesson(category_id=cat.id, title='برنامج الرسام (Paint)', description='تعلم استخدام الرسام', order=2, is_published=True),
                        Lesson(category_id=cat.id, title='برنامج الملاحظات (Sticky Notes)', description='تعلم استخدام الملاحظات', order=3, is_published=True),
                        Lesson(category_id=cat.id, title='مسجل الصوت (Sound Recorder)', description='تعلم استخدام مسجل الصوت', order=4, is_published=True),
                    ]
                    db.session.add_all(lessons)
                    db.session.commit()
                    print("✅ تم إنشاء دروس افتراضية لبرامج النظام.")
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)