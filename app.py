from flask import Flask, render_template, request, redirect, url_for, session, flash, g
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
from pathlib import Path

# Определяем абсолютные пути
BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__,
            template_folder=str(BASE_DIR / 'templates'),
            static_folder=str(BASE_DIR / 'static'))
app.secret_key = 'your-secret-key-12345'
app.config['DATABASE'] = str(BASE_DIR / 'database' / 'messenger.db')

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        
        # Пользователи
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Чаты
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                is_group BOOLEAN DEFAULT 1,
                is_public BOOLEAN DEFAULT 0,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        ''')
        
        # Участники чатов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, user_id),
                FOREIGN KEY (chat_id) REFERENCES chats(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Сообщения
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (chat_id) REFERENCES chats(id)
            )
        ''')
        
        # Создаем общий чат, если его нет
        cursor.execute("SELECT id FROM chats WHERE name = 'Общий чат' AND is_public = 1")
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO chats (name, is_group, is_public) VALUES (?, ?, ?)",
                ('Общий чат', 1, 1)
            )
            print("Создан общий чат для всех пользователей")
        
        db.commit()

@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'db'):
        g.db.close()

# Создаем папки при запуске
with app.app_context():
    os.makedirs(BASE_DIR / 'database', exist_ok=True)
    os.makedirs(BASE_DIR / 'templates', exist_ok=True)
    os.makedirs(BASE_DIR / 'static/css', exist_ok=True)
    init_db()
    print("Database initialized!")

# Маршруты
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('SELECT id, password FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = username
            
            # Добавляем пользователя в общий чат при первом входе
            cursor.execute('SELECT id FROM chats WHERE name = "Общий чат" AND is_public = 1')
            general_chat = cursor.fetchone()
            if general_chat:
                cursor.execute('''
                    INSERT OR IGNORE INTO chat_members (chat_id, user_id) 
                    VALUES (?, ?)
                ''', (general_chat['id'], user['id']))
                db.commit()
            
            flash('Вход выполнен успешно!')
            return redirect(url_for('dashboard'))
        else:
            flash('Неверное имя пользователя или пароль')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        db = get_db()
        cursor = db.cursor()
        
        # Проверяем существование пользователя
        cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
        if cursor.fetchone():
            flash('Пользователь с таким именем уже существует')
            return render_template('register.html')
        
        # Создаем нового пользователя
        hashed_password = generate_password_hash(password)
        cursor.execute(
            'INSERT INTO users (username, password) VALUES (?, ?)',
            (username, hashed_password)
        )
        user_id = cursor.lastrowid
        
        # Добавляем пользователя в общий чат
        cursor.execute('SELECT id FROM chats WHERE name = "Общий чат" AND is_public = 1')
        general_chat = cursor.fetchone()
        if general_chat:
            cursor.execute(
                'INSERT OR IGNORE INTO chat_members (chat_id, user_id) VALUES (?, ?)',
                (general_chat['id'], user_id)
            )
        
        db.commit()
        flash('Регистрация успешна! Теперь вы можете войти.')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему')
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor()
    
    # Получаем чаты пользователя
    cursor.execute('''
        SELECT c.* FROM chats c
        JOIN chat_members cm ON c.id = cm.chat_id
        WHERE cm.user_id = ?
        ORDER BY 
            CASE WHEN c.name = 'Общий чат' THEN 1 ELSE 2 END,
            c.created_at DESC
    ''', (session['user_id'],))
    chats = cursor.fetchall()
    
    # Получаем всех пользователей для добавления в чаты
    cursor.execute('SELECT id, username FROM users WHERE id != ? ORDER BY username', (session['user_id'],))
    all_users = cursor.fetchall()
    
    return render_template('dashboard.html', 
                         username=session['username'], 
                         chats=chats,
                         all_users=all_users)

@app.route('/create_chat', methods=['POST'])
def create_chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    chat_name = request.form['chat_name']
    selected_users = request.form.getlist('users')  # Получаем список выбранных пользователей
    
    db = get_db()
    cursor = db.cursor()
    
    # Создаем чат
    cursor.execute(
        'INSERT INTO chats (name, is_group, created_by) VALUES (?, ?, ?)',
        (chat_name, 1, session['user_id'])
    )
    chat_id = cursor.lastrowid
    
    # Добавляем создателя в чат
    cursor.execute(
        'INSERT INTO chat_members (chat_id, user_id) VALUES (?, ?)',
        (chat_id, session['user_id'])
    )
    
    # Добавляем выбранных пользователей в чат
    for user_id in selected_users:
        cursor.execute(
            'INSERT OR IGNORE INTO chat_members (chat_id, user_id) VALUES (?, ?)',
            (chat_id, int(user_id))
        )
    
    db.commit()
    flash(f'Чат "{chat_name}" создан!')
    return redirect(url_for('chat', chat_id=chat_id))

@app.route('/chat/<int:chat_id>')
def chat(chat_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor()
    
    # Проверяем доступ к чату
    cursor.execute('SELECT 1 FROM chat_members WHERE chat_id = ? AND user_id = ?',
                  (chat_id, session['user_id']))
    if not cursor.fetchone():
        flash('У вас нет доступа к этому чату')
        return redirect(url_for('dashboard'))
    
    # Получаем информацию о чате
    cursor.execute('SELECT * FROM chats WHERE id = ?', (chat_id,))
    chat_info = cursor.fetchone()
    
    # Получаем сообщения
    cursor.execute('''
        SELECT m.*, u.username FROM messages m
        JOIN users u ON m.user_id = u.id
        WHERE m.chat_id = ?
        ORDER BY m.timestamp
    ''', (chat_id,))
    messages = cursor.fetchall()
    
    # Получаем участников чата
    cursor.execute('''
        SELECT u.id, u.username FROM chat_members cm
        JOIN users u ON cm.user_id = u.id
        WHERE cm.chat_id = ?
    ''', (chat_id,))
    members = cursor.fetchall()
    
    # Получаем всех пользователей для добавления в чат
    cursor.execute('''
        SELECT u.id, u.username FROM users u
        WHERE u.id NOT IN (
            SELECT cm2.user_id FROM chat_members cm2 
            WHERE cm2.chat_id = ?
        ) AND u.id != ?
    ''', (chat_id, session['user_id']))
    available_users = cursor.fetchall()
    
    return render_template('chat.html',
                         chat=chat_info,
                         messages=messages,
                         members=members,
                         available_users=available_users,
                         user_id=session['user_id'],
                         username=session['username'])

@app.route('/send_message/<int:chat_id>', methods=['POST'])
def send_message(chat_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    content = request.form.get('content', '').strip()
    
    if content:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            'INSERT INTO messages (content, user_id, chat_id) VALUES (?, ?, ?)',
            (content, session['user_id'], chat_id)
        )
        db.commit()
        flash('Сообщение отправлено!')
    
    return redirect(url_for('chat', chat_id=chat_id))

@app.route('/add_to_chat/<int:chat_id>', methods=['POST'])
def add_to_chat(chat_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id_to_add = request.form.get('user_id', '').strip()
    
    if not user_id_to_add:
        flash('Выберите пользователя')
        return redirect(url_for('chat', chat_id=chat_id))
    
    db = get_db()
    cursor = db.cursor()
    
    # Проверяем, что чат существует и пользователь имеет к нему доступ
    cursor.execute('SELECT 1 FROM chat_members WHERE chat_id = ? AND user_id = ?',
                  (chat_id, session['user_id']))
    if not cursor.fetchone():
        flash('У вас нет доступа к этому чату')
        return redirect(url_for('dashboard'))
    
    # Проверяем, не добавлен ли уже пользователь в чат
    cursor.execute('SELECT 1 FROM chat_members WHERE chat_id = ? AND user_id = ?',
                  (chat_id, user_id_to_add))
    if cursor.fetchone():
        flash('Этот пользователь уже в чате')
        return redirect(url_for('chat', chat_id=chat_id))
    
    # Добавляем пользователя в чат
    cursor.execute(
        'INSERT INTO chat_members (chat_id, user_id) VALUES (?, ?)',
        (chat_id, user_id_to_add)
    )
    
    db.commit()
    
    # Получаем имя пользователя для сообщения
    cursor.execute('SELECT username FROM users WHERE id = ?', (user_id_to_add,))
    added_user = cursor.fetchone()
    
    flash(f'Пользователь {added_user["username"]} добавлен в чат!' if added_user else 'Пользователь добавлен в чат')
    return redirect(url_for('chat', chat_id=chat_id))

@app.route('/users')
def users_list():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor()
    
    # Получаем всех пользователей кроме текущего
    cursor.execute('SELECT id, username, created_at FROM users WHERE id != ? ORDER BY username', 
                  (session['user_id'],))
    users = cursor.fetchall()
    
    return render_template('users.html', users=users, username=session['username'])

@app.route('/create_private_chat/<int:user_id>')
def create_private_chat(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor()
    
    # Проверяем, существует ли уже приватный чат между этими пользователями
    cursor.execute('''
        SELECT c.id FROM chats c
        JOIN chat_members cm1 ON c.id = cm1.chat_id
        JOIN chat_members cm2 ON c.id = cm2.chat_id
        WHERE c.is_group = 0 
        AND cm1.user_id = ? 
        AND cm2.user_id = ?
        AND c.created_by IS NULL
    ''', (session['user_id'], user_id))
    
    existing_chat = cursor.fetchone()
    
    if existing_chat:
        return redirect(url_for('chat', chat_id=existing_chat['id']))
    
    # Получаем имя пользователя для названия чата
    cursor.execute('SELECT username FROM users WHERE id = ?', (user_id,))
    other_user = cursor.fetchone()
    
    if not other_user:
        flash('Пользователь не найден')
        return redirect(url_for('users_list'))
    
    # Создаем новый приватный чат
    chat_name = f"{session['username']} и {other_user['username']}"
    cursor.execute(
        'INSERT INTO chats (name, is_group, created_by) VALUES (?, ?, ?)',
        (chat_name, 0, session['user_id'])
    )
    chat_id = cursor.lastrowid
    
    # Добавляем обоих пользователей в чат
    cursor.execute(
        'INSERT INTO chat_members (chat_id, user_id) VALUES (?, ?)',
        (chat_id, session['user_id'])
    )
    cursor.execute(
        'INSERT INTO chat_members (chat_id, user_id) VALUES (?, ?)',
        (chat_id, user_id)
    )
    
    db.commit()
    
    flash(f'Создан приватный чат с {other_user["username"]}')
    return redirect(url_for('chat', chat_id=chat_id))

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)