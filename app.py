import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import json

# ==================== إعدادات التطبيق ====================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_super_secret_key_here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# تهيئة المكتبات
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
socketio = SocketIO(app)

# ==================== نماذج قاعدة البيانات ====================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class ExamResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    exam_id = db.Column(db.Integer, nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    answers = db.Column(db.Text)
    completed_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==================== الصفحات ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/lessons')
def lessons():
    return render_template('lessons.html')

@app.route('/office')
def office():
    return render_template('office.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('اسم المستخدم موجود بالفعل', 'danger')
            return redirect(url_for('register'))
        
        new_user = User(
            username=username,
            full_name=full_name,
            email=email,
            phone=phone
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        
        flash('تم إنشاء الحساب بنجاح!', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            flash('تم تسجيل الدخول بنجاح', 'success')
            return redirect(url_for('index'))
        else:
            flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('تم تسجيل الخروج', 'success')
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user)

# ==================== الاختبارات ====================

exams_data = [
    {
        'title': 'اختبار أساسيات الحاسوب',
        'description': 'اختبر معرفتك بمكونات الحاسوب.',
        'duration': 10,
        'questions': [
            {'question': 'ما هي وحدة المعالجة المركزية؟', 'options': ['الذاكرة', 'المعالج', 'القرص الصلب', 'الشاشة'], 'answer': 1},
            {'question': 'ما هو نظام التشغيل؟', 'options': ['برنامج تطبيقي', 'برنامج يدير الأجهزة', 'جهاز', 'لا شيء'], 'answer': 1},
            {'question': 'ما هي وظيفة الرام؟', 'options': ['تخزين الملفات', 'تشغيل البرامج مؤقتاً', 'توصيل الإنترنت', 'عرض الصور'], 'answer': 1}
        ]
    }
]

@app.route('/exam/<int:exam_index>')
@login_required
def exam(exam_index):   # <--- تم تغيير الاسم من take_exam إلى exam
    if exam_index >= len(exams_data):
        flash('الاختبار غير موجود', 'danger')
        return redirect(url_for('lessons'))
    
    exam_info = exams_data[exam_index]
    exam_info['index'] = exam_index
    return render_template('exam.html', exam=exam_info)

@app.route('/submit_exam/<int:exam_index>', methods=['POST'])
@login_required
def submit_exam(exam_index):
    if exam_index >= len(exams_data):
        return jsonify({'error': 'الاختبار غير موجود'})
    
    questions = exams_data[exam_index]['questions']
    answers = request.json.get('answers', {})
    
    score = 0
    total = len(questions)
    correct_answers = []
    
    for i, q in enumerate(questions):
        user_answer = answers.get(str(i))
        correct = q['answer']
        is_correct = user_answer == correct
        if is_correct:
            score += 1
        correct_answers.append({
            'question_index': i,
            'user_answer': user_answer,
            'correct': correct,
            'is_correct': is_correct
        })
    
    result = ExamResult(
        user_id=current_user.id,
        exam_id=exam_index + 1,
        score=score,
        total=total,
        answers=json.dumps(correct_answers)
    )
    db.session.add(result)
    db.session.commit()
    
    return jsonify({
        'score': score,
        'total': total,
        'percentage': int((score / total) * 100),
        'correct_answers': correct_answers
    })

@app.route('/results')
@login_required
def results():
    results = ExamResult.query.filter_by(user_id=current_user.id).order_by(ExamResult.completed_at.desc()).all()
    return render_template('results.html', results=results)

# ==================== الدردشة ====================

@socketio.on('send_message')
def handle_send_message(data):
    content = data.get('content')
    if not content:
        return
    
    new_message = Message(
        user_id=current_user.id,
        content=content
    )
    db.session.add(new_message)
    db.session.commit()
    
    emit('new_message', {
        'user': current_user.full_name,
        'username': current_user.username,
        'content': content,
        'timestamp': datetime.datetime.now().strftime('%H:%M')
    }, broadcast=True)

@app.route('/chat')
@login_required
def chat():
    messages = Message.query.order_by(Message.created_at.asc()).limit(100).all()
    return render_template('chat.html', messages=messages)

# ==================== تشغيل التطبيق ====================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)