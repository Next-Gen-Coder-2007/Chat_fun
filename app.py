from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid
import secrets
from datetime import datetime
from markupsafe import escape
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
socketio = SocketIO(app, cors_allowed_origins="*")

# Data structures
chat_rooms = {}
room_members = {}
message_seen_by = {}  # Track who has seen each message

# Admin credentials (in production, use proper authentication)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"  # Change this!

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/create_room', methods=['POST'])
def create_room():
    room_name = request.form.get('room_name', 'Unnamed Room')
    room_id = str(uuid.uuid4())[:8]
    chat_rooms[room_id] = {
        'name': room_name,
        'messages': [],
        'created_at': datetime.now().isoformat(),
        'creator': request.form.get('creator')
    }
    room_members[room_id] = []
    
    return redirect(url_for('chat_room', room_id=room_id))

@app.route('/join/<room_id>')
def join_room_page(room_id):
    if room_id not in chat_rooms:
        return "Room not found!", 404
    return render_template('join.html', room_id=room_id, room_name=chat_rooms[room_id]['name'])

@app.route('/chat/<room_id>')
def chat_room(room_id):
    if room_id not in chat_rooms:
        return "Room not found!", 404
    
    username = request.args.get('username')
    if not username:
        # fallback to creator if no username provided
        username = chat_rooms[room_id]['creator']
    
    session['username'] = username
    session['room_id'] = room_id
    
    return render_template('chat.html', 
                           room_id=room_id, 
                           room_name=chat_rooms[room_id]['name'],
                           username=username,
                           messages=chat_rooms[room_id]['messages'])

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('admin_login.html', error="Invalid credentials")
    
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    # Calculate statistics
    total_rooms = len(chat_rooms)
    total_messages = sum(len(room['messages']) for room in chat_rooms.values())
    active_users = sum(len(members) for members in room_members.values())
    
    return render_template('admin_dashboard.html',
                         chat_rooms=chat_rooms,
                         room_members=room_members,
                         total_rooms=total_rooms,
                         total_messages=total_messages,
                         active_users=active_users)

@app.route('/admin/room/<room_id>')
def admin_room_details(room_id):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    if room_id not in chat_rooms:
        return "Room not found!", 404
    
    return render_template('admin_room_details.html',
                         room_id=room_id,
                         room=chat_rooms[room_id],
                         members=room_members.get(room_id, []))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))

@socketio.on('join')
def on_join(data):
    username = escape(data['username'])
    room = data['room']

    # Initialize room in room_members if not present
    if room not in room_members:
        room_members[room] = []

    join_room(room)

    if username not in room_members[room]:
        room_members[room].append(username)

    emit('status', {
        'msg': f'{username} has joined the room.',
        'username': username
    }, room=room)

    emit('members_update', {
        'members': room_members[room]
    }, room=room)


@socketio.on('leave')
def on_leave(data):
    username = escape(data['username'])
    room = data['room']

    leave_room(room)

    # Only try to remove if the room exists and the user is in it
    if room in room_members and username in room_members[room]:
        room_members[room].remove(username)

    emit('status', {
        'msg': f'{username} has left the room.',
        'username': username
    }, room=room)

    emit('members_update', {
        'members': room_members.get(room, [])
    }, room=room)


@socketio.on('disconnect')
def handle_disconnect():
    username = session.get('username')
    room = session.get('room_id')

    if username and room:
        if room in room_members and username in room_members[room]:
            room_members[room].remove(username)

        emit('status', {
            'msg': f'{username} has disconnected.',
            'username': username
        }, room=room)

        emit('members_update', {
            'members': room_members.get(room, [])
        }, room=room)


@socketio.on('typing')
def handle_typing(data):
    username = escape(data['username'])
    room = data['room']
    is_typing = data['is_typing']
    
    emit('user_typing', {
        'username': username,
        'is_typing': is_typing
    }, room=room, include_self=False)

@socketio.on('message')
def handle_message(data):
    try:
        room = data.get('room')
        username = escape(data.get('username', ''))
        message = escape(data.get('message', ''))
        message_type = data.get('type', 'text')  # text or gif
        
        if not all([room, username, message]):
            return
        
        if room not in chat_rooms:
            emit('error', {'msg': 'Room not found'})
            return
        
        if len(message) > 2000:
            emit('error', {'msg': 'Message too long'})
            return
        
        message_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        msg_data = {
            'id': message_id,
            'username': username,
            'message': message,
            'type': message_type,
            'timestamp': timestamp,
            'edited': False,
            'seen_by': [username]  # Sender has seen their own message
        }
        
        chat_rooms[room]['messages'].append(msg_data)
        message_seen_by[message_id] = [username]
        
        emit('message', msg_data, room=room)
        
    except Exception as e:
        app.logger.error(f"Error handling message: {e}")
        emit('error', {'msg': 'Failed to send message'})

@socketio.on('edit_message')
def handle_edit_message(data):
    try:
        room = data.get('room')
        message_id = data.get('message_id')
        new_message = escape(data.get('message', ''))
        username = escape(data.get('username', ''))
        
        if room not in chat_rooms:
            return
        
        # Find and update the message
        for msg in chat_rooms[room]['messages']:
            if msg['id'] == message_id and msg['username'] == username:
                msg['message'] = new_message
                msg['edited'] = True
                msg['edited_at'] = datetime.now().isoformat()
                
                emit('message_edited', {
                    'message_id': message_id,
                    'message': new_message,
                    'edited': True
                }, room=room)
                break
                
    except Exception as e:
        app.logger.error(f"Error editing message: {e}")

@socketio.on('message_seen')
def handle_message_seen(data):
    try:
        room = data.get('room')
        message_id = data.get('message_id')
        username = escape(data.get('username', ''))
        
        if room not in chat_rooms:
            return
        
        # Update seen_by list
        for msg in chat_rooms[room]['messages']:
            if msg['id'] == message_id:
                if username not in msg['seen_by']:
                    msg['seen_by'].append(username)
                
                emit('message_seen_update', {
                    'message_id': message_id,
                    'seen_by': msg['seen_by']
                }, room=room)
                break
                
    except Exception as e:
        app.logger.error(f"Error updating seen status: {e}")

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
